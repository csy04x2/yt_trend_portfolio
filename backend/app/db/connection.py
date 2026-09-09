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
    if fresh:
        print(f"[db] 새 파일 생성: {path}")
    return conn
