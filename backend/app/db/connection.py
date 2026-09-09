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
    _add_missing_columns(conn)
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
    "video_metrics": {
        # 댓글율 배수. view_multiple 과 같은 비교군을 쓴다.
        # 비교군이 모자라면 NULL 이고 이유는 _basis 에 남는다
        "comment_rate_multiple": "REAL",
        "comment_rate_multiple_basis": "TEXT",
    },
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, cols in LATE_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                print(f"[db] 열 추가: {table}.{name}")
