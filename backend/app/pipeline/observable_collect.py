"""Observable evidence collection. Separate run-scoped tables preserve legacy labels."""
import datetime as dt,json,sqlite3
from app.clients.youtube import CommentsDisabled
from app.pipeline.collect import upsert_video
from app.pipeline.eligibility import REASON_OWN_CHANNEL,SOURCE_COLLECT,SOURCE_MIGRATION,decide,extract_timestamps,timestamps_json

def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def ensure_schema(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS observation_runs(run_id TEXT PRIMARY KEY,started_at TEXT,finished_at TEXT,policy_json TEXT,status TEXT);
 CREATE TABLE IF NOT EXISTS observation_comments(run_id TEXT,comment_id TEXT,video_id TEXT,parent_id TEXT,author_id TEXT,text TEXT,published_at TEXT,fetched_at TEXT,PRIMARY KEY(run_id,comment_id));
 CREATE TABLE IF NOT EXISTS observation_threads(run_id TEXT,video_id TEXT,thread_id TEXT,top_id TEXT,api_replies INTEGER,collected_replies INTEGER,status TEXT,PRIMARY KEY(run_id,top_id));
 CREATE TABLE IF NOT EXISTS observation_collection(run_id TEXT,video_id TEXT,top_count INTEGER,status TEXT,next_page_token TEXT,captured_at TEXT,PRIMARY KEY(run_id,video_id));
 CREATE TABLE IF NOT EXISTS observable_evidence(run_id TEXT,evidence_id TEXT,payload_json TEXT,PRIMARY KEY(run_id,evidence_id));
 ''')
 _add_eligibility_columns(c)

# 분석 포함 여부 (H2·H3, docs/design/comment-eligibility.md). comments 표와 같은 열 이름.
# 옛 표에는 없으므로 붙이고, 알 수 있는 own_channel 만 videos.channel_id 비교로 채운다.
# misplaced_data 는 옛 행에 근거(API videoId)가 없어 eligible 로 남긴다.
OBS_ELIGIBILITY_COLUMNS={'author_is_channel_owner':'INTEGER','analysis_eligible':'INTEGER NOT NULL DEFAULT 1','exclusion_reason':'TEXT','exclusion_source':'TEXT','timestamps_json':"TEXT NOT NULL DEFAULT '[]'"}
def _add_eligibility_columns(c):
 have={r[1] for r in c.execute('PRAGMA table_info(observation_comments)')}
 missing=[k for k in OBS_ELIGIBILITY_COLUMNS if k not in have]
 for k in missing:c.execute(f'ALTER TABLE observation_comments ADD COLUMN {k} {OBS_ELIGIBILITY_COLUMNS[k]}')
 if 'analysis_eligible' not in missing:return
 c.execute('UPDATE observation_comments SET author_is_channel_owner=(SELECT CASE WHEN observation_comments.author_id=v.channel_id THEN 1 ELSE 0 END FROM videos v WHERE v.video_id=observation_comments.video_id) WHERE author_id IS NOT NULL')
 c.execute('UPDATE observation_comments SET analysis_eligible=0,exclusion_reason=?,exclusion_source=? WHERE author_is_channel_owner=1',(REASON_OWN_CHANNEL,SOURCE_MIGRATION))
 for r in c.execute('SELECT run_id,comment_id,text FROM observation_comments').fetchall():
  ts=extract_timestamps(r[2])
  if ts:c.execute('UPDATE observation_comments SET timestamps_json=? WHERE run_id=? AND comment_id=?',(json.dumps(ts,ensure_ascii=False),r[0],r[1]))

def save_comment(c,run,video,item,parent=None):
 """원문은 제외 여부와 무관하게 저장한다. 답글의 판정은 부모와 독립이다 —
 채널 고정 댓글(own_channel)에 달린 시청자 답글은 eligible 이고, 부모는 맥락으로 남는다."""
 s=item['snippet'];author=(s.get('authorChannelId') or {}).get('value');text=s.get('textOriginal') or s.get('textDisplay') or ''
 ch=c.execute('SELECT channel_id FROM videos WHERE video_id=?',(video,)).fetchone()
 eligible,reason,owner=decide(video,s.get('videoId'),author,ch[0] if ch else None)
 c.execute('INSERT OR REPLACE INTO observation_comments(run_id,comment_id,video_id,parent_id,author_id,text,published_at,fetched_at,author_is_channel_owner,analysis_eligible,exclusion_reason,exclusion_source,timestamps_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(run,item['id'],video,parent,author,text,s.get('publishedAt'),now(),owner,eligible,reason,SOURCE_COLLECT if reason else None,timestamps_json(text)))

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
