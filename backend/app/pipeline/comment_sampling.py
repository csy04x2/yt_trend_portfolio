"""댓글 표본 정책 — 어느 영상의 댓글을, 영상마다 몇 개까지 받을지 정한다.

설계와 근거는 `docs/design/comment-sampling-policy.md` 에 있다. 이 모듈은 그
문서의 규칙을 **순수 함수**로 옮긴 것이다. DB·네트워크를 만지지 않는다 —
같은 영상 메타와 같은 정책을 넣으면 언제나 같은 표본이 나온다.

## 왜 따로 두는가

지금까지 채널마다 영상 2편의 댓글만 받았다. 침착맨 Development 90편 중
댓글 관측이 있는 것은 8편뿐이고(8 capped, 82 not_sampled), 그래서 댓글 기반
지표가 NOT_READY 다. 편수만 늘리면 되는 문제가 아니다. 어느 영상을 골랐는지가
결과를 바꾸므로, **고른 규칙과 확률을 영상마다 남겨야** 나중에 가중치로 되돌릴
수 있다.

## 세 가지 약속

1. **Holdout 성과를 보지 않는다.** 성과 층(tier) 경계는 holdout 이 아닌 영상의
   성과값으로만 자른다. holdout 영상은 성과값이 들어와도 읽지 않고 층을
   `blind` 로 둔다. holdout 규칙에 성과 층화를 걸면 ValueError 다.
2. **split 을 바꾸지 않는다.** 영상의 `split` 은 읽기만 한다. 표본은 split 안에서
   뽑는다.
3. **댓글 내용을 보지 않는다.** 선정에 쓰는 것은 메타(유형·길이·성과·댓글 수·
   댓글 사용 중지·라이브)뿐이다. Phase 2 원칙과 같다 — 희귀 반응을 찾으려고
   골라 넣지 않는다.

## 영상 입력

각 영상은 dict 이고 아래 키를 읽는다. 없는 키는 None 으로 본다.

    video_id, split, type_code, length_axis, <performance_field>,
    comment_count, comments_disabled, is_live
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction

POLICY_VERSION = "comment-sampling-v0.1"

# 결정 값
SELECTED = "selected"
NOT_SAMPLED = "not_sampled"     # 자격은 있었지만 표본에 들지 않음
EXCLUDED = "excluded"           # 자격이 없음 (사유는 reason)

# split 규칙의 mode
CENSUS = "census"               # 자격 있는 영상 전부
STRATIFIED = "stratified"       # 유형 × 길이 × 성과 층
BLIND = "blind"                 # 유형 × 길이만 (성과를 보지 않음)
SKIP = "skip"                   # 이번 실행에서 받지 않음
MODES = (CENSUS, STRATIFIED, BLIND, SKIP)

# split 이 없거나 규칙에 없는 split 에 쓰는 키
ANY_SPLIT = "*"

UNTYPED = "UNTYPED"
UNKNOWN_TIER = "unknown"
BLIND_TIER = "blind"

# commentThreads.list 한 페이지 최대 건수 (API 상한)
PAGE_SIZE = 100


@dataclass(frozen=True)
class SplitRule:
    mode: str
    # stratified / blind 에서 목표 편수. census / skip 에서는 쓰지 않는다
    target: int | None = None


@dataclass(frozen=True)
class SamplingPolicy:
    name: str
    split_rules: dict[str, SplitRule]
    seed: int = 42

    # ---- 영상 자격 ----
    # 수집 시점 댓글 수가 이보다 적으면 제외. comment_count 는 답글을 포함한 값이다
    min_comments: int = 20
    exclude_live: bool = True

    # ---- 층화 ----
    # 유형 × 길이 칸마다 최소 편수 (칸에 영상이 그보다 적으면 전부)
    min_per_cell: int = 2
    n_tiers: int = 3
    performance_field: str = "view_multiple"
    # 이 split 들의 성과는 읽지 않는다. 층 경계 계산에서도 뺀다
    holdout_splits: tuple[str, ...] = ("holdout",)
    length_groups: dict[str, str] = field(default_factory=lambda: {
        "shorts": "shorts", "standard": "longform",
        "long": "longform", "longform": "longform",
    })

    # ---- 영상당 댓글 ----
    order: str = "time"            # commentThreads order. 편향은 설계 문서 3장
    collect_cap: int = 100         # 받을 원댓글 상한
    reply_threads: int = 0         # 답글을 따로 받을 thread 수 상한 (수집 순서 앞에서부터)
    reply_pages: int = 0           # thread 당 comments.list 페이지 상한
    label_cap: int = 50            # 판정에 보낼 원댓글 상한 (수집분에서 해시로 균등 추출)

    def rule_for(self, split: str | None) -> SplitRule:
        if split in self.split_rules:
            return self.split_rules[split]
        if ANY_SPLIT in self.split_rules:
            return self.split_rules[ANY_SPLIT]
        return SplitRule(SKIP)

    def validate(self) -> None:
        for split, rule in self.split_rules.items():
            if rule.mode not in MODES:
                raise ValueError(f"알 수 없는 mode {rule.mode!r} (split={split})")
            if rule.mode in (STRATIFIED, BLIND) and (rule.target is None or rule.target < 0):
                raise ValueError(f"{split}: {rule.mode} 에는 0 이상의 target 이 필요하다")
            if split in self.holdout_splits and rule.mode == STRATIFIED:
                raise ValueError(
                    f"{split} 은 holdout 이다 — 성과 층화(stratified)를 쓸 수 없다. "
                    "blind / census / skip 중 하나로 둔다")
        if self.order not in ("time", "relevance"):
            raise ValueError(f"order 는 time 또는 relevance: {self.order!r}")
        if self.n_tiers < 1 or self.min_per_cell < 0:
            raise ValueError("n_tiers >= 1, min_per_cell >= 0")
        for k in ("collect_cap", "reply_threads", "reply_pages", "label_cap"):
            if getattr(self, k) < 0:
                raise ValueError(f"{k} 는 0 이상")

    @property
    def top_pages(self) -> int:
        return math.ceil(self.collect_cap / PAGE_SIZE)

    def to_json(self) -> str:
        d = asdict(self)
        d["policy_version"] = POLICY_VERSION
        return json.dumps(d, ensure_ascii=False, sort_keys=True)


# --------------------------------------------------------------------------
# 프리셋 — 추천값이지 승인된 값이 아니다. 설계 문서 5장·6장을 볼 것
# --------------------------------------------------------------------------

def _split_rules(dev: SplitRule, disc: SplitRule, hold: SplitRule,
                 anything: SplitRule) -> dict[str, SplitRule]:
    return {"development": dev, "discovery": disc, "holdout": hold, ANY_SPLIT: anything}


PRESETS: dict[str, SamplingPolicy] = {
    # Development 댓글 지표의 not_sampled 를 없애는 최소치
    "light": SamplingPolicy(
        name="light",
        split_rules=_split_rules(SplitRule(CENSUS), SplitRule(SKIP), SplitRule(SKIP),
                                 SplitRule(STRATIFIED, 60)),
        collect_cap=100, reply_threads=0, reply_pages=0, label_cap=50,
    ),
    # 추천 기본값 (승인 전)
    "standard": SamplingPolicy(
        name="standard",
        split_rules=_split_rules(SplitRule(CENSUS), SplitRule(STRATIFIED, 45),
                                 SplitRule(BLIND, 60), SplitRule(STRATIFIED, 150)),
        collect_cap=500, reply_threads=20, reply_pages=1, label_cap=100,
    ),
    "full": SamplingPolicy(
        name="full",
        split_rules=_split_rules(SplitRule(CENSUS), SplitRule(CENSUS), SplitRule(CENSUS),
                                 SplitRule(CENSUS)),
        collect_cap=2000, reply_threads=50, reply_pages=2, label_cap=300,
    ),
}


def preset(name: str, **overrides) -> SamplingPolicy:
    if name not in PRESETS:
        raise KeyError(f"프리셋은 {sorted(PRESETS)} 중 하나: {name!r}")
    return replace(PRESETS[name], **overrides)


# --------------------------------------------------------------------------
# 결과
# --------------------------------------------------------------------------

@dataclass
class SamplingPlan:
    policy: SamplingPolicy
    # 길이 묶음별 성과 층 경계 (holdout 제외 모집단에서 계산)
    cutpoints: dict[str, list[float]]
    decisions: list[dict]
    warnings: list[str]

    def selected(self) -> list[dict]:
        return [d for d in self.decisions if d["decision"] == SELECTED]

    def by_id(self) -> dict[str, dict]:
        return {d["video_id"]: d for d in self.decisions}


# --------------------------------------------------------------------------
# 순수 계산
# --------------------------------------------------------------------------

def rank_key(seed: int, split: str | None, video_id: str) -> str:
    """영상 순번. 같은 seed·split·ID 면 언제나 같다.

    split_dataset 과 같은 sha256 방식이다. 영상 목록이 늘어도 기존 영상의
    순번은 바뀌지 않는다. 같은 층 안에서는 목표 편수를 늘리면 앞의 표본에
    더해진다(층 사이 배분이 바뀌는 경계에서는 예외가 있다 — apportion 참고).
    """
    return hashlib.sha256(f"{seed}\0{split or ''}\0{video_id}".encode()).hexdigest()


def length_group(video: dict, policy: SamplingPolicy) -> str:
    return policy.length_groups.get(video.get("length_axis") or "", "unknown")


def _number(x) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)) and math.isfinite(x):
        return float(x)
    return None


def exclusion_reason(video: dict, policy: SamplingPolicy) -> str | None:
    """자격이 없으면 사유, 있으면 None. 앞의 사유가 먼저다."""
    if video.get("comments_disabled"):
        return "comments_disabled"
    if policy.exclude_live and video.get("is_live"):
        return "live"
    cc = video.get("comment_count")
    if cc is None:
        return "comment_count_unknown"
    if cc < policy.min_comments:
        return "below_comment_threshold"
    return None


def tier_cutpoints(videos: list[dict], policy: SamplingPolicy) -> dict[str, list[float]]:
    """길이 묶음마다 성과 분위 경계.

    holdout split 영상은 성과값이 있어도 **읽지 않는다.** 자격 여부와 무관하게
    holdout 이 아닌 영상 전부를 모집단으로 쓴다 — 댓글 수 기준을 바꿨다고
    층 경계가 흔들리지 않게.
    """
    values: dict[str, list[float]] = {}
    for v in videos:
        if v.get("split") in policy.holdout_splits:
            continue
        x = _number(v.get(policy.performance_field))
        if x is None:
            continue
        values.setdefault(length_group(v, policy), []).append(x)
    out = {}
    for g, xs in sorted(values.items()):
        xs.sort()
        n = len(xs)
        # 하위 i/n_tiers 지점의 값 (최근접 순위). 보간하지 않는다
        out[g] = [xs[min(n - 1, max(0, math.ceil(n * i / policy.n_tiers) - 1))]
                  for i in range(1, policy.n_tiers)]
    return out


def tier_of(video: dict, policy: SamplingPolicy,
            cutpoints: dict[str, list[float]]) -> str:
    if video.get("split") in policy.holdout_splits:
        return BLIND_TIER
    x = _number(video.get(policy.performance_field))
    cuts = cutpoints.get(length_group(video, policy))
    if x is None or cuts is None:
        return UNKNOWN_TIER
    for i, c in enumerate(cuts):
        if x <= c:
            return f"t{i + 1}"
    return f"t{len(cuts) + 1}"


def apportion(sizes: dict, total: int, minimum: int = 0) -> dict:
    """정수 배분. 각 칸에 min(minimum, 크기)를 먼저 주고 나머지를 크기 비례로.

    나머지는 한 편씩 D'Hondt 방식으로 준다 — 크기/(받은 수+1)이 가장 큰 칸.
    동률은 키 순서. 이 방식은 total 을 늘렸을 때 어느 칸도 줄지 않는다.
    최소치 합이 total 을 넘으면 최소치를 지킨다(total 을 넘는다).
    """
    alloc = {k: min(minimum, n) for k, n in sizes.items()}
    left = total - sum(alloc.values())
    keys = sorted(sizes, key=str)
    while left > 0:
        cands = [k for k in keys if alloc[k] < sizes[k]]
        if not cands:
            break
        best = min(cands, key=lambda k: (-Fraction(sizes[k], alloc[k] + 1), str(k)))
        alloc[best] += 1
        left -= 1
    return alloc


def plan(videos: list[dict], policy: SamplingPolicy) -> SamplingPlan:
    """영상 목록 → 영상마다 결정 한 줄.

    입력 영상은 전부 결정 줄을 받는다(선정·미선정·제외). 빠진 영상이 없어야
    "받지 않았다"와 "모른다"가 구분된다.
    """
    policy.validate()
    ids = [v["video_id"] for v in videos]
    if len(set(ids)) != len(ids):
        raise ValueError("video_id 중복")

    cuts = tier_cutpoints(videos, policy)
    warnings: list[str] = []
    rows: dict[str, dict] = {}
    pools: dict[str, list[dict]] = {}          # split → 자격 있는 영상

    for v in videos:
        split = v.get("split")
        rule = policy.rule_for(split)
        tier = tier_of(v, policy, cuts)
        if rule.mode == BLIND:
            tier = BLIND_TIER                   # blind 규칙은 성과를 쓰지 않는다
        cell = (v.get("type_code") or UNTYPED, length_group(v, policy))
        row = {
            "video_id": v["video_id"], "split": split,
            "cell": "|".join(cell), "tier": tier,
            "stratum": "|".join((*cell, tier)),
            "comment_count": v.get("comment_count"),
            "mode": rule.mode, "decision": NOT_SAMPLED, "reason": None,
            "inclusion_prob": 0.0, "rank_key": rank_key(policy.seed, split, v["video_id"]),
            "order": policy.order, "collect_cap": 0, "top_pages": 0,
            "reply_threads": 0, "reply_pages": 0, "label_cap": 0,
        }
        rows[v["video_id"]] = row
        why = exclusion_reason(v, policy)
        if why:
            row["decision"], row["reason"] = EXCLUDED, why
            continue
        if rule.mode == SKIP:
            row["reason"] = "split_rule:skip"
            continue
        # 규칙에 없는 split 은 "*" 규칙으로 왔다 (없었으면 위에서 skip)
        pools.setdefault(split if split in policy.split_rules else ANY_SPLIT, []).append(v)

    for key in sorted(pools, key=str):
        _select_pool(pools[key], policy.split_rules[key], policy, rows, warnings, str(key))

    for row in rows.values():
        if row["decision"] == SELECTED:
            row.update(collect_cap=policy.collect_cap, top_pages=policy.top_pages,
                       reply_threads=policy.reply_threads,
                       reply_pages=policy.reply_pages,
                       label_cap=min(policy.label_cap, policy.collect_cap))
    return SamplingPlan(policy, cuts, [rows[i] for i in ids], warnings)


def _select_pool(pool: list[dict], rule: SplitRule, policy: SamplingPolicy,
                 rows: dict[str, dict], warnings: list[str], name: str) -> None:
    if rule.mode == CENSUS or len(pool) <= (rule.target or 0):
        for v in pool:
            rows[v["video_id"]].update(decision=SELECTED, reason=rule.mode
                                       if rule.mode == CENSUS else "target>=eligible",
                                       inclusion_prob=1.0)
        return

    by_cell: dict[str, list[dict]] = {}
    for v in pool:
        by_cell.setdefault(rows[v["video_id"]]["cell"], []).append(v)
    cell_alloc = apportion({c: len(vs) for c, vs in by_cell.items()},
                           rule.target, policy.min_per_cell)
    if sum(cell_alloc.values()) > rule.target:
        warnings.append(f"{name}: 칸별 최소치 합 {sum(cell_alloc.values())} 이 "
                        f"target {rule.target} 을 넘어 최소치를 따랐다")
    for cell, k in sorted(cell_alloc.items()):
        vs = by_cell[cell]
        if len(vs) < policy.min_per_cell:
            warnings.append(f"{name}: 칸 {cell} 은 {len(vs)}편뿐 (최소 {policy.min_per_cell})")
        by_stratum: dict[str, list[dict]] = {}
        for v in vs:
            by_stratum.setdefault(rows[v["video_id"]]["stratum"], []).append(v)
        # 칸 안에서는 성과 층마다 한 편씩 먼저 — 편수가 허락하는 만큼
        tier_min = 1 if k >= len(by_stratum) else 0
        s_alloc = apportion({s: len(x) for s, x in by_stratum.items()}, k, tier_min)
        for stratum, m in s_alloc.items():
            members = sorted(by_stratum[stratum],
                             key=lambda v: (rows[v["video_id"]]["rank_key"], v["video_id"]))
            prob = m / len(members)
            for i, v in enumerate(members):
                row = rows[v["video_id"]]
                row["inclusion_prob"] = prob
                if i < m:
                    row["decision"], row["reason"] = SELECTED, rule.mode
                else:
                    row["reason"] = "stratum_quota"


def label_subset(comment_ids: list[str], cap: int, seed: int, video_id: str) -> list[str]:
    """수집한 원댓글에서 판정에 보낼 것을 해시 순서로 고른다.

    수집이 complete 이면 수집 시점 원댓글 전체에서의 균등 추출이다. capped 이면
    수집된 부분(order 가 정한 앞쪽)에서의 균등 추출일 뿐이다 — 설계 문서 3장.
    """
    key = lambda cid: (hashlib.sha256(f"{seed}\0{video_id}\0{cid}".encode()).hexdigest(), cid)
    return sorted(sorted(set(comment_ids), key=key)[:cap])


# --------------------------------------------------------------------------
# 예산 추정 — 추정치다. 가정은 인자로 드러낸다
# --------------------------------------------------------------------------

def estimate(plan_: SamplingPlan, *, metadata_videos: int | None = None,
             in_tokens_per_comment: float = 165, out_tokens_per_comment: float = 80,
             price_per_mtok: tuple[float, float] | None = None,
             batch_discount: float = 0.5) -> dict:
    """YouTube 유닛 상한과 판정 토큰·비용 추정.

    - 원댓글 페이지: ceil(min(comment_count, collect_cap)/100), 최소 1.
      comment_count 가 답글을 포함하므로 **상한**이다. 모르면 cap 기준.
    - 답글 호출: reply_threads × reply_pages. 답글 없는 thread 는 호출하지
      않으므로 역시 상한이다.
    - 메타 갱신: videos.list 50편당 1유닛 (metadata_videos 가 주어졌을 때).
    - 판정 건수: min(comment_count, label_cap). 토큰·단가는 가정이다.
    """
    chosen = plan_.selected()
    top = replies = labeled = 0
    for d in chosen:
        cc = d["comment_count"]
        reach = d["collect_cap"] if cc is None else min(cc, d["collect_cap"])
        top += max(1, math.ceil(reach / PAGE_SIZE))
        replies += d["reply_threads"] * d["reply_pages"]
        labeled += d["label_cap"] if cc is None else min(cc, d["label_cap"])
    meta = math.ceil(metadata_videos / 50) if metadata_videos else 0
    units = top + replies + meta
    tin = labeled * in_tokens_per_comment
    tout = labeled * out_tokens_per_comment
    out = {
        "videos": len(chosen), "units_top_pages": top, "units_replies_max": replies,
        "units_metadata": meta, "units_total_max": units,
        "quota_days_at_9500": math.ceil(units / 9500) if units else 0,
        "labeled_comments": labeled, "input_tokens": tin, "output_tokens": tout,
    }
    if price_per_mtok:
        cost = tin / 1e6 * price_per_mtok[0] + tout / 1e6 * price_per_mtok[1]
        out["cost_usd_sync"] = round(cost, 2)
        out["cost_usd_batch"] = round(cost * batch_discount, 2)
    return out

