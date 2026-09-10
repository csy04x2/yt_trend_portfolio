"""5단계 감성·주제 라벨링 — API 경로.

오프라인 경로(`offline_llm`)와 **같은 프롬프트 파일, 같은 묶음 본문, 같은
검증기**를 쓴다. 다른 것은 판정을 누가 하느냐뿐이다.

    오프라인   묶음 파일 → 사람이 Claude Code 에 붙여넣음 → .result.json → 검증 → DB
    API 경로   묶음 본문 → client.judge()                  → dict        → 검증 → DB
                            ~~~~~~~~~~~~~~~~ 여기만 다르다

이렇게 묶어 둔 이유는 하나다. 오프라인에서 282건을 판정하며 프롬프트를
다듬었는데, API 가 다른 문자열을 보내면 그 작업이 통째로 날아간다.

## 무엇을 판정 대상으로 삼는가

규칙 필터(`comment_screens`)가 `keep` 또는 `suspect_repeat` 으로 남긴 것.
`drop` 은 보내지 않는다 — 규칙이 확정한 것을 다시 물으면 돈만 나간다.
그리고 **이미 같은 (버전, 모델) 로 라벨된 것은 건너뛴다.** 중간에 끊겨도
다시 실행하면 남은 것부터 이어간다.

## 실패는 묶음 단위로 격리한다

한 묶음이 스키마 검증에 걸려도 나머지 묶음은 계속 간다. 200묶음짜리
작업이 3번째에서 통째로 죽으면 앞의 두 묶음 값도 못 쓴다.
실패한 묶음은 목록으로 돌려주고, 그 묶음의 댓글은 라벨이 없는 채로 남는다 —
다음 실행이 자연히 다시 집는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.pipeline.offline_llm import (
    BATCH_SIZE,
    ValidationError,
    batch_body,
    save_labels,
    validate_result,
)
from app.prompts.registry import get as get_prompt

# 규칙이 이 판정을 남긴 댓글만 LLM 으로 보낸다.
SENDABLE = ("keep", "suspect_repeat")


@dataclass
class Progress:
    batches: int = 0
    done: int = 0
    labeled: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def pending(conn, prompt_version: str, model: str,
            video_id: str | None = None, limit: int | None = None) -> list[dict]:
    """아직 라벨이 없는, 규칙을 통과한 댓글들. 영상별로 모아 돌려준다."""
    sql = """
        SELECT c.comment_id, c.video_id, c.text, c.like_count, v.title AS video_title
        FROM comments c
        JOIN videos v ON v.video_id = c.video_id
        JOIN comment_screens s ON s.comment_id = c.comment_id
        LEFT JOIN comment_labels l
               ON l.comment_id = c.comment_id
              AND l.prompt_version = ? AND l.model = ?
        WHERE s.verdict IN (%s) AND l.comment_id IS NULL
    """ % ",".join("?" * len(SENDABLE))
    params: list = [prompt_version, model, *SENDABLE]
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

    프롬프트가 영상 제목을 맥락으로 주므로 한 묶음에 두 영상이 섞이면
    제목이 맞지 않는 댓글이 생긴다.
    """
    out: list[list[dict]] = []
    by_video: dict[str, list[dict]] = {}
    for r in rows:
        by_video.setdefault(r["video_id"], []).append(r)
    for vid, rs in by_video.items():
        for i in range(0, len(rs), size):
            out.append(rs[i:i + size])
    return out


def estimate(rows: list[dict], size: int = BATCH_SIZE) -> dict:
    """보내기 전에 규모를 알려준다. 사람이 멈출 기회를 준다."""
    n_batches = sum(math.ceil(len(v) / size)
                    for v in _by_video(rows).values()) if rows else 0
    chars = sum(len(r.get("text") or "") for r in rows)
    return {"comments": len(rows), "batches": n_batches, "chars": chars}


def _by_video(rows: list[dict]) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = {}
    for r in rows:
        d.setdefault(r["video_id"], []).append(r)
    return d


def run(conn, client, *, model: str | None = None, video_id: str | None = None,
        limit: int | None = None, size: int = BATCH_SIZE,
        dry_run: bool = False, log=print) -> Progress:
    """규칙을 통과한 댓글을 API 로 판정해 comment_labels 에 넣는다.

    model 을 주지 않으면 클라이언트의 모델을 쓴다. 이 값이 곧 DB 의 해석
    키가 되므로, 모델을 바꾸면 같은 댓글이 새 행으로 다시 쌓인다 —
    덮어쓰기가 아니다. 그게 의도다.
    """
    prompt = get_prompt("comment_label")
    mdl = model or client.model
    rows = pending(conn, prompt.version, mdl, video_id, limit)
    batches = chunk(rows, size)
    p = Progress(batches=len(batches))

    est = estimate(rows, size)
    log(f"[라벨] 대상 {est['comments']}건 · {est['batches']}묶음 · "
        f"프롬프트 {prompt.name}({prompt.version}) · 모델 {mdl}")
    if dry_run or not batches:
        if not batches:
            log("  라벨할 것이 없다 — 규칙을 통과한 댓글이 전부 라벨돼 있다")
        else:
            log("  --dry-run 이라 호출하지 않았다")
        return p

    for i, group in enumerate(batches, 1):
        batch_id = f"api_{group[0]['video_id']}_{i:03d}"
        body, mapping = batch_body(group, group[0]["video_title"], batch_id)
        try:
            data = client.judge(prompt, body)
            labeled = validate_result(data, mapping)
        except ValidationError as e:
            p.failed.append((batch_id, f"검증 실패: {e}"))
            log(f"  [{i}/{len(batches)}] {batch_id} 검증 실패 — 건너뛴다")
            continue
        except Exception as e:
            p.failed.append((batch_id, f"{type(e).__name__}: {e}"))
            log(f"  [{i}/{len(batches)}] {batch_id} {type(e).__name__} — 건너뛴다")
            continue

        # 묶음마다 커밋한다. 중간에 죽어도 여기까지는 남는다.
        p.labeled += save_labels(conn, labeled, prompt.version, mdl, log=log)
        p.done += 1
        if i % 10 == 0 or i == len(batches):
            log(f"  [{i}/{len(batches)}] 누적 {p.labeled}건")

    log(f"[라벨] {p.done}/{p.batches}묶음 성공 · {p.labeled}건 저장")
    if p.failed:
        log(f"  실패 {len(p.failed)}묶음 — 그 댓글은 라벨 없이 남는다. "
            f"다시 실행하면 그것부터 집는다")
    log("  " + client.usage.describe(mdl))
    return p
