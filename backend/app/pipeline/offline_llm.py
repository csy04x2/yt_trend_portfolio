"""오프라인 LLM 단계 — API 대신 Claude Code가 판정한다.

Anthropic API 키 없이 5단계(감성·주제 라벨링)를 시험하기 위한 경로다.
비용이 0이고, 프롬프트가 쓸 만한지를 돈 쓰기 전에 확인할 수 있다.

  export_batch()  규칙을 통과한 댓글을 프롬프트와 함께 파일 하나로 내보낸다
  (사람/Claude Code가 그 파일을 읽고 .result.json 을 쓴다)
  import_batch()  결과를 검증해 DB에 넣는다

검증이 이 모듈의 핵심이다. 사람이든 모델이든 번호를 빠뜨리거나 없는 번호를
만들 수 있고, 그걸 조용히 넘기면 나중에 집계가 틀린다. 아키텍처 9장의
"구조화 출력이 입력 번호와 안 맞음" 항목을 여기서 구현한다.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

PROMPTS = pathlib.Path(__file__).resolve().parents[1] / "prompts"

SENTIMENTS = {"positive", "negative", "neutral"}
# T1~T10. v2 에서 T10(조회수·성과 메타)이 늘었다. 옛 버전으로 만든
# 결과에는 T10 이 없을 뿐이라 이 집합을 넓혀도 과거 검증이 깨지지 않는다.
TOPICS = {f"T{i}" for i in range(1, 11)}
BATCH_SIZE = 20


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def export_batch(
    comments: list[dict],
    video_title: str,
    batch_id: str,
    out_dir: pathlib.Path,
) -> pathlib.Path:
    """댓글 묶음을 판정용 파일 하나로 내보낸다.

    comment_id 대신 묶음 안 1~N 번호를 쓴다. 긴 ID를 되돌려 받으면 출력 토큰이
    늘고 잘못 옮겨 적을 여지가 생긴다. 번호↔ID 대응은 이 파일 안에 남긴다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = (PROMPTS / "comment_label.md").read_text(encoding="utf-8")
    body, mapping = batch_body(comments, video_title, batch_id)
    sep = "\n\n---\n\n"
    text = prompt + sep + body + sep + _mapping_block(mapping)

    path = out_dir / f"{batch_id}.md"
    path.write_text(text, encoding="utf-8")

    # 대응표를 별도 파일로도 남긴다 — import가 읽는다
    (out_dir / f"{batch_id}.map.json").write_text(
        json.dumps({"batch": batch_id, "video_title": video_title, "map": mapping},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


class ValidationError(ValueError):
    pass


def validate_result(result: dict, mapping: dict[str, str]) -> list[dict]:
    """판정 결과를 검증한다. 통과하면 comment_id가 붙은 행들을 돌려준다.

    조용히 넘기지 않는다 — 틀린 것은 전부 모아 한 번에 알려준다.
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

        sent = r.get("sentiment")
        if sent not in SENTIMENTS:
            problems.append(f"{idx}: sentiment '{sent}' 는 허용값이 아니다")
        topics = r.get("topics") or []
        if not isinstance(topics, list) or not topics:
            problems.append(f"{idx}: topics 가 비었다")
        else:
            bad = [t for t in topics if t not in TOPICS]
            if bad:
                problems.append(f"{idx}: 없는 주제 코드 {bad}")
        conf = r.get("confidence")
        if conf is not None and not (isinstance(conf, (int, float)) and 0 <= conf <= 1):
            problems.append(f"{idx}: confidence 가 0~1 이 아니다 ({conf})")

        out.append({
            "comment_id": mapping[idx],
            "idx": int(idx),
            "sentiment": sent,
            "confidence": conf,
            "sarcasm_suspect": bool(r.get("sarcasm_suspect")),
            "topics": topics,
        })

    missing = sorted(set(mapping) - seen, key=int)
    if missing:
        problems.append(f"빠진 번호 {missing}")

    if problems:
        raise ValidationError("\n  - ".join(["판정 결과가 입력과 맞지 않는다:"] + problems))
    return out


def batch_body(comments: list[dict], video_title: str,
               batch_id: str) -> tuple[str, dict[str, str]]:
    """판정할 묶음 본문과 번호↔ID 대응표.

    **오프라인 경로와 API 경로가 이 함수를 함께 쓴다.** 두 경로가 서로 다른
    본문을 만들면, 오프라인에서 잰 정확도가 API 결과를 보장하지 못한다.
    """
    mapping = {str(i): c["comment_id"] for i, c in enumerate(comments, 1)}
    lines = [
        "# 이 묶음",
        "",
        f"- batch: `{batch_id}`",
        f"- 영상 제목: **{video_title}**",
        f"- 댓글 {len(comments)}건",
        "",
        "## 판정할 댓글",
        "",
    ]
    for i, c in enumerate(comments, 1):
        # 댓글 안의 줄바꿈은 기호로 바꾼다. 그대로 두면 번호 매긴 목록이
        # 끊겨 모델이 한 댓글을 둘로 읽는다.
        text = (c.get("text") or "").replace("\n", " ⏎ ")
        lines.append(f"{i}. (좋아요 {c.get('like_count', 0)}) {text}")
    return "\n".join(lines), mapping


def _mapping_block(mapping: dict[str, str]) -> str:
    return "\n".join([
        "## 번호 ↔ comment_id (판정에 쓰지 말 것. 되돌릴 때만 쓴다)",
        "",
        "```json",
        json.dumps(mapping, ensure_ascii=False, indent=2),
        "```",
    ])


def save_labels(conn, rows: list[dict], prompt_version: str, model: str,
                log=None) -> int:
    """검증을 통과한 판정을 comment_labels 에 넣는다.

    오프라인 import 와 API 경로가 함께 쓴다. (comment_id, 버전, 모델) 이
    PK 라 같은 묶음을 다시 돌려도 덮어쓰기만 된다.
    """
    written = 0
    for r in rows:
        try:
            conn.execute(
                """INSERT INTO comment_labels (comment_id, prompt_version, model,
                       sentiment, sentiment_confidence, is_sarcasm_suspect,
                       topics_json, labeled_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(comment_id, prompt_version, model) DO UPDATE SET
                       sentiment=excluded.sentiment,
                       sentiment_confidence=excluded.sentiment_confidence,
                       is_sarcasm_suspect=excluded.is_sarcasm_suspect,
                       topics_json=excluded.topics_json,
                       labeled_at=excluded.labeled_at""",
                (r["comment_id"], prompt_version, model, r["sentiment"],
                 r["confidence"], int(r["sarcasm_suspect"]),
                 json.dumps(r["topics"], ensure_ascii=False), _now()))
            written += 1
        except Exception as e:   # 표본에서 온 comment_id 는 DB 에 없을 수 있다
            if log:
                log(f"  건너뜀 {r['comment_id']}: {e}")
    return written
