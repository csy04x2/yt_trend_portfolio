"""6단계 집계 — 영상별·유형별로 접고, 결론 문장 초안을 만든다.

여기까지 오면 도구가 **혼자서** 리포트를 내놓는다. 그전까지는 사람이 SQL 을
두드려 표를 읽고 문장을 손으로 썼다. 그건 도구가 분석한 게 아니라 사람이
분석한 것이다.

## 무엇을 접는가

    video_comment_metrics   영상별 유효 댓글 수, 긍·부·중 비율, 주제별 언급 수,
                            대표 댓글(긍정·부정 각 상위 3)
    type_comment_metrics    유형 × 길이 축별로 같은 것을 합친 것
    reports                 결론 문장, 전후 비교, 어느 축으로 읽어야 하는지

성과 쪽(`type_metrics`)은 3단계가 이미 만들어 뒀다. 여기서는 **댓글 쪽**을
만들어 그 옆에 놓는다.

## positive_ratio 와 approval 은 다른 값이다

헷갈리기 쉬워 적어 둔다.

    positive_ratio  긍정 ÷ **라벨 전체**        (neutral 이 분모에 있다)
    approval        긍정 ÷ (긍정 + 부정)        (neutral 을 분모에서 뺀다, engagement.py)

같은 영상에서 앞은 0.26, 뒤는 0.59 가 나온다 — 토론 영상이 그랬다. 둘 다
맞는 값이고 묻는 질문이 다르다. 앞은 "댓글 중 칭찬이 얼마나 되나", 뒤는
"의견을 낸 사람 중 몇이 편을 들었나"이다. 리포트에 둘을 나란히 쓸 때는
반드시 이름을 붙여 구분한다.

## 결론 문장은 규칙이 쓰고 Claude 는 다듬기만 한다

수치와 인과를 모델이 만들면, 리포트를 읽는 사람이 나머지 수치까지 의심하게
된다. 그래서 초안을 규칙으로 채우고 Claude 에는 문장만 맡긴 뒤,
**돌아온 문장의 숫자가 초안과 다르면 초안을 쓴다**(`same_numbers`).
어느 쪽이 쓰였는지는 `reports.conclusion_source` 에 남는다.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import statistics as st
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.pipeline.classify_videos import ALL, LONGFORM, SHORTS, view_group

POSITIVE, NEGATIVE, NEUTRAL = "positive", "negative", "neutral"

LENGTH_LABEL = {SHORTS: "쇼츠", LONGFORM: "롱폼", ALL: "전체"}
AXIS_LABEL = {"topic": "주제", "segment": "코너"}


@dataclass
class AggregateConfig:
    # 이보다 라벨이 적으면 영상의 비율을 내지 않는다. engagement.min_polar 와
    # 같은 사고방식이다 — 세 건으로 낸 비율이 소수점 두 자리로 찍히면
    # 정밀한 측정처럼 보인다.
    min_labels: int = 10
    # 결론 문장의 주인공이 되려면 이만큼은 있어야 한다. 4편의 중앙값을
    # "이 채널이 가장 잘하는 것"이라고 말하면 안 된다.
    min_videos_headline: int = 5
    # 대표 댓글 개수 (긍정·부정 각각)
    top_n: int = 3
    # 전후 비교의 한쪽 크기
    window: int = 30
    # 인사이트에서 뺄 주제. **기본값은 비운다** — 무엇을 뺄지는 결정 문서
    # 3장의 미결 사항이라 여기서 확정하지 않는다. T8(감정·응원)을 빼자는
    # 이야기가 있었으나 정해지지 않았다.
    ignore_topics: tuple[str, ...] = ()
    # 코너 축이 주도권을 가지려면 그 길이 축에서 이만큼은 덮어야 한다
    axis_coverage: float = 0.5


DEFAULT = AggregateConfig()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


# --------------------------------------------------------------------------
# 조사 — 결론 문장은 사람이 읽는 물건이다
# --------------------------------------------------------------------------

def _has_final(word: str) -> tuple[bool, bool]:
    """마지막 글자의 (받침 있음, 그 받침이 ㄹ). 한글이 아니면 (False, False)."""
    for ch in reversed(word.strip()):
        if "가" <= ch <= "힣":
            code = (ord(ch) - 0xAC00) % 28
            return code != 0, code == 8
        if ch.isalnum():
            # 숫자·영문으로 끝나면 받침을 단정할 수 없다. 받침 없는 쪽으로
            # 두는 편이 "돈슐랭2로"처럼 읽힌다.
            return False, False
    return False, False


def ro(word: str) -> str:
    """…로 / …으로. ㄹ 받침은 '로' 를 쓴다 (선발대로, 서울로)."""
    final, is_l = _has_final(word)
    return f"{word}로" if (not final or is_l) else f"{word}으로"


def neun(word: str) -> str:
    """…는 / …은"""
    final, _ = _has_final(word)
    return f"{word}은" if final else f"{word}는"


def ga(word: str) -> str:
    """…가 / …이"""
    final, _ = _has_final(word)
    return f"{word}이" if final else f"{word}가"


# --------------------------------------------------------------------------
# 영상별
# --------------------------------------------------------------------------

def video_rollup(labels: list[dict], collected: int,
                 cfg: AggregateConfig = DEFAULT) -> dict:
    """영상 하나의 댓글을 접는다. 순수 함수 — DB 를 모른다.

    labels 각 항목: {comment_id, text, like_count, sentiment, confidence,
                     sarcasm_suspect, topics}

    **대표 댓글에서 반어 의심은 뺀다.** 세는 데는 그대로 넣는다. 반어일지도
    모르는 칭찬을 "이 영상의 대표 긍정 댓글"로 리포트 맨 앞에 박아 두는 것이
    비율 한 칸 틀리는 것보다 나쁘다. (이 판단은 아키텍처에 없다 — 여기서
    정한 것이라 결정 문서에 올려 확정받아야 한다.)
    """
    n = len(labels)
    counts = Counter(x["sentiment"] for x in labels)
    topics: Counter = Counter()
    for x in labels:
        for t in x.get("topics") or []:
            if t not in cfg.ignore_topics:
                topics[t] += 1

    out = {
        "valid_comment_count": n,
        "positive": counts.get(POSITIVE, 0),
        "negative": counts.get(NEGATIVE, 0),
        "neutral": counts.get(NEUTRAL, 0),
        "positive_ratio": None,
        "negative_ratio": None,
        "neutral_ratio": None,
        "topic_counts": dict(topics.most_common()),
        "top_positive": [],
        "top_negative": [],
        "basis": "",
    }

    if n == 0:
        out["basis"] = (f"라벨된 댓글이 없다 (수집 {collected}건) — "
                        f"export-batch · import-batch 를 먼저 돌린다")
        return out

    def pick(sentiment: str) -> list[dict]:
        pool = [x for x in labels
                if x["sentiment"] == sentiment and not x.get("sarcasm_suspect")]
        pool.sort(key=lambda x: (-(x.get("like_count") or 0),
                                 -(x.get("confidence") or 0)))
        return [{"comment_id": x["comment_id"],
                 "text": (x.get("text") or "")[:200],
                 "like_count": x.get("like_count") or 0}
                for x in pool[:cfg.top_n]]

    out["top_positive"] = pick(POSITIVE)
    out["top_negative"] = pick(NEGATIVE)

    if n < cfg.min_labels:
        out["basis"] = (f"라벨 {n}건 (최소 {cfg.min_labels}건 필요) — "
                        f"비율은 내지 않고 대표 댓글만 남긴다")
        return out

    out["positive_ratio"] = out["positive"] / n
    out["negative_ratio"] = out["negative"] / n
    out["neutral_ratio"] = out["neutral"] / n
    out["basis"] = f"라벨 {n}/{collected}건 · 주제 언급 {sum(topics.values())}회"
    return out


# --------------------------------------------------------------------------
# 유형별
# --------------------------------------------------------------------------

def type_comment_rollup(labels_by_video: dict[str, list[dict]],
                        type_of: dict[str, str],
                        length_of: dict[str, str],
                        cfg: AggregateConfig = DEFAULT) -> list[dict]:
    """유형 × 길이 축(쇼츠/롱폼/합침)으로 댓글을 접는다.

    영상별 비율을 다시 평균하지 않고 **댓글을 다시 센다.** 댓글 3건짜리
    영상과 200건짜리 영상의 비율을 같은 무게로 평균하면 작은 영상이 유형
    전체의 성격을 흔든다.
    """
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    videos: dict[tuple[str, str], set] = defaultdict(set)
    for vid, rows in labels_by_video.items():
        code = type_of.get(vid)
        if not code:
            continue
        for axis in (view_group(length_of.get(vid, "standard")), ALL):
            buckets[(code, axis)].extend(rows)
            videos[(code, axis)].add(vid)

    out = []
    for (code, axis), rows in buckets.items():
        n = len(rows)
        counts = Counter(r["sentiment"] for r in rows)
        pos_t: Counter = Counter()
        neg_t: Counter = Counter()
        for r in rows:
            bag = pos_t if r["sentiment"] == POSITIVE else (
                neg_t if r["sentiment"] == NEGATIVE else None)
            if bag is None:
                continue
            for t in r.get("topics") or []:
                if t not in cfg.ignore_topics:
                    bag[t] += 1

        rec = {
            "type_code": code, "length_axis": axis,
            "labeled_video_count": len(videos[(code, axis)]),
            "valid_comment_count": n,
            "positive_ratio": counts.get(POSITIVE, 0) / n if n >= cfg.min_labels else None,
            "negative_ratio": counts.get(NEGATIVE, 0) / n if n >= cfg.min_labels else None,
            "top_positive_topics": dict(pos_t.most_common(5)),
            "top_negative_topics": dict(neg_t.most_common(5)),
            "basis": "",
        }
        rec["basis"] = (
            f"영상 {rec['labeled_video_count']}편 · 라벨 {n}건"
            if n >= cfg.min_labels
            else f"라벨 {n}건뿐이라 비율을 내지 않았다 (최소 {cfg.min_labels}건)"
        )
        out.append(rec)
    return sorted(out, key=lambda r: (r["type_code"], r["length_axis"]))


# --------------------------------------------------------------------------
# 전후 비교
# --------------------------------------------------------------------------

def recent_vs_prior(rows: list[dict], cfg: AggregateConfig = DEFAULT) -> dict:
    """최근 N편과 그 이전 N편의 유형별 조회 배수를 비교한다.

    rows 각 항목: {video_id, type_code, published_at, view_multiple}

    양쪽 다 3편 이상일 때만 값을 낸다. 2편 대 2편의 중앙값 차이를
    "최근 좋아지고 있다"고 읽으면 안 된다.
    """
    ordered = sorted((r for r in rows if r.get("published_at")),
                     key=lambda r: r["published_at"], reverse=True)
    recent, prior = ordered[:cfg.window], ordered[cfg.window:cfg.window * 2]
    if not prior:
        return {"basis": f"영상이 {len(ordered)}편뿐이라 전후로 가를 수 없다 "
                         f"(한쪽 {cfg.window}편 필요)", "types": {}}

    def by_type(part):
        d = defaultdict(list)
        for r in part:
            if r.get("type_code"):
                d[r["type_code"]].append(r.get("view_multiple"))
        return d

    a, b = by_type(recent), by_type(prior)
    types = {}
    for code in sorted(set(a) | set(b)):
        ra, rb = a.get(code, []), b.get(code, [])
        if len([x for x in ra if x is not None]) < 3 or \
           len([x for x in rb if x is not None]) < 3:
            continue
        ma, mb = _med(ra), _med(rb)
        types[code] = {"recent_n": len(ra), "prior_n": len(rb),
                       "recent": ma, "prior": mb, "delta": ma - mb}
    return {
        "basis": (f"최근 {len(recent)}편 vs 그 이전 {len(prior)}편 "
                  f"(양쪽 3편 이상인 유형만)"),
        "window": cfg.window,
        "types": types,
    }


# --------------------------------------------------------------------------
# 어느 축으로 읽어야 하는가
# --------------------------------------------------------------------------

def pick_axis(coverage: dict[str, float], length_axis: str,
              cfg: AggregateConfig = DEFAULT) -> tuple[str, str]:
    """길이 축마다 주 축을 고른다. coverage 는 {'topic': 0.0~1.0, 'segment': ...}

    채널이 코너로 관리하는 구간에서는 코너가 더 정확하고, 그렇지 않은
    구간에서는 주제로만 설명할 수 있다. 14F 는 롱폼의 72%가 코너에 속하고
    쇼츠는 0%다 — 같은 채널 안에서도 답이 갈린다. 그래서 채널이 아니라
    **길이 축마다** 고른다.
    """
    seg, top = coverage.get("segment", 0.0), coverage.get("topic", 0.0)
    lab = LENGTH_LABEL.get(length_axis, length_axis)
    if seg >= cfg.axis_coverage:
        return "segment", (f"{lab} 영상의 {seg:.0%}가 채널 재생목록의 코너에 속한다 — "
                           f"채널이 스스로 나눈 단위라 코너로 읽는다")
    if top <= 0:
        return "topic", f"{lab}에 유형 라벨이 없다"
    return "topic", (f"{lab} 영상 중 코너에 속한 것이 {seg:.0%}뿐이라 "
                     f"({cfg.axis_coverage:.0%} 미만) 주제로 읽는다")


# --------------------------------------------------------------------------
# 결론 문장 — 규칙이 쓴다
# --------------------------------------------------------------------------

NUM = re.compile(r"\d+(?:\.\d+)?")


def same_numbers(draft: str, polished: str) -> bool:
    """다듬은 문장이 초안의 수치를 그대로 갖고 있는지.

    순서는 봐주고 값은 안 봐준다. 1.76 을 '약 1.8' 로 고치는 것도 위반이다 —
    반올림 한 번이면 리포트의 배수와 결론의 배수가 달라진다.
    """
    return Counter(NUM.findall(draft)) == Counter(NUM.findall(polished))


def conclusion_draft(perf: list[dict], comments: list[dict],
                     names: dict[str, str], topic_names: dict[str, str],
                     axis: str, length_axis: str,
                     masked: list[dict] | None = None,
                     cfg: AggregateConfig = DEFAULT) -> tuple[str, str]:
    """규칙으로 결론 초안을 채운다. (문장, completeness) 를 돌려준다.

    perf 는 그 길이 축의 type_metrics 행들, comments 는 같은 축의
    type_comment_metrics 행들이다.

    **댓글이 일부 유형에만 있으면 그렇다고 말한다.** 7개 유형 중 2개에만
    댓글이 있는데 "부정 비율이 가장 높은 유형은 X"라고 쓰면, 읽는 사람은
    7개를 다 재고 고른 줄 안다. 지금 이 저장소의 데이터가 정확히 그
    상태다 — 300편 중 댓글을 받은 것이 2편이다.
    """
    lab = LENGTH_LABEL.get(length_axis, length_axis)
    unit = AXIS_LABEL.get(axis, axis)
    parts: list[str] = []

    ranked = sorted(
        (p for p in perf
         if p.get("med_view_multiple") is not None
         and (p.get("video_count") or 0) >= cfg.min_videos_headline),
        key=lambda p: -p["med_view_multiple"])

    if not ranked:
        return (f"{lab} 영상 중 {cfg.min_videos_headline}편 이상인 {unit}가 없어 "
                f"성과를 비교할 수 없다."), "empty"

    best, worst = ranked[0], ranked[-1]
    nm = lambda c: names.get(c, c)  # noqa: E731
    parts.append(
        f"{lab} 기준 조회 배수가 가장 높은 {unit}는 "
        f"{ro(nm(best['type_code']))} {best['med_view_multiple']:.2f}배다"
        f"({best['video_count']}편).")
    if worst is not best:
        parts.append(
            f"가장 낮은 것은 {ro(nm(worst['type_code']))} "
            f"{worst['med_view_multiple']:.2f}배다({worst['video_count']}편).")

    # -- 여기서부터는 댓글이 있어야 말할 수 있다 --------------------------
    withc = [c for c in comments if c.get("negative_ratio") is not None]
    scope = ""
    if withc and len(withc) < len(ranked):
        scope = f"댓글이 있는 {unit} {len(withc)}개 중 "

    cby = {c["type_code"]: c for c in comments}

    def top_topic(rec, key):
        d = (rec or {}).get(key) or {}
        if not d:
            return None
        code, n = next(iter(d.items()))
        return topic_names.get(code, code), n

    said = False
    hit = top_topic(cby.get(best["type_code"]), "top_positive_topics")
    if hit:
        said = True
        parts.append(f"그 {unit}의 긍정 댓글에서 가장 많이 나온 주제는 "
                     f"{ro(hit[0])} {hit[1]}건이다.")

    if withc:
        said = True
        z = max(withc, key=lambda c: c["negative_ratio"])
        line = (f"{scope}부정 댓글 비율이 가장 높은 {unit}는 "
                f"{ro(nm(z['type_code']))} {z['negative_ratio'] * 100:.1f}%")
        w = top_topic(z, "top_negative_topics")
        line += (f"이며, 그 지적은 주로 {w[0]}에 몰려 있다({w[1]}건)."
                 if w else "다.")
        parts.append(line)

    # 완결성은 "댓글 단계가 돌았는가"와 "얼마나 덮었는가"를 함께 본다.
    n_types = len(ranked)
    if not said:
        completeness = "performance_only"
        parts.append(f"댓글 라벨이 있는 {unit}가 없어 피드백은 넣지 못했다.")
    elif len(withc) < n_types:
        # 유형 하나라도 댓글이 없으면 "가장 높은/낮은"은 전수 비교가 아니다.
        completeness = "partial"
        parts.append(f"나머지 {unit} {n_types - len(withc)}개는 댓글을 받지 않아 "
                     f"피드백을 비교하지 못했다.")
    else:
        completeness = "full"

    for m in (masked or []):
        parts.append(
            f"{neun(nm(m['type_code']))} 쇼츠 {m['shorts']:.2f}배와 롱폼 "
            f"{m['longform']:.2f}배가 갈리므로 합친 값으로 읽으면 안 된다.")

    return " ".join(parts), completeness


def polish(client, draft: str, *, context: str = "") -> tuple[str, str]:
    """Claude 에 문장만 다듬게 한다. (문장, 출처) 를 돌려준다.

    출처는 'claude' 또는 'draft'. **수치가 하나라도 달라지면 초안을 쓴다** —
    이 함수가 실패해도 리포트는 언제나 나온다.
    """
    from app.prompts.registry import get

    prompt = get("conclusion_phrase")
    user = draft if not context else f"{context}\n\n## 다듬을 초안\n\n{draft}"
    try:
        data = client.judge(prompt, user)
    except Exception:
        return draft, "draft"
    text = (data.get("text") or "").strip()
    if not text or not same_numbers(draft, text):
        return draft, "draft"
    return text, "claude"


# --------------------------------------------------------------------------
# DB 연결부
# --------------------------------------------------------------------------

def _latest_label_version(conn) -> tuple[str, str] | None:
    r = conn.execute(
        """SELECT prompt_version, model FROM comment_labels
           GROUP BY prompt_version, model
           ORDER BY MAX(labeled_at) DESC LIMIT 1""").fetchone()
    return (r["prompt_version"], r["model"]) if r else None


def _read_labels(conn, prompt_version: str, model: str) -> dict[str, list[dict]]:
    rows = conn.execute(
        """SELECT c.video_id, c.comment_id, c.text, c.like_count,
                  l.sentiment, l.sentiment_confidence AS confidence,
                  l.is_sarcasm_suspect, l.topics_json
           FROM comment_labels l
           JOIN comments c ON c.comment_id = l.comment_id
           WHERE l.prompt_version = ? AND l.model = ?""",
        (prompt_version, model))
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["video_id"]].append({
            "comment_id": r["comment_id"], "text": r["text"],
            "like_count": r["like_count"], "sentiment": r["sentiment"],
            "confidence": r["confidence"],
            "sarcasm_suspect": bool(r["is_sarcasm_suspect"]),
            "topics": json.loads(r["topics_json"] or "[]"),
        })
    return out


def _type_map(conn, channel_id: str, axis: str):
    """활성 체계의 (taxonomy_id, {video_id: type_code}, {code: 이름})."""
    from app.pipeline.classify_videos import active_taxonomy

    tax = active_taxonomy(conn, channel_id, axis)
    if not tax:
        return None, {}, {}
    tid = tax["taxonomy_id"]
    labels = {r["video_id"]: r["type_code"] for r in conn.execute(
        "SELECT video_id, type_code FROM video_type_labels WHERE taxonomy_id=?", (tid,))}
    return tid, labels, json.loads(tax["types_json"])


def _latest_metric_run(conn, taxonomy_id: int) -> str | None:
    r = conn.execute(
        """SELECT run_id FROM type_metrics WHERE taxonomy_id=?
           ORDER BY computed_at DESC LIMIT 1""", (taxonomy_id,)).fetchone()
    return r["run_id"] if r else None


def run(conn, channel_id: str, run_id: str, *,
        prompt_version: str | None = None, model: str | None = None,
        client=None, cfg: AggregateConfig = DEFAULT) -> list[dict]:
    """영상·유형 댓글 집계를 만들고 길이 축마다 리포트를 하나씩 낸다.

    client 를 주면 결론 문장을 Claude 가 다듬는다. 안 주면 초안이 그대로
    나간다 — **댓글 라벨이 없어도, API 키가 없어도 리포트는 나온다.**
    그게 아키텍처 12장 2번 단계가 요구한 performance_only 경로다.
    """
    from app.exports import TOPIC_NAMES
    from app.pipeline.classify_videos import masked_types

    ver = (prompt_version, model) if (prompt_version and model) \
        else _latest_label_version(conn)
    pv, mdl = ver if ver else ("(없음)", "(없음)")
    labels_by_video = _read_labels(conn, pv, mdl) if ver else {}

    videos = {r["video_id"]: dict(r) for r in conn.execute(
        "SELECT video_id, length_axis, published_at FROM videos WHERE channel_id=?",
        (channel_id,))}
    if not videos:
        return []
    collected = {r["video_id"]: r["n"] for r in conn.execute(
        "SELECT video_id, COUNT(*) AS n FROM comments GROUP BY video_id")}
    now = _now()

    # -- (1) 영상별 -----------------------------------------------------
    for vid, rows in labels_by_video.items():
        v = video_rollup(rows, collected.get(vid, 0), cfg)
        conn.execute(
            """INSERT INTO video_comment_metrics
                   (video_id, run_id, prompt_version, model, valid_comment_count,
                    positive, negative, neutral, positive_ratio, negative_ratio,
                    neutral_ratio, topic_counts_json, top_positive_json,
                    top_negative_json, basis, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(video_id, run_id, prompt_version, model) DO UPDATE SET
                   valid_comment_count=excluded.valid_comment_count,
                   positive=excluded.positive, negative=excluded.negative,
                   neutral=excluded.neutral, positive_ratio=excluded.positive_ratio,
                   negative_ratio=excluded.negative_ratio,
                   neutral_ratio=excluded.neutral_ratio,
                   topic_counts_json=excluded.topic_counts_json,
                   top_positive_json=excluded.top_positive_json,
                   top_negative_json=excluded.top_negative_json,
                   basis=excluded.basis, computed_at=excluded.computed_at""",
            (vid, run_id, pv, mdl, v["valid_comment_count"], v["positive"],
             v["negative"], v["neutral"], v["positive_ratio"], v["negative_ratio"],
             v["neutral_ratio"],
             json.dumps(v["topic_counts"], ensure_ascii=False),
             json.dumps(v["top_positive"], ensure_ascii=False),
             json.dumps(v["top_negative"], ensure_ascii=False),
             v["basis"], now))

    length_of = {k: (x.get("length_axis") or "standard") for k, x in videos.items()}
    maps = {ax: _type_map(conn, channel_id, ax) for ax in ("topic", "segment")}
    reports = []

    # -- (2) 유형별 + (3) 리포트. 길이 축마다 한 판씩 ----------------------
    for length_axis in (SHORTS, LONGFORM, ALL):
        pool = [vid for vid in videos
                if length_axis == ALL or view_group(length_of[vid]) == length_axis]
        if not pool:
            continue

        coverage = {ax: sum(1 for v in pool if v in maps[ax][1]) / len(pool)
                    for ax in maps}
        axis, reason = pick_axis(coverage, length_axis, cfg)
        tid, tmap, names = maps[axis]
        if tid is None:
            continue

        crows = [c for c in type_comment_rollup(
            {k: v for k, v in labels_by_video.items() if k in pool},
            tmap, length_of, cfg) if c["length_axis"] == length_axis]
        for c in crows:
            conn.execute(
                """INSERT INTO type_comment_metrics
                       (channel_id, run_id, taxonomy_id, type_code, length_axis,
                        labeled_video_count, valid_comment_count, positive_ratio,
                        negative_ratio, top_positive_topics_json,
                        top_negative_topics_json, basis, computed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(channel_id, run_id, taxonomy_id, type_code, length_axis)
                   DO UPDATE SET
                       labeled_video_count=excluded.labeled_video_count,
                       valid_comment_count=excluded.valid_comment_count,
                       positive_ratio=excluded.positive_ratio,
                       negative_ratio=excluded.negative_ratio,
                       top_positive_topics_json=excluded.top_positive_topics_json,
                       top_negative_topics_json=excluded.top_negative_topics_json,
                       basis=excluded.basis, computed_at=excluded.computed_at""",
                (channel_id, run_id, tid, c["type_code"], length_axis,
                 c["labeled_video_count"], c["valid_comment_count"],
                 c["positive_ratio"], c["negative_ratio"],
                 json.dumps(c["top_positive_topics"], ensure_ascii=False),
                 json.dumps(c["top_negative_topics"], ensure_ascii=False),
                 c["basis"], now))

        mrun = _latest_metric_run(conn, tid)
        perf = [dict(r) for r in conn.execute(
            """SELECT * FROM type_metrics
               WHERE channel_id=? AND taxonomy_id=? AND length_axis=? AND run_id=?""",
            (channel_id, tid, length_axis, mrun))] if mrun else []

        # 합침 판만 "가려진 유형"을 경고한다. 쇼츠·롱폼 판은 그 자체가
        # 가려지지 않은 값이라 경고할 것이 없다.
        masked = []
        if length_axis == ALL and mrun:
            masked = masked_types([dict(r) for r in conn.execute(
                """SELECT type_code, length_axis, med_view_multiple
                   FROM type_metrics WHERE channel_id=? AND taxonomy_id=? AND run_id=?""",
                (channel_id, tid, mrun))])

        draft, completeness = conclusion_draft(
            perf, crows, names, TOPIC_NAMES, axis, length_axis, masked, cfg)
        text, source = polish(client, draft) if client is not None else (draft, "draft")

        vm = {r["video_id"]: r["view_multiple"] for r in conn.execute(
            """SELECT video_id, view_multiple FROM video_metrics
               WHERE run_id=(SELECT run_id FROM video_metrics
                             ORDER BY computed_at DESC LIMIT 1)""")}
        rvp = recent_vs_prior(
            [{"video_id": v, "type_code": tmap.get(v),
              "published_at": videos[v]["published_at"],
              "view_multiple": vm.get(v)} for v in pool], cfg)

        versions = {"comment_label": pv, "model": mdl, "rules": "rules-v1",
                    "axis": axis, "conclusion": source}
        conn.execute(
            """INSERT INTO reports
                   (channel_id, run_id, length_axis, taxonomy_id, axis, axis_reason,
                    prompt_version_set_json, masked_types_json, conclusion_draft,
                    conclusion_text, conclusion_source, recent_vs_prior_json,
                    completeness, built_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(channel_id, run_id, length_axis) DO UPDATE SET
                   taxonomy_id=excluded.taxonomy_id, axis=excluded.axis,
                   axis_reason=excluded.axis_reason,
                   prompt_version_set_json=excluded.prompt_version_set_json,
                   masked_types_json=excluded.masked_types_json,
                   conclusion_draft=excluded.conclusion_draft,
                   conclusion_text=excluded.conclusion_text,
                   conclusion_source=excluded.conclusion_source,
                   recent_vs_prior_json=excluded.recent_vs_prior_json,
                   completeness=excluded.completeness, built_at=excluded.built_at""",
            (channel_id, run_id, length_axis, tid, axis, reason,
             json.dumps(versions, ensure_ascii=False),
             json.dumps(masked, ensure_ascii=False), draft, text, source,
             json.dumps(rvp, ensure_ascii=False), completeness, now))

        reports.append({
            "length_axis": length_axis, "axis": axis, "axis_reason": reason,
            "coverage": coverage, "type_count": len(perf), "masked": masked,
            "conclusion": text, "conclusion_source": source,
            "completeness": completeness, "recent_vs_prior": rvp,
            "comment_rows": crows, "names": names,
        })
    return reports
