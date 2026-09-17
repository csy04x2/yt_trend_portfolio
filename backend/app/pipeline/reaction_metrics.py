"""Reaction 결과 연결 — Stage 08 사실 (집계만, 문장 없음).

설계: `docs/design/reaction-report.md`. 기준: `docs/reaction-track-closeout-2026-09-17.md`
(Final vNext R1–R10, Target T1–T5 + UNKNOWN, 「2026-09-17 재개 결정」).

`comment_reactions` (label_reactions.py 가 채운 AI 판정) 를 **분석 대상 댓글만으로**
접어 네 범위의 수치를 만든다.

    video     영상 하나
    channel   채널 전체 (길이 묶음별) — Stage 09 가 「나머지」를 계산하는 기준
    type      영상 유형 × 길이 묶음 (classify_videos 의 활성 체계, topic·segment 축)
    tier      성과 층 × 길이 묶음 (view_multiple 분위)

## 이 모듈이 하지 않는 것

- **문장을 만들지 않는다.** 「어느 유형이 더 높다」 는 해석이고 Stage 09
  (`app/interpret/reaction.py`) 의 일이다. `aggregate.py` 의 결론 초안이 Stage 08
  경계 밖에 있다는 것은 이미 알려진 문제라, 여기서는 그 길을 따르지 않는다.
- **MVP Finding 에 넣지 않는다.** `feature_outcome` 은 이 모듈을 import 하지 않는다.
  독립 fresh 표본 검증 전까지 모든 행은 `validation_status = '검증 전 AI 판정'` 이다.
- **표본 가중을 하지 않는다.** observation_sampling 이 있으면 완결성·포함 확률을
  출처로 남길 뿐, 가중 추정치는 내지 않는다 (사람이 정할 것, 설계 문서 6장).

## 비율의 정의 (다중 라벨)

    n_comments       이 묶음에서 판정된 분석 대상 댓글 수 (None·UNKNOWN 포함)
    reaction_share   그 Reaction 을 **가진** 댓글 ÷ n_comments
                     한 댓글이 R1·R7 을 함께 가지면 둘 다에 1 씩 센다 → 합이 1 을 넘을 수 있다
    none_share       Reaction=None ([]) 댓글 ÷ n_comments
    unknown_share    Reaction=["UNKNOWN"] (판정 불가) 댓글 ÷ n_comments
    target_share     T1–T5·UNKNOWN 각각을 가진 댓글 ÷ n_comments
                     (Reaction=None 이라 Target 이 빈 댓글은 no_target_count 로 따로 센다)

None 과 UNKNOWN 은 다르다 — 앞은 「반응 없음」, 뒤는 「판정할 수 없음」이다
(Phase 1 checkpoint Reaction 공통 규칙). 둘을 합치거나 분모에서 빼지 않는다.

## 작은 표본

n_comments 가 `min_comments` (기본 10, `aggregate.AggregateConfig.min_labels` 와 같은
값) 미만이면 비율을 전부 null 로 두고 `basis` 에 이유를 남긴다. 수는 남긴다 —
`video_comment_metrics` 가 비율만 비우고 긍·부·중 수는 남기는 것과 같은 규칙이다.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from dataclasses import dataclass

from app.pipeline.classify_videos import ALL, LONGFORM, SHORTS, view_group
from app.pipeline.label_reactions import REACTIONS, TARGETS, UNKNOWN

METRICS_VERSION = "reaction-metrics-v0.1"
VALIDATION_STATUS = "검증 전 AI 판정"

SCOPE_VIDEO, SCOPE_CHANNEL, SCOPE_TYPE, SCOPE_TIER = "video", "channel", "type", "tier"
SCOPES = (SCOPE_VIDEO, SCOPE_CHANNEL, SCOPE_TYPE, SCOPE_TIER)
CHANNEL_KEY = "channel"
UNKNOWN_TIER = "unknown"
TARGET_KEYS = TARGETS + (UNKNOWN,)
LENGTH_AXES = (SHORTS, LONGFORM, ALL)
OWN_CHANNEL = "own_channel"


@dataclass(frozen=True)
class ReactionMetricsConfig:
    # 이보다 판정이 적으면 비율을 내지 않는다. aggregate.min_labels 와 같은 값이다 —
    # 세 건으로 낸 비율이 소수점으로 찍히면 정밀한 측정처럼 보인다.
    min_comments: int = 10
    # 성과 층 수. comment_sampling.SamplingPolicy.n_tiers 와 같은 기본값·같은 경계 규칙
    n_tiers: int = 3


DEFAULT = ReactionMetricsConfig()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 분석 대상 (H3)
# --------------------------------------------------------------------------

def is_audience(row: dict) -> bool:
    """시청자 반응 집계에 넣는 댓글인가.

    `analysis_eligible = 1` 만 넣는다 (docs/design/comment-eligibility.md). 채널 본인
    댓글은 eligibility 가 이미 0 으로 두지만, 옛 DB·수기 입력에서 표시가 어긋나도
    새지 않게 `own_channel` 사유와 `author_is_channel_owner = 1` 도 한 번 더 뺀다.
    """
    if row.get("analysis_eligible") not in (1, True, "1"):
        return False
    if row.get("exclusion_reason") == OWN_CHANNEL:
        return False
    return row.get("author_is_channel_owner") not in (1, True, "1")


def _codes(value, allowed: tuple, axis: str, cid) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{cid}: {axis} 가 배열이 아니다")
    bad = [c for c in value if c not in allowed + (UNKNOWN,)]
    if bad:
        # 저장 시 label_reactions.check_label 을 통과한 값만 들어온다. 여기 걸리면
        # 표가 손으로 고쳐졌다는 뜻이라 조용히 세지 않는다.
        raise ValueError(f"{cid}: {axis} 에 없는 코드 {bad}")
    return list(dict.fromkeys(value))


# --------------------------------------------------------------------------
# 접기 — 순수 함수
# --------------------------------------------------------------------------

def rollup(labels: list[dict], *, n_eligible: int | None, n_videos: int,
           cfg: ReactionMetricsConfig = DEFAULT) -> dict:
    """판정 묶음 하나를 접는다. DB 를 모른다.

    labels 각 항목: {comment_id, reactions: [...], targets: [...], review_flag}
    (이미 분석 대상만 걸러 들어온다.)
    """
    n = len(labels)
    rc: Counter = Counter()
    tc: Counter = Counter()
    none = unknown = no_target = multi = flagged = 0
    for x in labels:
        cid = x.get("comment_id")
        reactions = _codes(x.get("reactions"), REACTIONS, "reactions", cid)
        targets = _codes(x.get("targets"), TARGETS, "targets", cid)
        if not reactions:
            none += 1
        elif reactions == [UNKNOWN]:
            unknown += 1
        else:
            for r in reactions:
                if r != UNKNOWN:
                    rc[r] += 1
            if len(reactions) >= 2:
                multi += 1
        if not targets:
            no_target += 1
        for t in targets:
            tc[t] += 1
        if x.get("review_flag"):
            flagged += 1

    masked = n < cfg.min_comments

    def share(k):
        return None if masked else k / n

    out = {
        "n_videos": n_videos,
        "n_eligible_comments": n_eligible if n_eligible is not None else 0,
        "n_comments": n,
        "labeled_ratio": (n / n_eligible) if n_eligible else None,
        "reaction_counts": {r: rc.get(r, 0) for r in REACTIONS},
        "reaction_shares": {r: share(rc.get(r, 0)) for r in REACTIONS},
        "none_count": none,
        "none_share": share(none),
        "unknown_count": unknown,
        "unknown_share": share(unknown),
        "target_counts": {t: tc.get(t, 0) for t in TARGET_KEYS},
        "target_shares": {t: share(tc.get(t, 0)) for t in TARGET_KEYS},
        "no_target_count": no_target,
        "multi_reaction_count": multi,
        "review_flag_count": flagged,
        "masked": masked,
        "validation_status": VALIDATION_STATUS,
        "metrics_version": METRICS_VERSION,
    }
    if n == 0:
        out["basis"] = "판정된 분석 대상 댓글이 없다"
    elif masked:
        out["basis"] = (f"판정 {n}건 (최소 {cfg.min_comments}건 필요) — "
                        f"비율은 내지 않고 수만 남긴다 · {VALIDATION_STATUS}")
    else:
        elig = f"{n}/{n_eligible}" if n_eligible else f"{n}"
        out["basis"] = (f"영상 {n_videos}편 · 판정 {elig}건 · 다중 Reaction {multi}건 · "
                        f"{VALIDATION_STATUS}")
    return out


def tier_cutpoints(values: dict[str, float | None], group_of: dict[str, str],
                   n_tiers: int = DEFAULT.n_tiers) -> dict[str, list[float]]:
    """길이 묶음마다 성과 분위 경계. comment_sampling.tier_cutpoints 와 같은 규칙
    (보간 없는 최근접 순위). 값이 없는 영상은 경계 계산에 들어가지 않는다."""
    import math

    by: dict[str, list[float]] = defaultdict(list)
    for vid, x in values.items():
        if x is None or isinstance(x, bool):
            continue
        by[group_of.get(vid, LONGFORM)].append(float(x))
    out = {}
    for g, xs in sorted(by.items()):
        xs.sort()
        n = len(xs)
        out[g] = [xs[min(n - 1, max(0, math.ceil(n * i / n_tiers) - 1))]
                  for i in range(1, n_tiers)]
    return out


def tier_of(x, cuts: list[float] | None) -> str:
    if x is None or cuts is None:
        return UNKNOWN_TIER
    for i, c in enumerate(cuts):
        if x <= c:
            return f"t{i + 1}"
    return f"t{len(cuts) + 1}"


def sampling_summary(video_ids, sampling: dict | None) -> dict:
    """묶음에 든 영상의 표본 설계 출처. 가중치를 **적용하지 않는다**는 것까지 적는다."""
    if not sampling:
        return {"source": None, "weighted": False,
                "note": "observation_sampling 없음 — 표본 설계 정보가 없어 가중하지 않았다"}
    rows = sampling.get("rows") or {}
    have = [rows[v] for v in video_ids if v in rows]
    probs = [r.get("inclusion_prob") for r in have if r.get("inclusion_prob") is not None]
    return {
        "source": "observation_sampling",
        "run_id": sampling.get("run_id"),
        "weighted": False,
        "videos_with_row": len(have),
        "videos_without_row": len(video_ids) - len(have),
        "completeness": dict(sorted(Counter(r.get("completeness") or "?" for r in have).items())),
        "decision": dict(sorted(Counter(r.get("decision") or "?" for r in have).items())),
        "inclusion_prob_min": min(probs) if probs else None,
        "inclusion_prob_max": max(probs) if probs else None,
        "policy_versions": sorted({r.get("policy_version") for r in have if r.get("policy_version")}),
        "orderings": sorted({r.get("ordering") for r in have if r.get("ordering")}),
        "label_caps": sorted({r.get("label_cap") for r in have if r.get("label_cap") is not None}),
    }


def compute(labels: list[dict], videos: dict[str, dict], *,
            prompt_version: str, model: str,
            eligible_counts: dict[str, int] | None = None,
            type_maps: list[dict] | None = None,
            performance: dict | None = None,
            sampling: dict | None = None,
            cfg: ReactionMetricsConfig = DEFAULT) -> list[dict]:
    """네 범위의 Reaction 수치 행을 만든다. 순수 함수.

    labels         [{comment_id, video_id, reactions, targets, review_flag,
                     analysis_eligible, exclusion_reason, author_is_channel_owner}]
                   한 (prompt_version, model) 의 판정만 넣는다.
    videos         {video_id: {"length_axis": shorts|standard|long|None}} — 채널 영상
    eligible_counts {video_id: 분석 대상 댓글 수} (판정 여부 무관)
    type_maps      [{"taxonomy_id": int, "axis": "topic"|"segment", "labels": {video_id: code}}]
    performance    {"values": {video_id: view_multiple|None}, "meta": {...}} — 없으면 tier 생략
    sampling       {"run_id": str, "rows": {video_id: observation_sampling 행}} 또는 None
    """
    eligible_counts = eligible_counts or {}
    by_video: dict[str, list[dict]] = defaultdict(list)
    for x in labels:
        vid = x.get("video_id")
        if vid in videos and is_audience(x):
            by_video[vid].append(x)
    if not by_video:
        return []

    group_of = {vid: view_group(v.get("length_axis") or "standard") for vid, v in videos.items()}
    groups: dict[tuple, set] = defaultdict(set)   # (scope, taxonomy_id, key, axis) → video ids
    extra: dict[tuple, dict] = {}

    for vid in by_video:
        g = group_of[vid]
        groups[(SCOPE_VIDEO, 0, vid, g)].add(vid)
        for axis in (g, ALL):
            groups[(SCOPE_CHANNEL, 0, CHANNEL_KEY, axis)].add(vid)

    for tm in type_maps or []:
        tid = tm["taxonomy_id"]
        for vid in by_video:
            code = (tm.get("labels") or {}).get(vid)
            if not code:
                continue            # 유형 없는 영상은 유형 묶음에 넣지 않는다 (aggregate 와 같다)
            for axis in (group_of[vid], ALL):
                key = (SCOPE_TYPE, tid, code, axis)
                groups[key].add(vid)
                extra[key] = {"taxonomy_axis": tm.get("axis")}

    if performance is not None:
        values = performance.get("values") or {}
        cuts = tier_cutpoints(values, group_of, cfg.n_tiers)
        meta = dict(performance.get("meta") or {})
        meta.update(n_tiers=cfg.n_tiers, cutpoints=cuts,
                    tier_rule="길이 묶음별 최근접 순위 분위 (comment_sampling.tier_cutpoints 와 같은 규칙)")
        for vid in by_video:
            tier = tier_of(values.get(vid), cuts.get(group_of[vid]))
            for axis in (group_of[vid], ALL):
                key = (SCOPE_TIER, 0, tier, axis)
                groups[key].add(vid)
                extra[key] = {"performance": meta}

    out = []
    for key in sorted(groups, key=lambda k: (SCOPES.index(k[0]), k[1], k[2], LENGTH_AXES.index(k[3]))):
        scope, tid, gkey, axis = key
        vids = sorted(groups[key])
        rows = [x for v in vids for x in by_video[v]]
        rec = rollup(rows, n_eligible=sum(eligible_counts.get(v, 0) for v in vids),
                     n_videos=len(vids), cfg=cfg)
        rec.update(scope=scope, taxonomy_id=tid, group_key=gkey, length_axis=axis,
                   prompt_version=prompt_version, model=model,
                   performance=(extra.get(key) or {}).get("performance") or {},
                   taxonomy_axis=(extra.get(key) or {}).get("taxonomy_axis"),
                   sampling=sampling_summary(vids, sampling))
        out.append(rec)
    return out


# --------------------------------------------------------------------------
# DB 읽기 — 읽기 전용 연결에서도 돈다 (표·열이 없으면 없는 대로)
# --------------------------------------------------------------------------

def _has_table(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _cols(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def label_versions(conn) -> list[tuple[str, str]]:
    """comment_reactions 에 실제로 있는 (prompt_version, model). 최근 판정 순."""
    if not _has_table(conn, "comment_reactions"):
        return []
    return [(r[0], r[1]) for r in conn.execute(
        """SELECT prompt_version, model FROM comment_reactions
           GROUP BY prompt_version, model ORDER BY MAX(labeled_at) DESC""")]


def _eligibility_select(conn) -> str:
    cols = _cols(conn, "comments")
    ae = "c.analysis_eligible" if "analysis_eligible" in cols else "1"
    er = "c.exclusion_reason" if "exclusion_reason" in cols else "NULL"
    ow = "c.author_is_channel_owner" if "author_is_channel_owner" in cols else "NULL"
    return f"{ae} AS analysis_eligible, {er} AS exclusion_reason, {ow} AS author_is_channel_owner"


def read_labels(conn, channel_id: str, prompt_version: str, model: str) -> list[dict]:
    """한 (버전, 모델) 의 판정과 댓글 쪽 분석 대상 표시. 원문(text)·근거(rationale)는 읽지 않는다."""
    if not _has_table(conn, "comment_reactions"):
        return []
    sql = f"""SELECT r.comment_id, c.video_id, r.reactions_json, r.targets_json, r.review_flag,
                     {_eligibility_select(conn)}
              FROM comment_reactions r
              JOIN comments c ON c.comment_id = r.comment_id
              JOIN videos v ON v.video_id = c.video_id
              WHERE r.prompt_version = ? AND r.model = ? AND v.channel_id = ?"""
    return [{
        "comment_id": r[0], "video_id": r[1],
        "reactions": json.loads(r[2]), "targets": json.loads(r[3]),
        "review_flag": bool(r[4]), "analysis_eligible": r[5],
        "exclusion_reason": r[6], "author_is_channel_owner": r[7],
    } for r in conn.execute(sql, (prompt_version, model, channel_id))]


def read_eligible_counts(conn, channel_id: str) -> dict[str, int]:
    out: dict[str, int] = {}
    sql = f"""SELECT c.video_id, {_eligibility_select(conn)}
              FROM comments c JOIN videos v ON v.video_id = c.video_id
              WHERE v.channel_id = ?"""
    for r in conn.execute(sql, (channel_id,)):
        row = {"analysis_eligible": r[1], "exclusion_reason": r[2], "author_is_channel_owner": r[3]}
        if is_audience(row):
            out[r[0]] = out.get(r[0], 0) + 1
    return out


def read_videos(conn, channel_id: str) -> dict[str, dict]:
    return {r[0]: {"length_axis": r[1]} for r in conn.execute(
        "SELECT video_id, length_axis FROM videos WHERE channel_id = ?", (channel_id,))}


def read_type_maps(conn, channel_id: str) -> list[dict]:
    """활성 체계(topic·segment)마다 {video_id: type_code}. 같은 영상의 라벨이 여럿이면 최근 것."""
    if not (_has_table(conn, "video_taxonomies") and _has_table(conn, "video_type_labels")):
        return []
    out = []
    for tax in conn.execute(
            """SELECT taxonomy_id, axis, types_json FROM video_taxonomies
               WHERE channel_id = ? AND is_active = 1 ORDER BY axis""", (channel_id,)).fetchall():
        labels = {}
        for r in conn.execute(
                """SELECT video_id, type_code FROM video_type_labels
                   WHERE taxonomy_id = ? ORDER BY labeled_at, model, prompt_version""", (tax[0],)):
            labels[r[0]] = r[1]
        out.append({"taxonomy_id": tax[0], "axis": tax[1],
                    "names": json.loads(tax[2] or "{}"), "labels": labels})
    return out


def read_performance(conn, channel_id: str, manifest: dict | None = None) -> dict | None:
    """영상별 조회 배수와 그 정의.

    manifest 가 없으면 `video_metrics` 최신 실행의 `view_multiple` (normalize 정의) —
    **provisional/legacy** 값이다 (docs/design/reference-population.md 3.1).
    동결 manifest 를 주면 `reference.canonical_view_multiple` 로 canonical 값을 쓴다.
    """
    if manifest is not None:
        from app.pipeline import reference

        reference.verify_manifest(manifest)
        snaps = {}
        if _has_table(conn, "video_stats_snapshots"):
            for r in conn.execute(
                    """SELECT s.video_id, s.view_count, s.captured_at FROM video_stats_snapshots s
                       JOIN videos v ON v.video_id = s.video_id WHERE v.channel_id = ?
                       ORDER BY s.captured_at, s.snapshot_id""", (channel_id,)):
                snaps[r[0]] = (r[1], r[2])
        values, statuses = {}, Counter()
        for r in conn.execute(
                """SELECT video_id, published_at, duration_sec, is_live, live_evidence
                   FROM videos WHERE channel_id = ?""", (channel_id,)):
            views, captured = snaps.get(r[0], (None, None))
            got = reference.canonical_view_multiple(
                {"video_id": r[0], "published_at": r[1], "duration_sec": r[2], "is_live": r[3],
                 "live_evidence": r[4], "view_count": views, "captured_at": captured},
                manifest, verify=False)
            values[r[0]] = got["view_multiple"]
            statuses[got["status"]] += 1
        rules = manifest["rules"]
        return {"values": values, "meta": {
            "field": "view_multiple", "definition": reference.CANONICAL_DEFINITION,
            "canonical": True, "canonical_status": "canonical",
            "reference_manifest_sha256": manifest["manifest_sha256"],
            "reference_rules_version": rules.get("rules_version"),
            "reference_rules_status": rules.get("rules_status"),
            "final_eligible": rules.get("rules_status") == "approved",
            "status_counts": dict(sorted(statuses.items())),
        }}

    if not _has_table(conn, "video_metrics"):
        return None
    run = conn.execute(
        """SELECT m.run_id FROM video_metrics m JOIN videos v ON v.video_id = m.video_id
           WHERE v.channel_id = ? ORDER BY m.computed_at DESC LIMIT 1""", (channel_id,)).fetchone()
    if not run:
        return None
    values, basis_missing = {}, 0
    for r in conn.execute(
            """SELECT m.video_id, m.view_multiple FROM video_metrics m
               JOIN videos v ON v.video_id = m.video_id
               WHERE v.channel_id = ? AND m.run_id = ?""", (channel_id, run[0])):
        values[r[0]] = r[1]
        basis_missing += r[1] is None
    return {"values": values, "meta": {
        "field": "view_multiple", "definition": "normalize.view_multiple",
        "canonical": False, "canonical_status": "provisional_legacy",
        "source": "video_metrics", "source_run_id": run[0],
        "missing_n": basis_missing,
        "note": "split 안 peer 로 계산한 임시값. 동결 reference manifest 를 주면 canonical 로 바뀐다",
    }}


def read_sampling(conn, run_id: str | None = None) -> dict | None:
    """observation_sampling 한 실행. run_id 가 없으면 가장 최근 결정 실행."""
    if not _has_table(conn, "observation_sampling"):
        return None
    if run_id is None:
        r = conn.execute("SELECT run_id FROM observation_sampling "
                         "ORDER BY decided_at DESC LIMIT 1").fetchone()
        if not r:
            return None
        run_id = r[0]
    cols = [c for c in ("video_id", "decision", "inclusion_prob", "completeness",
                        "policy_version", "ordering", "label_cap")]
    rows = {r[0]: dict(zip(cols, r)) for r in conn.execute(
        f"SELECT {', '.join(cols)} FROM observation_sampling WHERE run_id = ?", (run_id,))}
    return {"run_id": run_id, "rows": rows} if rows else None


def collect(conn, channel_id: str, *, prompt_version: str | None = None,
            model: str | None = None, manifest: dict | None = None,
            sampling_run_id: str | None = None,
            cfg: ReactionMetricsConfig = DEFAULT) -> list[dict]:
    """DB 를 읽어 수치 행을 만든다. **쓰지 않는다** (읽기 전용 연결에서 쓸 수 있다).

    버전을 주지 않으면 DB 에 있는 (버전, 모델) 조합마다 따로 만든다. 섞지 않는다.
    """
    versions = [(prompt_version, model)] if (prompt_version and model) else label_versions(conn)
    if not versions:
        return []
    videos = read_videos(conn, channel_id)
    eligible = read_eligible_counts(conn, channel_id)
    type_maps = read_type_maps(conn, channel_id)
    perf = read_performance(conn, channel_id, manifest)
    sampling = read_sampling(conn, sampling_run_id)
    out = []
    for pv, mdl in versions:
        out += compute(read_labels(conn, channel_id, pv, mdl), videos,
                       prompt_version=pv, model=mdl, eligible_counts=eligible,
                       type_maps=type_maps, performance=perf, sampling=sampling, cfg=cfg)
    return out


def save(conn, channel_id: str, run_id: str, records: list[dict]) -> int:
    now = _now()
    for r in records:
        conn.execute(
            """INSERT INTO reaction_metrics
                   (channel_id, run_id, prompt_version, model, scope, taxonomy_id, group_key,
                    length_axis, n_videos, n_eligible_comments, n_comments, labeled_ratio,
                    reaction_counts_json, reaction_shares_json, none_count, none_share,
                    unknown_count, unknown_share, target_counts_json, target_shares_json,
                    no_target_count, multi_reaction_count, review_flag_count, masked, basis,
                    performance_json, sampling_json, metrics_version, validation_status,
                    computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(channel_id, run_id, prompt_version, model, scope, taxonomy_id,
                           group_key, length_axis) DO UPDATE SET
                   n_videos=excluded.n_videos, n_eligible_comments=excluded.n_eligible_comments,
                   n_comments=excluded.n_comments, labeled_ratio=excluded.labeled_ratio,
                   reaction_counts_json=excluded.reaction_counts_json,
                   reaction_shares_json=excluded.reaction_shares_json,
                   none_count=excluded.none_count, none_share=excluded.none_share,
                   unknown_count=excluded.unknown_count, unknown_share=excluded.unknown_share,
                   target_counts_json=excluded.target_counts_json,
                   target_shares_json=excluded.target_shares_json,
                   no_target_count=excluded.no_target_count,
                   multi_reaction_count=excluded.multi_reaction_count,
                   review_flag_count=excluded.review_flag_count, masked=excluded.masked,
                   basis=excluded.basis, performance_json=excluded.performance_json,
                   sampling_json=excluded.sampling_json,
                   metrics_version=excluded.metrics_version,
                   validation_status=excluded.validation_status,
                   computed_at=excluded.computed_at""",
            (channel_id, run_id, r["prompt_version"], r["model"], r["scope"], r["taxonomy_id"],
             r["group_key"], r["length_axis"], r["n_videos"], r["n_eligible_comments"],
             r["n_comments"], r["labeled_ratio"],
             json.dumps(r["reaction_counts"]), json.dumps(r["reaction_shares"]),
             r["none_count"], r["none_share"], r["unknown_count"], r["unknown_share"],
             json.dumps(r["target_counts"]), json.dumps(r["target_shares"]),
             r["no_target_count"], r["multi_reaction_count"], r["review_flag_count"],
             int(r["masked"]), r["basis"],
             json.dumps(r["performance"], ensure_ascii=False),
             json.dumps(r["sampling"], ensure_ascii=False),
             r["metrics_version"], VALIDATION_STATUS, now))
    return len(records)


def run(conn, channel_id: str, run_id: str, **kw) -> list[dict]:
    """collect → reaction_metrics 에 저장."""
    records = collect(conn, channel_id, **kw)
    save(conn, channel_id, run_id, records)
    return records
