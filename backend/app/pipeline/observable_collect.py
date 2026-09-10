"""Observable evidence collection. Separate run-scoped tables preserve legacy labels."""
import datetime as dt,json,sqlite3
from app.clients.youtube import CommentsDisabled
from app.pipeline.collect import upsert_video

def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def ensure_schema(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS observation_runs(run_id TEXT PRIMARY KEY,started_at TEXT,finished_at TEXT,policy_json TEXT,status TEXT);
 CREATE TABLE IF NOT EXISTS observation_comments(run_id TEXT,comment_id TEXT,video_id TEXT,parent_id TEXT,author_id TEXT,text TEXT,published_at TEXT,fetched_at TEXT,PRIMARY KEY(run_id,comment_id));
 CREATE TABLE IF NOT EXISTS observation_threads(run_id TEXT,video_id TEXT,thread_id TEXT,top_id TEXT,api_replies INTEGER,collected_replies INTEGER,status TEXT,PRIMARY KEY(run_id,top_id));
 CREATE TABLE IF NOT EXISTS observation_collection(run_id TEXT,video_id TEXT,top_count INTEGER,status TEXT,next_page_token TEXT,captured_at TEXT,PRIMARY KEY(run_id,video_id));
 CREATE TABLE IF NOT EXISTS observable_evidence(run_id TEXT,evidence_id TEXT,payload_json TEXT,PRIMARY KEY(run_id,evidence_id));
 ''')

def save_comment(c,run,video,item,parent=None):
 s=item['snippet'];c.execute('INSERT OR REPLACE INTO observation_comments VALUES(?,?,?,?,?,?,?,?)',(run,item['id'],video,parent,(s.get('authorChannelId') or {}).get('value'),s.get('textOriginal') or s.get('textDisplay') or '',s.get('publishedAt'),now()))

def collect_sample(c,yt,run,video,reply_pages=2):
 """One newest page/video; fetch replies to each sampled thread up to bounded pages."""
 c.execute('INSERT OR REPLACE INTO observation_collection VALUES(?,?,0,?,NULL,?)',(run,video,'running',now()))
 try:
  body=yt._get('commentThreads',part='snippet',videoId=video,order='time',maxResults=100,textFormat='plainText')
  items=body.get('items',[])
  for it in items:
   sn=it['snippet'];top=sn['topLevelComment'];save_comment(c,run,video,top);expected=sn.get('totalReplyCount');token=None;count=0;state='complete'
   c.execute('INSERT OR REPLACE INTO observation_threads VALUES(?,?,?,?,?,?,?)',(run,video,it['id'],top['id'],expected,0,'running'))
   if expected is None:state='unknown_reply_count'
   elif expected:
    for page in range(reply_pages):
     rb=yt._get('comments',part='snippet',parentId=top['id'],maxResults=100,textFormat='plainText',**({'pageToken':token} if token else {}))
     for reply in rb.get('items',[]):save_comment(c,run,video,reply,top['id'])
     token=rb.get('nextPageToken')
     if not token:break
    if token:state='capped'
   count=c.execute('SELECT count(*) FROM observation_comments WHERE run_id=? AND parent_id=?',(run,top['id'])).fetchone()[0]
   if state=='complete' and count!=expected:state='count_changed'
   c.execute('UPDATE observation_threads SET collected_replies=?,status=? WHERE run_id=? AND top_id=?',(count,state,run,top['id']))
  c.execute('UPDATE observation_collection SET top_count=?,status=?,next_page_token=?,captured_at=? WHERE run_id=? AND video_id=?',(len(items),'capped' if body.get('nextPageToken') else 'complete',body.get('nextPageToken'),now(),run,video))
 except CommentsDisabled:
  c.execute("UPDATE observation_collection SET status='disabled' WHERE run_id=? AND video_id=?",(run,video))
 except Exception as e:
  c.execute('UPDATE observation_collection SET status=? WHERE run_id=? AND video_id=?',('error:'+type(e).__name__,run,video));raise

def sample_ids(videos):
 """Two chronologically spaced videos per publication month / length stratum."""
 groups={}
 for v in sorted(videos,key=lambda x:x['published_at']):
  groups.setdefault((v['published_at'][:7],v['length_axis']),[]).append(v['video_id'])
 return sorted({ids[i] for ids in groups.values() for i in {len(ids)//3,2*len(ids)//3}})
