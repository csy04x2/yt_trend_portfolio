"""Build the local Chimchakman prototype from current SQLite observations."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db.connection import connect
from app.pipeline.observable import build
root=Path(__file__).resolve().parents[2]
c=connect(root/'backend/data/chim.db');d=build(c);c.close()
raw=json.dumps(d,ensure_ascii=False,allow_nan=False)
(root/'docs/prototype/chim-evidence.json').write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
template=(root/'docs/prototype/chim-prototype.template.html').read_text(encoding='utf-8-sig')
(root/'docs/prototype/report-prototype.html').write_text(template.replace('__DATA__',raw.replace('<','\\u003c')),encoding='utf-8')
print(json.dumps(d['summary'],ensure_ascii=False));print('Built docs/prototype/report-prototype.html')
