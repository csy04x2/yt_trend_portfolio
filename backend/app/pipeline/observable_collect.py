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
 -- 표본 정책(app.pipeline.comment_sampling)으로 돌린 실행만 채운다. 입력 영상 전부가 한 줄씩(선정·미선정·제외).
 -- completeness: complete / capped / not_sampled / disabled / error:<예외> / pending
 CREATE TABLE IF NOT EXISTS observation_sampling(run_id TEXT,video_id TEXT,split TEXT,stratum TEXT,tier TEXT,mode TEXT,decision TEXT,reason TEXT,inclusion_prob REAL,rank_key TEXT,ordering TEXT,collect_cap INTEGER,top_pages INTEGER,reply_threads INTEGER,reply_pages INTEGER,label_cap INTEGER,policy_name TEXT,policy_version TEXT,seed INTEGER,decided_at TEXT,completeness TEXT,collected_at TEXT,PRIMARY KEY(run_id,video_id));
 ''')

def save_comment(c,run,video,item,parent=None):
 s=item['snippet'];c.execute('INSERT OR REPLACE INTO observation_comments VALUES(?,?,?,?,?,?,?,?)',(run,item['id'],video,parent,(s.get('authorChannelId') or {}).get('value'),s.get('textOriginal') or s.get('textDisplay') or '',s.get('publishedAt'),now()))

def collect_sample(c,yt,run,video,reply_pages=2,*,top_pages=1,order='time',max_reply_threads=None):
 """One newest page/video; fetch replies to each sampled thread up to bounded pages.

 기본값(top_pages=1, order='time', max_reply_threads=None)은 예전 동작 그대로다.
 표본 정책은 top_pages(원댓글 페이지 상한)와 max_reply_threads(답글을 받을 thread 수 상한,
 수집 순서 앞에서부터)를 넘긴다. 상한 밖이거나 reply_pages<=0 인 thread 는 답글을 받지 않고
 status='replies_not_fetched' 로 남긴다. API totalReplyCount(api_replies)는 그래도 기록된다."""
 c.execute('INSERT OR REPLACE INTO observation_collection VALUES(?,?,0,?,NULL,?)',(run,video,'running',now()))
 try:
  items=[];body={};page_token=None
  for _ in range(max(1,top_pages)):
   body=yt._get('commentThreads',part='snippet',videoId=video,order=order,maxResults=100,textFormat='plainText',**({'pageToken':page_token} if page_token else {}))
   items.extend(body.get('items',[]));page_token=body.get('nextPageToken')
   if not page_token:break
  fetched_threads=0
  for it in items:
   sn=it['snippet'];top=sn['topLevelComment'];save_comment(c,run,video,top);expected=sn.get('totalReplyCount');token=None;count=0;state='complete'
   c.execute('INSERT OR REPLACE INTO observation_threads VALUES(?,?,?,?,?,?,?)',(run,video,it['id'],top['id'],expected,0,'running'))
   if expected is None:state='unknown_reply_count'
   elif expected and (reply_pages<=0 or (max_reply_threads is not None and fetched_threads>=max_reply_threads)):state='replies_not_fetched'
   elif expected:
    fetched_threads+=1
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

# ---------------------------------------------------------------------------
# 표본 정책 경로 (선택). 위 sample_ids/collect_sample 기본 경로는 바뀌지 않는다.
# 설계: docs/design/comment-sampling-policy.md
# ---------------------------------------------------------------------------

TERMINAL=('complete','capped','disabled')

def record_plan(c,run,plan):
 """SamplingPlan 의 결정을 영상마다 observation_sampling 에 남기고, 실행 행에 정책을 적는다.

 이미 기록된 영상은 덮어쓰지 않는다 — 재개 시 결정이 바뀌면 안 된다.
 선정되지 않은 영상의 completeness 는 처음부터 not_sampled 다."""
 from app.pipeline.comment_sampling import POLICY_VERSION,SELECTED
 p=plan.policy;t=now()
 c.execute('INSERT OR IGNORE INTO observation_runs VALUES(?,?,NULL,?,?)',(run,t,json.dumps({'sampling':'comment-sampling-policy','policy':json.loads(p.to_json()),'cutpoints':plan.cutpoints,'warnings':plan.warnings},ensure_ascii=False,sort_keys=True),'running'))
 for d in plan.decisions:
  c.execute('INSERT OR IGNORE INTO observation_sampling VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(run,d['video_id'],d['split'],d['stratum'],d['tier'],d['mode'],d['decision'],d['reason'],d['inclusion_prob'],d['rank_key'],d['order'],d['collect_cap'],d['top_pages'],d['reply_threads'],d['reply_pages'],d['label_cap'],p.name,POLICY_VERSION,p.seed,t,'pending' if d['decision']==SELECTED else 'not_sampled',None))

def collect_planned(c,yt,run,plan,log=print):
 """계획에서 선정된 영상만 정책의 상한으로 받는다. 재개 가능.

 같은 run 에서 이미 complete/capped/disabled 인 영상은 건너뛴다. 오류(할당량 소진 포함)가
 나면 그 영상에 error 를 남기고 멈춘다 — 받은 것은 그대로 두고, 다시 부르면 이어서 받는다.
 로그에는 영상 ID·상태·유닛만 찍는다(댓글 원문은 찍지 않는다)."""
 record_plan(c,run,plan)
 chosen=plan.selected();done=0
 try:
  for i,d in enumerate(chosen):
   vid=d['video_id'];row=c.execute('SELECT status FROM observation_collection WHERE run_id=? AND video_id=?',(run,vid)).fetchone()
   if row is None or row[0] not in TERMINAL:
    try:
     collect_sample(c,yt,run,vid,d['reply_pages'],top_pages=d['top_pages'],order=d['order'],max_reply_threads=d['reply_threads'])
    finally:
     sync_completeness(c,run,vid)
   done+=1;log(f"{i+1}/{len(chosen)} {vid} units={getattr(yt,'units_used','?')}")
  c.execute("UPDATE observation_runs SET status='complete',finished_at=? WHERE run_id=?",(now(),run))
 except Exception as e:
  c.execute('UPDATE observation_runs SET status=?,finished_at=? WHERE run_id=?',('error:'+type(e).__name__,now(),run));raise
 return done

def sync_completeness(c,run,video):
 """observation_collection 의 상태를 observation_sampling.completeness 로 옮긴다."""
 row=c.execute('SELECT status,captured_at FROM observation_collection WHERE run_id=? AND video_id=?',(run,video)).fetchone()
 if row is None:return
 status='pending' if row[0]=='running' else row[0]
 c.execute('UPDATE observation_sampling SET completeness=?,collected_at=? WHERE run_id=? AND video_id=?',(status,row[1],run,video))
