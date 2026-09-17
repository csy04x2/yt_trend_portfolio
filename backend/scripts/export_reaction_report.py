"""DB 의 Reaction 판정 → evidence JSON 의 `reaction_report` 블록 (+ 선택: 대시보드 다시 그리기).

DB 는 **읽기 전용**으로 연다 (sqlite `mode=ro`). 표를 만들거나 열을 붙이지 않는다 —
`connect()` 가 하는 스키마 보정도 돌리지 않는다. 판정이 없으면 숫자 없이 빈 상태 블록을 쓴다.

    python scripts/export_reaction_report.py --db ./data/chim.db
    python scripts/export_reaction_report.py --db ./data/chim.db --render
    python scripts/export_reaction_report.py --db ./data/chim.db \
        --prompt-version reaction-v1 --model claude-code-offline \
        --reference-manifest <동결 manifest.json>

블록에는 댓글 원문·rationale·comment_id 가 들어가지 않는다 (수와 비율, 유형 이름만).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.interpret.reaction_report import BLOCK_KEY, block_from_db  # noqa: E402


def open_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True, help="SQLite 파일 (읽기 전용으로 연다)")
    p.add_argument("--evidence", default=str(ROOT / "docs/prototype/chim-evidence.json"))
    p.add_argument("--channel-id", help="DB 에 채널이 여럿일 때")
    p.add_argument("--prompt-version")
    p.add_argument("--model")
    p.add_argument("--reference-manifest", help="동결 reference manifest. 주면 성과 층에 canonical 조회 배수를 쓴다")
    p.add_argument("--render", action="store_true", help="scripts/render_prototype.py 로 대시보드를 다시 그린다")
    a = p.parse_args(argv)

    manifest = None
    if a.reference_manifest:
        manifest = json.loads(Path(a.reference_manifest).read_text(encoding="utf-8"))
    db = Path(a.db)
    conn = open_readonly(db)
    try:
        block = block_from_db(conn, channel_id=a.channel_id, prompt_version=a.prompt_version,
                              model=a.model, manifest=manifest, db_name=db.name)
    finally:
        conn.close()

    ev = Path(a.evidence)
    data = json.loads(ev.read_text(encoding="utf-8"))
    data[BLOCK_KEY] = block
    # 기존 파일과 같은 직렬화(indent 2, 끝 줄바꿈) — 다른 키의 diff 를 만들지 않는다
    ev.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                  encoding="utf-8")
    src = block["source"]
    print(f"[reaction_report] {block['state']} · 판정 {src['n_labeled_comments']}건 · "
          f"({src.get('prompt_version')}, {src.get('model')}) · 문장 "
          f"{len(block['interpretation']['sentences'])}개 · {block['validation_status']} → {ev}")
    if a.render:
        subprocess.run([sys.executable, str(BACKEND / "scripts/render_prototype.py"), str(ev)], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
