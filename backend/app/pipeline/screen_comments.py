"""4단계 댓글 선별 — 규칙 다음의 Claude 절반.

규칙(`pipeline/rules.py`)이 먼저 돌고, 여기가 그 뒤를 잇는다. 두 판정은
**같은 표에 나란히 앉는다.**

    comment_screens (comment_id, prompt_version, model)
      ('c1', 'rules-v1',  'rule')            verdict=keep          ← 규칙
      ('c1', 'screen-v1', 'claude-sonnet-5') verdict=drop, reason  ← 여기

같은 댓글에 두 행이 생기는 것이 설계다. 규칙 행을 덮어쓰지 않는다 — 덮어쓰면
"규칙은 통과시켰는데 모델이 버렸다"는 사실이 사라지고, 그 차이가 바로 이
단계를 붙인 이유(규칙의 오탐·미탐을 세는 것)이기 때문이다.

## 무엇을 보내는가

규칙이 `keep` 또는 `suspect_repeat` 으로 남긴 것만이다(`label_comments.SENDABLE`).
규칙이 `promo`·`irrelevant` 로 확정한 것을 다시 물으면 돈만 나간다. 그리고
이미 같은 (버전, 모델) 로 판정된 것은 건너뛴다 — 끊겨도 이어서 돈다.

## reason 이 rule_flags_json 에 들어가지 않는 이유

`rule_flags_json` 은 이름이 말하는 대로 **규칙이 붙인 표시**의 자리다
(`['url', 'repeat']`). 모델이 쓴 한 줄 설명을 거기 넣으면, 그 열을 읽는
쪽은 리스트를 기대하는데 문장이 나오고, "규칙 표시"를 세는 집계가 조용히
틀린다. 그래서 `reason` 열을 따로 뒀다. 규칙 행은 이 열을 NULL 로 둔다 —
규칙은 이유를 문장으로 쓰지 않고 표시로 남기기 때문이다.

## 실패는 묶음 단위로 격리한다

`label_comments` 와 같다. 한 묶음이 검증에 걸려도 나머지는 계속 간다.
실패한 묶음의 댓글은 판정 없이 남고, 다음 실행이 자연히 다시 집는다.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
from dataclasses import dataclass, field

from app.pipeline.label_comments import SENDABLE
from app.pipeline.offline_llm import BATCH_SIZE, _mapping_block, batch_body
from app.pipeline.rules import MODEL_RULE
from app.prompts.registry import get as get_prompt

PROMPT_NAME = "comment_screen"

# 프롬프트가 돌려줄 수 있는 판정. 규칙의 verdict(4종)와 다르다 — 모델은
# 통과/버림만 가른다. 왜 버렸는지는 reason 에 문장으로 남는다.
VERDICTS = frozenset({"keep", "drop"})


@dataclass
class Progress:
    batches: int = 0
    done: int = 0
    screened: int = 0
    kept: int = 0
    dropped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 대상 고르기
# --------------------------------------------------------------------------

def pending(conn, prompt_version: str, model: str,
            video_id: str | None = None, limit: int | None = None) -> list[dict]:
    """규칙을 통과했고 아직 이 (버전, 모델) 로 판정되지 않은 댓글들.

    규칙 행은 model 로 못박아 고른다. 못박지 않으면, 한 번 돌린 뒤부터는
    이 단계가 만든 행까지 "규칙 판정"으로 세어져 같은 댓글이 여러 번
    대상에 오른다.
    """
    sql = """
        SELECT c.comment_id, c.video_id, c.text, c.like_count, v.title AS video_title
        FROM comments c
        JOIN videos v ON v.video_id = c.video_id
        JOIN comment_screens r
             ON r.comment_id = c.comment_id AND r.model = ?
        LEFT JOIN comment_screens s
             ON s.comment_id = c.comment_id
            AND s.prompt_version = ? AND s.model = ?
        WHERE r.verdict IN (%s) AND s.comment_id IS NULL
    """ % ",".join("?" * len(SENDABLE))
    params: list = [MODEL_RULE, prompt_version, model, *SENDABLE]
    if video_id:
        sql += " AND c.video_id = ?"
        params.append(video_id)
    sql += " ORDER BY c.video_id, c.published_at"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def chunk(rows: list[dict], size: int = BATCH_SIZE) -> list[list[dict]]:
    """영상 경계를 넘지 않게 자른다.

    묶음 본문이 영상 제목을 맥락으로 주므로(`offline_llm.batch_body`) 한
    묶음에 두 영상이 섞이면 제목이 맞지 않는 댓글이 생긴다. 「영상과 아무
    상관 없는 복붙」을 가르는 판정이라 제목이 틀리면 판정도 틀린다.
    """
    out: list[list[dict]] = []
    by_video: dict[str, list[dict]] = {}
    for r in rows:
        by_video.setdefault(r["video_id"], []).append(r)
    for rs in by_video.values():
        for i in range(0, len(rs), size):
            out.append(rs[i:i + size])
    return out


def estimate(rows: list[dict], size: int = BATCH_SIZE) -> dict:
    """보내기 전에 규모를 알려준다. 사람이 멈출 기회를 준다."""
    by_video: dict[str, int] = {}
    for r in rows:
        by_video[r["video_id"]] = by_video.get(r["video_id"], 0) + 1
    return {
        "comments": len(rows),
        "batches": sum(math.ceil(n / size) for n in by_video.values()),
        "chars": sum(len(r.get("text") or "") for r in rows),
    }


# --------------------------------------------------------------------------
# 검증 — 조용히 넘기지 않는다
# --------------------------------------------------------------------------

class ValidationError(ValueError):
    pass


def validate_screens(result: dict, mapping: dict[str, str]) -> list[dict]:
    """선별 결과를 검증한다. 통과하면 comment_id 가 붙은 행들을 돌려준다.

    `offline_llm.validate_result` 와 같은 규율이다 — 없는 번호, 중복,
    빠진 번호, 허용값 아닌 verdict 를 **전부 모아 한 번에** 알린다.
    첫 번째에서 멈추면 프롬프트를 한 번 고칠 때마다 한 가지씩만 알게 된다.

    감성 라벨의 검증기를 손대지 않고 따로 쓰는 이유는 스키마가 다르기
    때문이다. 저쪽은 sentiment·topics 를 요구하는데 이쪽 출력에는 없다.
    """
    problems: list[str] = []
    rows = result.get("results")
    if not isinstance(rows, list):
        raise ValidationError("results 가 배열이 아니다")

    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        idx = str(r.get("idx"))
        if idx not in mapping:
            problems.append(f"입력에 없는 번호 {idx}")
            continue
        if idx in seen:
            problems.append(f"번호 {idx} 중복")
            continue
        seen.add(idx)

        verdict = r.get("verdict")
        if verdict not in VERDICTS:
            problems.append(f"{idx}: verdict '{verdict}' 는 허용값이 아니다 "
                            f"(허용: {sorted(VERDICTS)})")
            continue

        reason = r.get("reason")
        if isinstance(reason, str):
            reason = reason.strip() or None
        elif reason is not None:
            problems.append(f"{idx}: reason 이 문자열이 아니다 ({type(reason).__name__})")
            reason = None

        out.append({
            "comment_id": mapping[idx],
            "idx": int(idx),
            "verdict": verdict,
            "reason": reason,
        })

    missing = sorted(set(mapping) - seen, key=int)
    if missing:
        problems.append(f"빠진 번호 {missing}")

    if problems:
        raise ValidationError("\n  - ".join(["선별 결과가 입력과 맞지 않는다:"] + problems))
    return out


# --------------------------------------------------------------------------
# 저장
# --------------------------------------------------------------------------

def save_screens(conn, rows: list[dict], prompt_version: str, model: str,
                 log=None) -> int:
    """검증을 통과한 판정을 comment_screens 에 넣는다.

    `rule_flags_json` 은 건드리지 않고 NULL 로 둔다 — 규칙이 붙인 표시의
    자리라 모델은 쓸 것이 없다. 같은 (댓글, 버전, 모델) 을 다시 돌리면
    덮어쓰기만 된다. 규칙 행은 model 이 달라 그대로 남는다.
    """
    written = 0
    for r in rows:
        try:
            conn.execute(
                """INSERT INTO comment_screens (comment_id, prompt_version, model,
                       rule_flags_json, verdict, reason, screened_at)
                   VALUES (?,?,?,NULL,?,?,?)
                   ON CONFLICT(comment_id, prompt_version, model) DO UPDATE SET
                       verdict=excluded.verdict,
                       reason=excluded.reason,
                       screened_at=excluded.screened_at""",
                (r["comment_id"], prompt_version, model, r["verdict"],
                 r["reason"], _now()))
            written += 1
        except Exception as e:   # 표본에서 온 comment_id 는 DB 에 없을 수 있다
            if log:
                log(f"  건너뜀 {r['comment_id']}: {e}")
    return written


# --------------------------------------------------------------------------
# 오프라인 경로 — 비용 0으로 프롬프트를 다듬는 자리
# --------------------------------------------------------------------------

def export(comments: list[dict], video_title: str, batch_id: str,
           out_dir: pathlib.Path) -> pathlib.Path:
    """댓글 묶음을 선별용 파일 하나로 내보낸다.

    `offline_llm.export_batch` 와 같은 모양이고, **같은 `batch_body` 를
    쓴다.** 프롬프트만 comment_screen 이다. 라벨링이 그랬듯 선별도 돈을
    쓰기 전에 오프라인에서 정확도를 재고 프롬프트를 고칠 수 있어야 한다.
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = get_prompt(PROMPT_NAME)
    body, mapping = batch_body(comments, video_title, batch_id)
    sep = "\n\n---\n\n"
    text = prompt.full_text + sep + body + sep + _mapping_block(mapping)

    path = out_dir / f"{batch_id}.md"
    path.write_text(text, encoding="utf-8")
    (out_dir / f"{batch_id}.map.json").write_text(
        json.dumps({"batch": batch_id, "video_title": video_title,
                    "prompt": prompt.name, "prompt_version": prompt.version,
                    "map": mapping}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# API 경로
# --------------------------------------------------------------------------

def run(conn, client, *, model: str | None = None, video_id: str | None = None,
        limit: int | None = None, size: int = BATCH_SIZE,
        dry_run: bool = False, log=print) -> Progress:
    """규칙을 통과한 댓글을 API 로 선별해 comment_screens 에 넣는다.

    model 을 주지 않으면 클라이언트의 모델을 쓴다. 이 값이 곧 DB 의 판정
    키가 되므로, 모델을 바꾸면 같은 댓글이 새 행으로 다시 쌓인다 —
    덮어쓰기가 아니다. 규칙 행과 나란히 앉는 것도 같은 이치다.
    """
    prompt = get_prompt(PROMPT_NAME)
    mdl = model or client.model
    rows = pending(conn, prompt.version, mdl, video_id, limit)
    batches = chunk(rows, size)
    p = Progress(batches=len(batches))

    est = estimate(rows, size)
    log(f"[선별] 대상 {est['comments']}건 · {est['batches']}묶음 · "
        f"프롬프트 {prompt.name}({prompt.version}) · 모델 {mdl}")
    if dry_run or not batches:
        if not batches:
            log("  선별할 것이 없다 — 규칙을 통과한 댓글이 전부 판정돼 있다")
        else:
            log("  --dry-run 이라 호출하지 않았다")
        return p

    for i, group in enumerate(batches, 1):
        batch_id = f"api_{group[0]['video_id']}_s{i:03d}"
        body, mapping = batch_body(group, group[0]["video_title"], batch_id)
        try:
            data = client.judge(prompt, body)
            judged = validate_screens(data, mapping)
        except ValidationError as e:
            p.failed.append((batch_id, f"검증 실패: {e}"))
            log(f"  [{i}/{len(batches)}] {batch_id} 검증 실패 — 건너뛴다")
            continue
        except Exception as e:
            p.failed.append((batch_id, f"{type(e).__name__}: {e}"))
            log(f"  [{i}/{len(batches)}] {batch_id} {type(e).__name__} — 건너뛴다")
            continue

        # 묶음마다 커밋한다. 중간에 죽어도 여기까지는 남는다.
        p.screened += save_screens(conn, judged, prompt.version, mdl, log=log)
        p.kept += sum(1 for r in judged if r["verdict"] == "keep")
        p.dropped += sum(1 for r in judged if r["verdict"] == "drop")
        p.done += 1
        if i % 10 == 0 or i == len(batches):
            log(f"  [{i}/{len(batches)}] 누적 {p.screened}건 "
                f"(통과 {p.kept} · 버림 {p.dropped})")

    log(f"[선별] {p.done}/{p.batches}묶음 성공 · {p.screened}건 저장 "
        f"(통과 {p.kept} · 버림 {p.dropped})")
    if p.failed:
        log(f"  실패 {len(p.failed)}묶음 — 그 댓글은 판정 없이 남는다. "
            f"다시 실행하면 그것부터 집는다")
    log("  " + client.usage.describe(mdl))
    return p
