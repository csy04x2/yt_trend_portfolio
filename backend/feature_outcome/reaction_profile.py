"""영상별 Reaction 프로필 — `comment_reactions` 판정을 영상 단위 비율로 모은다.

설계: `docs/design/reaction-feature-join.md`. 기준 코드(R1–R10, T1–T5, UNKNOWN)는
`app.pipeline.label_reactions` 의 것을 그대로 쓰고 여기서 만들지 않는다.

## 결과의 지위

여기서 나오는 값은 전부 **「검증 전 AI 판정」** 이다. 독립 fresh 표본 검증을
통과하기 전까지 MVP Finding 입력이 아니다 (`docs/reaction-track-closeout-2026-09-17.md`
「2026-09-17 재개 결정」). 모든 프로필에 `validation_status` 와
`mvp_input_eligible: false` 를 박는다.

## 댓글 원문을 읽지 않는다

DB 로더는 `comments.text`, `comment_reactions.rationale`, timestamp 열을
**SELECT 하지 않는다.** 영상 ID·댓글 ID·부모 ID·분석 포함 여부와 코드 배열만
읽는다. DB 는 읽기 전용(`mode=ro`)으로 연다.

## 분모 (모두 [제안], 사람 확정 전)

- 분석 대상 = `analysis_eligible = 1` 인 댓글만. 0 이면 판정이 있어도 뺀다(H3).
- 단위 = 원댓글(`parent_id IS NULL`). 표본 정책의 `label_cap` 단위와 같다.
  `include_replies=True` 면 답글도 센다.
- Reaction 코드 비율 = 그 코드를 가진 판정 댓글 수 ÷ 판정된 분석 대상 댓글 수(n_labeled).
  한 댓글이 코드를 여럿 가질 수 있어 합이 1이 아니다. None 비율·UNKNOWN 비율도 같은 분모.
- Target 비율 = 그 Target 을 가진 댓글 ÷ **반응이 있는 댓글**(Reaction 이 None 도
  UNKNOWN 도 아닌 댓글). Reaction=None 댓글에 붙은 Target 은 세지 않는다.
- n_labeled 가 `MIN_LABELED_PER_VIDEO` 미만이면 비율을 내지 않고(null) 사유를 남긴다.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.pipeline.label_reactions import REACTIONS, TARGETS, UNKNOWN, check_label

VERSION = "reaction-profile-v0.1"
VALIDATION_STATUS = "검증 전 AI 판정"

# [제안] 영상당 최소 판정 댓글 수. 비율 p 의 표준오차 sqrt(p(1-p)/n) 는 p=0.5, n=30 에서
# 약 0.09 다. 표본 정책 프리셋의 label_cap(light 50 / standard 100) 안에 들어오는
# 가장 작은 둥근 값으로 골랐다. 사람이 정할 값이다 (설계 문서 7장).
MIN_LABELED_PER_VIDEO = 30

REACTION_SHARE_KEYS = tuple(f"reaction_share_{c}" for c in REACTIONS) + (
    "reaction_none_share", "reaction_unknown_share")
TARGET_SHARE_KEYS = tuple(f"reaction_target_share_{t}" for t in TARGETS) + (
    "reaction_target_unknown_share",)
SHARE_KEYS = REACTION_SHARE_KEYS + TARGET_SHARE_KEYS

# 프로필 상태
AVAILABLE = "available"
NO_ELIGIBLE = "no_eligible_comments"
NO_LABELS = "no_reaction_labels"
INSUFFICIENT = "insufficient_labeled_n"


def _eligible(value) -> bool:
    """분석 대상은 1 로 **확정된** 것만. NULL·문자열·0 은 대상이 아니다."""
    return not isinstance(value, bool) and value == 1 or value is True


def _ratio(num, den):
    return num / den if den else None


def build_profile(video_id: str, comments: list[dict], *, prompt_version: str, model: str,
                  min_labeled: int = MIN_LABELED_PER_VIDEO, include_replies: bool = False,
                  sampling: dict | None = None) -> dict:
    """한 영상의 Reaction 프로필.

    comments: 그 영상의 댓글 행. 각 행은
        {"comment_id", "parent_id", "analysis_eligible",
         "reactions": list | None, "targets": list | None, "review_flag": bool}
    reactions 가 None 이면 이 (prompt_version, model) 로 판정되지 않은 댓글이다.
    `[]` 는 Reaction=None 판정이다 — 둘은 다르다.
    """
    if min_labeled < 1:
        raise ValueError("min_labeled 는 1 이상이어야 한다")
    unit = [c for c in comments if include_replies or not c.get("parent_id")]
    eligible = [c for c in unit if _eligible(c.get("analysis_eligible"))]
    ineligible_labeled = sum(1 for c in unit
                             if not _eligible(c.get("analysis_eligible")) and c.get("reactions") is not None)

    labels, invalid = [], 0
    for c in eligible:
        if c.get("reactions") is None:
            continue
        label, problems = check_label({"reactions": c["reactions"], "targets": c.get("targets") or []},
                                      strict=False, where=str(c.get("comment_id")))
        if problems:
            invalid += 1
            continue
        labels.append({**label, "review_flag": bool(c.get("review_flag"))})

    n = len(labels)
    reaction_counts = {code: sum(code in lab["reactions"] for lab in labels) for code in REACTIONS}
    none_n = sum(lab["reactions"] == [] for lab in labels)
    unknown_n = sum(lab["reactions"] == [UNKNOWN] for lab in labels)
    reacting = [lab for lab in labels if lab["reactions"] and lab["reactions"] != [UNKNOWN]]
    target_counts = {t: sum(t in lab["targets"] for lab in reacting) for t in (*TARGETS, UNKNOWN)}

    if not eligible:
        status, reason = NO_ELIGIBLE, "분석 대상(analysis_eligible=1) 댓글이 없다"
    elif n == 0:
        status, reason = NO_LABELS, f"({prompt_version}, {model}) 판정이 없다"
    elif n < min_labeled:
        status, reason = INSUFFICIENT, f"판정 댓글 {n}건 < 최소 {min_labeled}건"
    else:
        status, reason = AVAILABLE, None

    shares = dict.fromkeys(SHARE_KEYS)
    target_reason = None
    if status == AVAILABLE:
        for code in REACTIONS:
            shares[f"reaction_share_{code}"] = reaction_counts[code] / n
        shares["reaction_none_share"] = none_n / n
        shares["reaction_unknown_share"] = unknown_n / n
        if reacting:
            for t in TARGETS:
                shares[f"reaction_target_share_{t}"] = target_counts[t] / len(reacting)
            shares["reaction_target_unknown_share"] = target_counts[UNKNOWN] / len(reacting)
        else:
            target_reason = "반응이 있는 댓글이 없어 Target 분모가 0이다"

    return {
        "video_id": video_id,
        "profile_version": VERSION,
        "validation_status": VALIDATION_STATUS,
        "mvp_input_eligible": False,
        "prompt_version": prompt_version,
        "model": model,
        "label_unit": "all_comments" if include_replies else "top_level",
        "status": status,
        "reason": reason,
        "min_labeled": min_labeled,
        "eligible_n": len(eligible),
        "n_labeled": n,
        "label_coverage": _ratio(n, len(eligible)),
        "reacting_n": len(reacting),
        "invalid_label_n": invalid,
        "ineligible_labeled_n": ineligible_labeled,
        "counts": {**reaction_counts, "None": none_n, UNKNOWN: unknown_n},
        "target_counts": target_counts,
        "review_flag_share": _ratio(sum(lab["review_flag"] for lab in labels), n),
        "shares": shares,
        "target_share_reason": target_reason,
        "sampling": sampling if sampling is not None else {"status": "not_recorded"},
    }


def build_profiles(video_ids, comments: list[dict], **kwargs) -> dict[str, dict]:
    """선택된 영상마다 프로필 하나. 선택 밖 영상의 댓글은 보지 않는다."""
    wanted = list(video_ids)
    by_video: dict[str, list[dict]] = {vid: [] for vid in wanted}
    for c in comments:
        if c.get("video_id") in by_video:
            by_video[c["video_id"]].append(c)
    sampling = kwargs.pop("sampling", None) or {}
    return {vid: build_profile(vid, by_video[vid], sampling=sampling.get(vid), **kwargs)
            for vid in sorted(wanted)}


# --------------------------------------------------------------------------
# 읽기 전용 DB 로더 — 원문·rationale 열은 SELECT 하지 않는다
# --------------------------------------------------------------------------

def open_readonly(db_path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"DB 가 없다: {path}")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _chunks(ids, size=500):
    ids = sorted(ids)
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


def load_comment_reactions(conn, video_ids, *, prompt_version: str, model: str) -> list[dict]:
    """선택 영상 댓글의 분석 포함 여부와 (prompt_version, model) 판정 코드."""
    tables = _tables(conn)
    if not {"comments", "comment_reactions"} <= tables:
        raise ValueError("DB 에 comments 와 comment_reactions 표가 모두 있어야 한다")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(comments)")}
    if not {"analysis_eligible", "parent_id"} <= cols:
        raise ValueError("comments 에 analysis_eligible·parent_id 열이 없다 — 분석 포함 여부가 "
                         "확정되지 않은 DB 는 집계하지 않는다 (docs/design/comment-eligibility.md)")
    out = []
    for part in _chunks(video_ids):
        marks = ",".join("?" * len(part))
        sql = f"""
            SELECT c.video_id, c.comment_id, c.parent_id, c.analysis_eligible,
                   r.reactions_json, r.targets_json, r.review_flag
            FROM comments c
            LEFT JOIN comment_reactions r
                   ON r.comment_id = c.comment_id AND r.prompt_version = ? AND r.model = ?
            WHERE c.video_id IN ({marks})
            ORDER BY c.video_id, c.comment_id"""
        for r in conn.execute(sql, [prompt_version, model, *part]):
            labeled = r["reactions_json"] is not None
            out.append({
                "video_id": r["video_id"],
                "comment_id": r["comment_id"],
                "parent_id": r["parent_id"],
                "analysis_eligible": r["analysis_eligible"],
                "reactions": json.loads(r["reactions_json"]) if labeled else None,
                "targets": json.loads(r["targets_json"]) if labeled and r["targets_json"] else ([] if labeled else None),
                "review_flag": bool(r["review_flag"]) if labeled else False,
            })
    return out


def label_versions(conn) -> list[dict]:
    """DB 에 있는 (prompt_version, model) 조합과 건수. 섞어 집계하지 않았음을 남긴다."""
    if "comment_reactions" not in _tables(conn):
        return []
    return [dict(r) for r in conn.execute(
        "SELECT prompt_version, model, COUNT(*) AS n FROM comment_reactions "
        "GROUP BY prompt_version, model ORDER BY prompt_version, model")]


def load_sampling(conn, video_ids, run_id: str | None = None) -> dict[str, dict]:
    """observation_sampling 의 영상별 결정·완결성. 표가 없으면 빈 dict.

    run_id 를 주지 않았는데 한 영상에 실행이 여럿이면 고르지 않고
    `ambiguous_multiple_runs` 로 남긴다.
    """
    if "observation_sampling" not in _tables(conn):
        return {}
    rows: dict[str, list[dict]] = {}
    for part in _chunks(video_ids):
        marks = ",".join("?" * len(part))
        sql = (f"SELECT run_id, video_id, split, decision, reason, completeness, inclusion_prob, "
               f"label_cap, policy_name, policy_version FROM observation_sampling WHERE video_id IN ({marks})")
        params = list(part)
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        for r in conn.execute(sql, params):
            rows.setdefault(r["video_id"], []).append(dict(r))
    out = {}
    for vid, rs in rows.items():
        if len(rs) > 1:
            out[vid] = {"status": "ambiguous_multiple_runs", "run_ids": sorted(r["run_id"] for r in rs)}
        else:
            out[vid] = {"status": "recorded", **rs[0]}
    return out
