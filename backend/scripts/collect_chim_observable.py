import sys,json,sqlite3,datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import config
from app.clients.youtube import YouTubeClient
from app.db.connection import connect
from app.pipeline.observable_collect import ensure_schema,collect_sample,sample_ids,now
from app.pipeline.collect import upsert_video
root=Path(__file__).resolve().parents[1];config.load_env();c=connect(root/'data/chim.db');run='observable-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
b=sqlite3.connect(root/'data/backups'/f'chim-{run}.db');c.backup(b);b.close();ensure_schema(c)
vs=[dict(r) for r in c.execute('select * from videos order by published_at')];ids=sample_ids(vs)
ids=sorted(set(ids)|{'3nAjcgsig_A','Yln0zfwJcZY'})
c.execute('INSERT INTO observation_runs VALUES(?,?,NULL,?,?)',(run,now(),json.dumps({'sampling':'two chronological quantiles/month/length plus legacy 2','video_ids':ids,'top_order':'time','top_limit':100,'reply_page_limit':2}), 'running'))
yt=YouTubeClient(config.require('YOUTUBE_API_KEY','기존 키 설정 필요'),daily_quota=600)
try:
 for item in yt.fetch_videos([v['video_id'] for v in vs]):upsert_video(c,item,vs[0]['channel_id'],run)
 print('Snapshots refreshed; sample videos',len(ids),flush=True)
 for i,vid in enumerate(ids):
  collect_sample(c,yt,run,vid);print(f'{i+1}/{len(ids)} {vid} units={yt.units_used}',flush=True)
 c.execute("UPDATE observation_runs SET status='complete',finished_at=? WHERE run_id=?",(now(),run))
except Exception as e:
 c.execute("UPDATE observation_runs SET status=?,finished_at=? WHERE run_id=?",('error:'+type(e).__name__,now(),run));print(type(e).__name__,flush=True)
finally:
 print('run',run,'units',yt.units_used,flush=True);c.close()
