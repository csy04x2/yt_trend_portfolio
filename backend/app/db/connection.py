"""SQLite 연결.

WAL로 연다. 프로토타입은 단일 프로세스지만, 본 파이프라인에서 워커(쓰기)와
API(읽기)가 같이 도는 구조라 처음부터 같은 모드로 둔다.

연결은 스레드마다 따로 연다 — 아키텍처 5.3에서 워커를 전용 스레드로 내리기로
했으므로 연결을 공유하면 안 된다.
"""

from __future__ import annotations

import pathlib
import sqlite3

SCHEMA = pathlib.Path(__file__).with_name("schema.sql")


def connect(db_path: str | pathlib.Path) -> sqlite3.Connection:
    path = pathlib.Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists()

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    # schema.sql은 IF NOT EXISTS라 매번 돌려도 안전하다
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    added = _add_missing_columns(conn)
    if ("comments", "analysis_eligible") in added:
        # 옛 DB 에 분석 포함 여부 열을 막 붙였다. 알 수 있는 것만 채운다 —
        # own_channel 은 channel_id 비교로 정해지고, misplaced_data 는 옛 행에
        # 근거가 없어 eligible 로 남는다. 한 번만 돈다.
        from app.pipeline.eligibility import backfill_comments

        got = backfill_comments(conn)
        print(f"[db] 댓글 분석 포함 여부 채움: {got}")
    if fresh:
        print(f"[db] 새 파일 생성: {path}")
    return conn


# 나중에 추가된 열. CREATE TABLE IF NOT EXISTS 는 이미 있는 표를 건드리지
# 않으므로, 먼저 만든 DB 에는 이 열들이 없다. 프로토타입 단계라 번호 매긴
# 마이그레이션 대신 "없으면 붙인다"로 둔다.
LATE_COLUMNS = {
    "videos": {
        "description_clean": "TEXT",     # 2단계 정규화가 채운다
    },
    "video_taxonomies": {
        # 유형 축. topic(판단) 과 segment(채널 재생목록) 를 나란히 둔다
        "axis": "TEXT NOT NULL DEFAULT 'topic'",
        # 체계의 사람이 부르는 이름 ("woni-topics-v1" 같은 것).
        # prompt_version 과 다르다 — 저건 이 체계를 만든 프롬프트의 버전이다.
        # 둘을 한 칸에 섞었더니 대조기가 재현 불가로 잡았고, 그게 옳았다.
        "label": "TEXT NOT NULL DEFAULT ''",
    },
    "comment_screens": {
        # 모델이 왜 버렸는지 한 줄. rule_flags_json 은 규칙 표시의 자리라
        # 문장을 넣을 수 없다 — 규칙 행은 이 열을 NULL 로 둔다
        "reason": "TEXT",
    },
    "video_metrics": {
        # 댓글율 배수. view_multiple 과 같은 비교군을 쓴다.
        # 비교군이 모자라면 NULL 이고 이유는 _basis 에 남는다
        "comment_rate_multiple": "REAL",
        "comment_rate_multiple_basis": "TEXT",
    },
    "comments": {
        # 분석 포함 여부 (H2·H3). 기본값은 "포함·사유 없음"이다 — 옛 행을
        # 근거 없이 빼지 않는다. 알 수 있는 것은 connect() 가 채운다
        "parent_id": "TEXT",
        "author_is_channel_owner": "INTEGER",
        "analysis_eligible": "INTEGER NOT NULL DEFAULT 1",
        "exclusion_reason": "TEXT",
        "exclusion_source": "TEXT",
        "timestamps_json": "TEXT NOT NULL DEFAULT '[]'",
    },
}


def _add_missing_columns(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """없는 열을 붙이고, 붙인 (표, 열) 을 돌려준다."""
    added: set[tuple[str, str]] = set()
    for table, cols in LATE_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                print(f"[db] 열 추가: {table}.{name}")
                added.add((table, name))
    return added
