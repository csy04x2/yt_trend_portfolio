"""라벨 결과 내보내기.

DB 파일을 그대로 주고받지 않기 위해 있다. SQLite 파일은 열어보려면 도구가
필요하고, 커밋하면 바이너리라 diff 가 안 보이며, 매 실행마다 통째로 바뀌어
저장소를 부풀린다. 사람이 검수하려는 것은 결국 표 하나다.

CSV 는 **UTF-8 BOM 으로 쓴다.** 한국어 윈도우의 엑셀은 BOM 이 없는 UTF-8
CSV 를 cp949 로 읽어 한글을 깨뜨린다. 프로그램이 읽을 때는 BOM 이 문제되지
않는다(`utf-8-sig`). 검수자가 엑셀로 열 것을 전제하므로 BOM 쪽을 택한다.

주제 코드(T1…T9)는 사람이 읽을 이름을 나란히 넣는다. 검수자가 코드표를
따로 펴놓고 봐야 한다면 그건 표가 덜 만들어진 것이다.
"""

from __future__ import annotations

import csv
import json
import pathlib

# 주제 코드 → 이름. 프롬프트(comment_label.md)의 표와 같아야 한다.
TOPIC_NAMES = {
    "T1": "정보·내용", "T2": "편집·연출", "T3": "길이·구성",
    "T4": "출연자·진행", "T5": "썸네일·제목", "T6": "음질·화질",
    "T7": "요청·제안", "T8": "감정·응원", "T9": "기타",
    "T10": "조회수·성과 메타",
}

COLUMNS = [
    "comment_id", "video_id", "video_title", "published_at", "like_count",
    "text",
    "rule_verdict", "rule_flags",
    "sentiment", "confidence", "sarcasm_suspect",
    "topics", "topic_names",
    "prompt_version", "model",
]


def fetch(conn, prompt_version: str | None = None,
          model: str | None = None, video_id: str | None = None) -> list[dict]:
    """라벨된 댓글을 원문·규칙 판정과 함께 한 줄씩 모은다."""
    q = """
        SELECT cm.comment_id, cm.video_id, v.title AS video_title,
               cm.published_at, cm.like_count, cm.text,
               s.verdict AS rule_verdict, s.rule_flags_json,
               l.sentiment, l.sentiment_confidence, l.is_sarcasm_suspect,
               l.topics_json, l.prompt_version, l.model
        FROM comment_labels l
        JOIN comments cm ON cm.comment_id = l.comment_id
        JOIN videos   v  ON v.video_id   = cm.video_id
        LEFT JOIN comment_screens s
               ON s.comment_id = l.comment_id
        WHERE 1=1
    """
    params: list = []
    if prompt_version:
        q += " AND l.prompt_version = ?"
        params.append(prompt_version)
    if model:
        q += " AND l.model = ?"
        params.append(model)
    if video_id:
        q += " AND cm.video_id = ?"
        params.append(video_id)
    q += " ORDER BY cm.video_id, cm.like_count DESC, cm.comment_id"

    rows = []
    for r in conn.execute(q, params):
        topics = json.loads(r["topics_json"] or "[]")
        flags = json.loads(r["rule_flags_json"] or "[]")
        rows.append({
            "comment_id": r["comment_id"],
            "video_id": r["video_id"],
            "video_title": r["video_title"],
            "published_at": r["published_at"],
            "like_count": r["like_count"],
            # 원문은 그대로 둔다. 줄바꿈은 csv 모듈이 따옴표로 감싸 처리한다
            "text": r["text"],
            "rule_verdict": r["rule_verdict"] or "",
            "rule_flags": "|".join(flags),
            "sentiment": r["sentiment"],
            "confidence": r["sentiment_confidence"],
            "sarcasm_suspect": bool(r["is_sarcasm_suspect"]),
            "topics": "|".join(topics),
            "topic_names": "|".join(TOPIC_NAMES.get(t, t) for t in topics),
            "prompt_version": r["prompt_version"],
            "model": r["model"],
        })
    return rows


def to_csv(rows: list[dict], path: pathlib.Path) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: 엑셀이 한글을 깨뜨리지 않게 BOM 을 붙인다
    # newline="": csv 모듈이 줄바꿈을 직접 다루게 한다 (윈도우에서 빈 줄 방지)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)
    return path


def to_json(rows: list[dict], path: pathlib.Path, meta: dict) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(meta)
    payload["topic_codes"] = TOPIC_NAMES
    payload["count"] = len(rows)
    # JSON 에서는 topics 를 배열로 되돌린다. CSV 의 "|" 는 표 한 칸에 넣기 위한
    # 타협이고, 프로그램이 읽을 때는 배열이 맞다
    payload["comments"] = [
        {**r,
         "topics": [t for t in r["topics"].split("|") if t],
         "topic_names": [t for t in r["topic_names"].split("|") if t],
         "rule_flags": [t for t in r["rule_flags"].split("|") if t]}
        for r in rows
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path
