"""Explicit JSON content input or production SQLite, never a writing loader."""
import json
import sqlite3
from pathlib import Path

from .blind import CONTENT_FIELDS, validate_fields, validate_rows


def load_content(path):
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("Expected JSON array of content objects")
    else:
        # No app.db.connection import: it executes schema and migrations.
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
            fields = [f for f in CONTENT_FIELDS if f in cols]
            validate_fields(fields)
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                'SELECT ' + ', '.join('"' + f + '"' for f in fields)
                + ' FROM videos ORDER BY video_id')]
        finally:
            conn.close()
    validate_rows(rows)
    return sorted(rows, key=lambda r: r["video_id"])
