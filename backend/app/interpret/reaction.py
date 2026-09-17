"""Reaction 수치 → 짧은 한국어 문장 (Stage 09). 설계: docs/design/reaction-report.md 4장.

입력은 `app.pipeline.reaction_metrics` 가 만든 행(또는 `reaction_metrics` 표)이다.
여기서는 **고르고 말할 뿐** 새 수치를 만들지 않는다. 비교 대상인 「채널의 나머지」는
같은 길이 묶음의 channel 행에서 그 묶음의 **수**를 빼서 얻는다 (비율끼리 빼지 않는다).

## 지위

- 모든 문장은 `[검증 전 AI 판정]` 으로 시작하고 `validation_status` 를 달고 나간다.
- `finding_input = False`. MVP Finding(`feature_outcome`) 은 이 모듈을 import 하지 않으며,
  테스트가 그것을 확인한다 (closeout 「2026-09-17 재개 결정」).
- 관계만 말한다. 「그래서 조회가 높다」 「이렇게 하면 반응이 는다」 같은 인과·조언은 쓰지 않는다.

## 문장이 나가는 조건 (전부 만족, 값은 [제안])

| 조건 | 기본값 | 이유 |
|---|---|---|
| 묶음·나머지 각각 판정 댓글 수 | ≥ 50 | Stage 08 가림 기준(10)은 「비율을 적어도 되는가」, 이것은 「차이를 말해도 되는가」라 더 높다 |
| 묶음·나머지 각각 영상 수 | ≥ 5 | aggregate.min_videos_headline 과 같은 값. 댓글은 영상 안에서 뭉친다 — 영상 한두 편이 비율을 만든다 |
| 묶음·나머지 각각 UNKNOWN(판정 불가) 비율 | ≤ 20% | 판정 불가가 많으면 나머지 라벨 비율의 분모가 흔들린다 |
| 비율 차이의 절댓값 | ≥ 10%p | 유의성 검정이 아니다. 댓글이 영상 안에서 독립이 아니라 댓글 단위 검정은 과신한다 |

Reaction=None·UNKNOWN 자체의 차이는 문장으로 만들지 않는다 (판정 품질 신호이지 반응이 아니다).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from app.pipeline.label_reactions import REACTION_NAMES, REACTIONS, TARGET_NAMES, TARGETS
from app.pipeline.reaction_metrics import (
    CHANNEL_KEY,
    SCOPE_CHANNEL,
    SCOPE_TIER,
    SCOPE_TYPE,
    UNKNOWN_TIER,
    VALIDATION_STATUS,
)

INTERPRET_VERSION = "reaction-interpret-v0.1"
PREFIX = f"[{VALIDATION_STATUS}]"
AXIS_LABEL = {"shorts": "쇼츠", "longform": "롱폼", "all": ""}


@dataclass(frozen=True)
class InterpretConfig:
    """[제안] 사람 승인 전 기준값. 바꾸면 INTERPRET_VERSION 을 올린다."""

    min_comments: int = 50
    min_videos: int = 5
    max_unknown_share: float = 0.20
    min_diff: float = 0.10          # 비율 차이 (0.10 = 10%p)


DEFAULT = InterpretConfig()


def _single_version(records: list[dict]) -> tuple[str, str] | None:
    vs = {(r["prompt_version"], r["model"]) for r in records}
    if len(vs) > 1:
        raise ValueError(f"(prompt_version, model) 이 섞였다 {sorted(vs)} — 버전마다 따로 해석한다")
    return next(iter(vs)) if vs else None


def _rest(channel: dict, group: dict) -> dict:
    """채널 − 묶음. 수로 뺀다."""
    return {
        "n_comments": channel["n_comments"] - group["n_comments"],
        "n_videos": channel["n_videos"] - group["n_videos"],
        "unknown_count": channel["unknown_count"] - group["unknown_count"],
        "reaction_counts": {k: channel["reaction_counts"][k] - group["reaction_counts"][k]
                            for k in REACTIONS},
        "target_counts": {k: channel["target_counts"][k] - group["target_counts"].get(k, 0)
                          for k in TARGETS},
    }


def _why_not(side: str, x: dict, cfg: InterpretConfig) -> str | None:
    n = x["n_comments"]
    if n < cfg.min_comments:
        return f"{side} 판정 {n}건 (최소 {cfg.min_comments}건)"
    if x["n_videos"] < cfg.min_videos:
        return f"{side} 영상 {x['n_videos']}편 (최소 {cfg.min_videos}편)"
    if x["unknown_count"] / n > cfg.max_unknown_share:
        return (f"{side} 판정 불가(UNKNOWN) {x['unknown_count'] / n:.0%} "
                f"(최대 {cfg.max_unknown_share:.0%})")
    return None


def _group_phrase(rec: dict, names: dict) -> str | None:
    lab = AXIS_LABEL.get(rec["length_axis"], rec["length_axis"])
    lab = f"{lab} " if lab else ""
    if rec["scope"] == SCOPE_TYPE:
        name = (names.get(rec["taxonomy_id"]) or {}).get(rec["group_key"], rec["group_key"])
        return f"{lab}「{name}」 유형 영상"
    if rec["scope"] == SCOPE_TIER:
        key = rec["group_key"]
        if key == UNKNOWN_TIER:
            return None
        n_tiers = (rec.get("performance") or {}).get("n_tiers") or 3
        i = int(key[1:])
        pos = "하위" if i == 1 else "상위" if i == n_tiers else "중간"
        return f"{lab}조회 배수 {pos} 층({key}) 영상"
    return None


def interpret(records: list[dict], *, names: dict | None = None,
              cfg: InterpretConfig = DEFAULT) -> dict:
    """reaction_metrics 행들 → 문장 목록과 보류 목록.

    names: {taxonomy_id: {type_code: 이름}}. 없으면 코드를 그대로 쓴다.
    """
    names = names or {}
    base = {"version": INTERPRET_VERSION, "validation_status": VALIDATION_STATUS,
            "finding_input": False, "thresholds": asdict(cfg),
            "caveats": [
                f"모든 문장은 {VALIDATION_STATUS}을 집계한 것이며 독립 fresh 표본 검증 전이다.",
                "관계만 나타낸다. 원인이나 앞으로의 성과를 뜻하지 않는다.",
                "여러 묶음 × 15개 라벨을 한꺼번에 비교했다. 우연히 기준을 넘는 차이가 섞일 수 있다.",
                "표본 설계 가중치를 적용하지 않은 비가중 비율이다.",
            ],
            "sentences": [], "withheld": []}
    ver = _single_version(records)
    if ver is None:
        base["state"] = "empty"
        return base
    base["prompt_version"], base["model"] = ver
    base["state"] = "available"

    channels = {r["length_axis"]: r for r in records
                if r["scope"] == SCOPE_CHANNEL and r["group_key"] == CHANNEL_KEY}
    sentences, withheld = [], []
    for rec in records:
        if rec["scope"] not in (SCOPE_TYPE, SCOPE_TIER):
            continue
        phrase = _group_phrase(rec, names)
        ident = {k: rec[k] for k in ("scope", "taxonomy_id", "group_key", "length_axis")}
        if phrase is None:
            withheld.append({**ident, "reason": "성과값이 없는 영상 묶음(unknown)은 해석하지 않는다"})
            continue
        ch = channels.get(rec["length_axis"])
        if ch is None:
            withheld.append({**ident, "reason": "같은 길이 묶음의 채널 행이 없다"})
            continue
        rest = _rest(ch, rec)
        why = _why_not("묶음", rec, cfg) or _why_not("나머지", rest, cfg)
        if why:
            withheld.append({**ident, "reason": why})
            continue

        provisional = rec["scope"] == SCOPE_TIER and not (rec.get("performance") or {}).get("canonical")
        lab = AXIS_LABEL.get(rec["length_axis"], "")
        rest_phrase = f"채널의 나머지 {lab} 영상" if lab else "채널의 나머지 영상"
        n, rn = rec["n_comments"], rest["n_comments"]
        cand = [("reaction", k, rec["reaction_counts"][k] / n, rest["reaction_counts"][k] / rn,
                 f"{k} {REACTION_NAMES[k]}") for k in REACTIONS]
        cand += [("target", k, rec["target_counts"].get(k, 0) / n, rest["target_counts"][k] / rn,
                  f"대상이 {k} {TARGET_NAMES[k]}인") for k in TARGETS]
        for kind, code, g, c, what in cand:
            diff = g - c
            if abs(diff) < cfg.min_diff:
                continue
            noun = f"{what} 댓글" if kind == "target" else what
            text = (f"{PREFIX} {phrase} 댓글에서 {noun} 비율이 {rest_phrase} 댓글보다 "
                    f"{'높다' if diff > 0 else '낮다'} ({g * 100:.1f}% 대 {c * 100:.1f}%, "
                    f"댓글 {n}건·영상 {rec['n_videos']}편 대 {rn}건·{rest['n_videos']}편).")
            if provisional:
                text += " 조회 배수는 임시값(provisional)이다."
            sentences.append({
                "text": text, "validation_status": VALIDATION_STATUS, "finding_input": False,
                **ident, "label_kind": kind, "label": code,
                "group_share": g, "rest_share": c, "diff_pp": round(diff * 100, 1),
                "group_n": n, "group_videos": rec["n_videos"],
                "rest_n": rn, "rest_videos": rest["n_videos"],
                "provisional_performance": provisional, "rule": INTERPRET_VERSION,
            })
    sentences.sort(key=lambda s: (-abs(s["diff_pp"]), s["scope"], s["group_key"], s["label"]))
    base["sentences"], base["withheld"] = sentences, withheld
    return base


def records_from_db(conn, channel_id: str, run_id: str, prompt_version: str, model: str) -> list[dict]:
    """reaction_metrics 표에서 한 실행·한 버전의 행을 interpret 입력 모양으로."""
    out = []
    for r in conn.execute(
            """SELECT * FROM reaction_metrics WHERE channel_id=? AND run_id=?
               AND prompt_version=? AND model=?""", (channel_id, run_id, prompt_version, model)):
        d = dict(r)
        for k in ("reaction_counts", "reaction_shares", "target_counts", "target_shares",
                  "performance", "sampling"):
            d[k] = json.loads(d.pop(f"{k}_json"))
        d["masked"] = bool(d["masked"])
        out.append(d)
    return out
