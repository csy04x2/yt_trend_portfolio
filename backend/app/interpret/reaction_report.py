"""대시보드 evidence JSON 의 `reaction_report` 블록을 만든다.

Stage 08 수치(`reaction_metrics.collect`)와 Stage 09 문장(`reaction.interpret`)을 화면이 읽는
모양 하나로 묶는다. 파일 쓰기는 `backend/scripts/export_reaction_report.py` 가 맡는다.

판정이 하나도 없으면 **숫자를 만들지 않고** `state = "empty"` 와 빈 목록을 낸다. 화면은
그 상태를 「아직 판정 결과 없음 — 판정 실행 후 채워짐」으로 그린다.
"""

from __future__ import annotations

import datetime as dt

from app.interpret.reaction import DEFAULT as INTERPRET_DEFAULT
from app.interpret.reaction import INTERPRET_VERSION, InterpretConfig, interpret
from app.pipeline import reaction_metrics as rm
from app.pipeline.label_reactions import REACTION_NAMES, REACTIONS, TARGET_NAMES, UNKNOWN

EMPTY_MESSAGE = "아직 판정 결과 없음 — 판정 실행 후 채워짐"
BLOCK_KEY = "reaction_report"

DISPLAY_RULES = [
    "모든 Reaction·Target 값은 「검증 전 AI 판정」이다. 독립 fresh 표본 검증을 통과하기 전까지 배지를 뗄 수 없다.",
    "MVP Finding 입력이 아니다. 화면의 문장은 참고용 해석이며 Finding 카드로 올리지 않는다.",
    "비율은 「그 라벨을 가진 댓글 ÷ 판정된 분석 대상 댓글」이다. 한 댓글이 여러 Reaction 을 가질 수 있어 합이 100%를 넘는다.",
    "Reaction 없음(None)과 판정 불가(UNKNOWN)는 따로 표시한다.",
    "판정이 최소치보다 적은 묶음은 비율 대신 「표본 부족」으로 가린다.",
    "판정 결과가 없으면 숫자를 만들지 않고 빈 상태를 보여 준다.",
]

HOW_TO_FILL = [
    "# backend/ 에서. <DB> 는 ./data/<채널>.db",
    "python -m app.cli --db <DB> export-reaction-batch rx --out ./data/batches/reaction   # 오프라인 판정 묶음 (비용 0)",
    "# 각 묶음 .md 를 Claude Code 로 판정해 rx_NNN.result.json 으로 저장한 뒤",
    "python -m app.cli --db <DB> import-reaction-batch rx_001 --out ./data/batches/reaction  # → comment_reactions",
    "python -m app.cli --db <DB> reaction-metrics                                          # Stage 08 수치 → reaction_metrics",
    "python scripts/export_reaction_report.py --db <DB> --render                           # evidence JSON + 대시보드",
]

ROW_KEYS = ("scope", "taxonomy_id", "taxonomy_axis", "group_key", "length_axis", "n_videos",
            "n_eligible_comments", "n_comments", "labeled_ratio", "reaction_counts",
            "reaction_shares", "none_count", "none_share", "unknown_count", "unknown_share",
            "target_counts", "target_shares", "no_target_count", "multi_reaction_count",
            "review_flag_count", "masked", "basis", "validation_status")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def build_block(records: list[dict], *, taxonomies: list[dict] | None = None,
                source: dict | None = None,
                interpret_cfg: InterpretConfig = INTERPRET_DEFAULT) -> dict:
    """수치 행 → 화면 블록. 순수 함수. records 는 한 (버전, 모델) 의 것이어야 한다."""
    taxonomies = taxonomies or []
    names = {t["taxonomy_id"]: t.get("names") or {} for t in taxonomies}
    shown = [r for r in records if r["scope"] in (rm.SCOPE_CHANNEL, rm.SCOPE_TYPE, rm.SCOPE_TIER)]
    rows = []
    for r in shown:
        row = {k: r.get(k) for k in ROW_KEYS}
        if r["scope"] == rm.SCOPE_TYPE:
            row["group_name"] = names.get(r["taxonomy_id"], {}).get(r["group_key"], r["group_key"])
        elif r["scope"] == rm.SCOPE_TIER:
            row["group_name"] = r["group_key"]
        else:
            row["group_name"] = "채널 전체"
        rows.append(row)
    total = next((r for r in shown if r["scope"] == rm.SCOPE_CHANNEL and r["length_axis"] == "all"), None)
    perf = next((r.get("performance") for r in shown if r["scope"] == rm.SCOPE_TIER), None)
    state = "available" if total and total["n_comments"] > 0 else "empty"
    return {
        "validation_status": rm.VALIDATION_STATUS,
        "state": state,
        "empty_message": EMPTY_MESSAGE,
        "finding_input": False,
        "metrics_version": rm.METRICS_VERSION,
        "interpret_version": INTERPRET_VERSION,
        "codes": {
            "reactions": [[k, REACTION_NAMES[k]] for k in REACTIONS],
            "targets": [[k, TARGET_NAMES[k]] for k in list(TARGET_NAMES) if k != UNKNOWN]
                       + [[UNKNOWN, TARGET_NAMES[UNKNOWN]]],
        },
        "source": {**(source or {}), "n_labeled_comments": total["n_comments"] if total else 0},
        "min_comments": rm.DEFAULT.min_comments,
        "taxonomies": [{"taxonomy_id": t["taxonomy_id"], "axis": t.get("axis"),
                        "names": t.get("names") or {}} for t in taxonomies],
        "rows": rows if state == "available" else [],
        "performance": perf or {},
        "sampling": (total or {}).get("sampling") or {},
        "interpretation": interpret(records if state == "available" else [], names=names,
                                    cfg=interpret_cfg),
        "display_rules": DISPLAY_RULES,
        "how_to_fill": HOW_TO_FILL,
        "generated_at": _now(),
    }


def block_from_db(conn, *, channel_id: str | None = None, prompt_version: str | None = None,
                  model: str | None = None, manifest: dict | None = None,
                  db_name: str | None = None) -> dict:
    """DB(읽기 전용이어도 된다) → 화면 블록. 쓰지 않는다.

    버전을 주지 않으면 가장 최근에 판정한 (버전, 모델) 하나를 쓰고, 나머지는
    `source.versions_available` 에 이름만 남긴다. 섞지 않는다.
    """
    if channel_id is None:
        chans = [r[0] for r in conn.execute("SELECT channel_id FROM channels")] \
            if rm._has_table(conn, "channels") else []
        if len(chans) > 1:
            raise ValueError(f"채널이 {len(chans)}개다 — channel_id 를 지정한다")
        channel_id = chans[0] if chans else None
    versions = rm.label_versions(conn)
    if not (prompt_version and model) and versions:
        prompt_version, model = versions[0]
    source = {"db": db_name, "channel_id": channel_id, "prompt_version": prompt_version,
              "model": model, "versions_available": [list(v) for v in versions],
              "comment_reactions_table": rm._has_table(conn, "comment_reactions")}
    if channel_id is None or not (prompt_version and model):
        return build_block([], source=source)
    records = rm.collect(conn, channel_id, prompt_version=prompt_version, model=model,
                         manifest=manifest)
    return build_block(records, taxonomies=rm.read_type_maps(conn, channel_id), source=source)
