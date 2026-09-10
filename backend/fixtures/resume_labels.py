"""Manual semantic labels by Codex; tokens encode sentiment/confidence/topics only.
No keyword classifier: each token was assigned after reading the batch text.
"""
import json,pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from app.pipeline.offline_llm import validate_result
ROOT=pathlib.Path(__file__).resolve().parents[1]/'data/batches'
def write(folder,batch,tokens):
    p=ROOT/folder/'comments'/f'{batch}.result.json'
    if p.exists(): raise RuntimeError(f'Refusing overwrite: {p}')
    rows=[]
    for i,token in enumerate(tokens.split(),1):
        code,topics=token.split(':'); sarcasm='!' in code;code=code.replace('!','')
        rows.append(dict(idx=i,sentiment={'P':'positive','N':'negative','U':'neutral'}[code[0]],confidence=float(code[1:]),sarcasm_suspect=sarcasm,topics=['T'+t for t in topics.split(',')]))
    payload=dict(batch=batch,prompt_version='v2',model='codex-offline',results=rows)
    mapping=json.loads(p.with_name(batch+'.map.json').read_text(encoding='utf-8-sig'))['map']
    validate_result(payload,mapping)
    p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(batch,len(rows))
