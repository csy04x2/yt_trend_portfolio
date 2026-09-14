"""evidence JSON + 템플릿 → 대시보드 HTML. DB가 없어도 돈다 (build_chim_prototype.py는 DB에서 evidence를 만든다)."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
ev = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "docs/prototype/chim-evidence.json"
tpl = root / "docs/prototype/chim-prototype.template.html"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "docs/prototype/report-prototype.html"
d = json.load(open(ev, encoding="utf-8"))
raw = json.dumps(d, ensure_ascii=False, allow_nan=False)
out.write_text(tpl.read_text(encoding="utf-8-sig").replace("__DATA__", raw.replace("<", "\\u003c")), encoding="utf-8")
print(f"rendered {out} ({out.stat().st_size // 1024} KB)")
