"""Resume validated offline labels without paid API calls; preserve source provenance."""
import sys,json,sqlite3,hashlib,datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db.connection import connect
from app.pipeline import offline_llm as ol, classify_videos as cv, aggregate
ROOT=Path(__file__).resolve().parents[1]
def main():
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 out=ROOT/'exports'/('resumed-analysis-'+stamp);out.mkdir(parents=True)
 all_summary=[]
 for name,prefix in [('chim','chimc'),('carden','carden')]:
  c=connect(ROOT/'data'/f'{name}.db');backup=ROOT/'data'/'backups'/f'{name}-{stamp}.db';backup.parent.mkdir(exist_ok=True)
  b=sqlite3.connect(backup);c.backup(b);b.close()
  folder=ROOT/'data'/'batches'/name; pending=[];manifest=[];seen=set()
  for i in range(1,21):
   p=folder/'comments'/f'{prefix}_{i:03d}.result.json';payload=json.loads(p.read_text(encoding='utf-8'));mp=json.loads(p.with_name(p.name.replace('.result','.map')).read_text(encoding='utf-8'))['map']
   assert payload['model'] in ('claude-code-offline','codex-offline') and payload['prompt_version']=='v2'
   rows=ol.validate_result(payload,mp);assert len(rows)==20
   ids={r['comment_id'] for r in rows};assert not seen&ids;seen|=ids
   pending.append((payload,rows));manifest.append({'file':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'model':payload['model'],'count':len(rows)})
  assert seen=={r[0] for r in c.execute('select comment_id from comments')}
  ch=c.execute('select channel_id,title from channels').fetchone()
  title=json.loads((folder/f'{name}_lab.result.json').read_text(encoding='utf-8'));mp=json.loads((folder/f'{name}_lab.map.json').read_text(encoding='utf-8'))['map'];tr=cv.validate(title,mp)
  tid=c.execute("select taxonomy_id from video_taxonomies where axis='topic' and is_active=1").fetchone()[0]
  c.execute('BEGIN')
  try:
   for payload,rows in pending:assert ol.save_labels(c,rows,payload['prompt_version'],payload['model'])==len(rows)
   for r in tr:
    cur=c.execute('update video_type_labels set confidence=? where taxonomy_id=? and video_id=? and type_code=?',(r.get('confidence'),tid,r['video_id'],r['type_code']));assert cur.rowcount==1
   reports=aggregate.run(c,ch[0],'resume-'+stamp,label_sources=[('v2','claude-code-offline'),('v2','codex-offline')])
   c.execute('COMMIT')
  except BaseException:c.execute('ROLLBACK');raise
  labels=[dict(r) for r in c.execute('select c.video_id,l.* from comment_labels l join comments c using(comment_id)')]
  videos=[dict(r) for r in c.execute('select v.video_id,v.title,v.length_axis,l.sentiment,l.model,count(*) as n from comment_labels l join comments c using(comment_id) join videos v using(video_id) group by v.video_id,l.sentiment,l.model')]
  summary={'channel':ch[1],'video_count':c.execute('select count(*) from videos').fetchone()[0],'labeled_comments':len(labels),'sampled_videos':len({r['video_id'] for r in labels}),'breakdown':videos,'reports':reports,'inputs':manifest}
  (out/f'{name}-labels.json').write_text(json.dumps(labels,ensure_ascii=False,indent=2),encoding='utf-8')
  (out/f'{name}-report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');all_summary.append(summary);c.close()
 lines=['# 침착맨·카더가든 분석 재개 결과',f'생성 UTC: {stamp}','','기존 감성·주제 v2 분석 완료. R1–R8 Reaction 분석은 별도이며 이번 결과에 포함하지 않음.','', '각 채널 300개 영상 중 댓글 표본은 2개 영상(0.67%), 영상당 200개. 댓글 전수·채널 대표 표본이 아니므로 채널 전체 반응으로 일반화할 수 없다.','Claude/Codex 판정 출처를 보존했다. 특히 침착맨은 영상별 판정 모델이 달라 영상 간 감성 차이에 모델 차이가 섞인다. 인간 정답 검증은 수행되지 않았다.','중립은 무반응이 아니다. 농담이 중립으로 분류될 수 있다. 채널 공지·출연자 댓글이 표본에 포함되어 있다.','제목 주제는 보조 분석이며 저확신도 유형의 결론을 보류했다. 재생목록에는 연간 모음이 있어 모든 목록을 실제 코너로 해석하면 안 된다.','']
 for s in all_summary:
  lines += [f"## {s['channel']}",f"영상 {s['video_count']}개 / 댓글 판정 {s['labeled_comments']}개 / 댓글 표본 영상 {s['sampled_videos']}개",'', '| 영상 | 길이축 | 감성 | 판정 출처 | 개수 |','|---|---|---|---|---|']
  for r in s['breakdown']:lines.append(f"| {r['title']} | {r['length_axis']} | {r['sentiment']} | {r['model']} | {r['n']} |")
  lines+=['', '세부 집계와 입력 해시는 동봉한 JSON에서 확인할 수 있다.','']
 (out/'README.md').write_text('\n'.join(lines),encoding='utf-8')
 print(out)
 for s in all_summary:print(json.dumps({k:s[k] for k in ['channel','video_count','labeled_comments','sampled_videos','breakdown']},ensure_ascii=False))
if __name__=='__main__':main()
