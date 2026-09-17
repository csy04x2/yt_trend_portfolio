"""Video-level observed associations with explicit provenance and missingness."""
import datetime as dt,json,math,re,statistics as st,random
from collections import Counter,defaultdict
from app.pipeline.observable_collect import ensure_schema
VERSION='observable-v1'
def date(s):return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
def ratio(a,b):return a/b if a is not None and b is not None and b>0 else None
def median(xs):return st.median(xs) if xs else None
def timestamps(text,duration):
 found=set()
 for m in re.finditer(r'(?<![\d:])(\d{1,3}:\d{2}(?::\d{2})?)(?![\d:])',text):
  parts=list(map(int,m[1].split(':')))
  if parts[-1]>=60 or (len(parts)==3 and parts[-2]>=60):continue
  sec=sum(v*60**i for i,v in enumerate(reversed(parts)))
  if 0<=sec<duration:found.add(sec)
 return sorted(found)
def clusters(comments,duration,window=30):
 buckets=defaultdict(set);examples=defaultdict(list);n=0
 for c in comments:
  ts=timestamps(c['text'],duration)
  if ts:n+=1
  for b in {t//window for t in ts}:
   buckets[b].add(c['comment_id'])
   if len(examples[b])<3:examples[b].append({'text':c['text'][:350],'comment_id':c['comment_id']})
 return {'timestamp_comments':n,'window_seconds':window,'bins':[{'start':b*window,'progress':b*window/duration,'n':len(ids),'examples':examples[b]} for b,ids in sorted(buckets.items())]}
def compare(video,videos):
 age=video['age_days'];tolerance=max(2,age*.2)
 peers=[v for v in videos if v['video_id']!=video['video_id'] and v['length_axis']==video['length_axis'] and abs(v['age_days']-age)<=tolerance and not v['is_live'] and v['view_count'] is not None]
 base=median([p['view_count'] for p in peers]) if len(peers)>=5 else None
 result={'comparison_n':len(peers),'comparison_ids':[p['video_id'] for p in peers],'age_tolerance_days':tolerance,'baseline_views':base,'view_multiple':ratio(video['view_count'],base),'excess_views':video['view_count']-base if base is not None and video['view_count'] is not None else None,'baseline_status':'available' if base and not video['is_live'] else 'insufficient_peers_or_zero','expected_kind':'cross_sectional_peer_median_not_prediction'}
 if video['is_live']:result.update(baseline_views=None,view_multiple=None,excess_views=None,baseline_status='live_excluded')
 for key in ['like_rate','comment_rate']:
  vals=[p[key] for p in peers if p[key] is not None];b=median(vals) if len(vals)>=5 else None
  result['baseline_'+key]=b;result[key+'_multiple']=ratio(video[key],b);result[key+'_comparison_n']=len(vals)
 return result

def effect(a,b):
 if len(a)<5 or len(b)<5:return None
 delta=st.median(a)-st.median(b);loo=[st.median(a[:i]+a[i+1:])-st.median(b) for i in range(len(a))]+[st.median(a)-st.median(b[:i]+b[i+1:]) for i in range(len(b))]
 rng=random.Random(17);boot=sorted(st.median(rng.choices(a,k=len(a)))-st.median(rng.choices(b,k=len(b))) for _ in range(400))
 return {'estimate':delta,'unit':'view_multiple_difference','video_n':len(a),'comparison_n':len(b),'variance_target':st.variance(a),'variance_comparison':st.variance(b),'bootstrap_interval':[boot[10],boot[389]],'leave_one_out_range':[min(loo),max(loo)],'outlier_dependency':max(abs(x-delta) for x in loo)/abs(delta) if delta else None,'status':'exploratory_association','interval_note':'영상 단위 bootstrap 400회; 비교군 공유·다중 비교를 보정한 검정 아님'}
def reaction_lift(target,peers):
 """Inputs must have one identical taxonomy/protocol/source tuple; proportions per video."""
 if not target or not peers:return {'status':'missing_labels','estimate':None}
 if len({tuple(v['provenance']) for v in target+peers})!=1:raise ValueError('Reaction provenance must match')
 return {'status':'exploratory_association','estimate':100*(st.mean(v['share'] for v in target)-st.mean(v['share'] for v in peers)),'unit':'percentage_points','video_n':len(target),'comparison_n':len(peers)}

def build(c):
 ensure_schema(c);run=c.execute('select * from observation_runs order by started_at desc limit 1').fetchone();rid=run['run_id']
 videos=[]
 for row in c.execute('select * from videos order by published_at'):
  v=dict(row);snaps=[dict(x) for x in c.execute('select * from video_stats_snapshots where video_id=? order by captured_at,snapshot_id',(v['video_id'],))];s=snaps[-1]
  v={k:v[k] for k in ['video_id','title','length_axis','duration_sec','published_at','is_live','live_evidence']};v.update({k:s[k] for k in ['view_count','like_count','comment_count','captured_at']});v['age_days']=max(0,(date(s['captured_at'])-date(v['published_at'])).total_seconds()/86400)
  v['like_rate']=ratio(v['like_count'],v['view_count']);v['comment_rate']=ratio(v['comment_count'],v['view_count']);v['snapshots']=[{k:x[k] for k in ['captured_at','view_count','like_count','comment_count']} for x in snaps]
  local=date(v['published_at']).astimezone(dt.timezone(dt.timedelta(hours=9)));v['weekday']=local.weekday();v['hour']=local.hour;v['month']=local.strftime('%Y-%m');v['gap_hours']=(date(v['published_at'])-date(videos[-1]['published_at'])).total_seconds()/3600 if videos else None
  v['corners']=[]
  for tax in c.execute("select * from video_taxonomies where axis='segment' and is_active=1"):
   names=json.loads(tax['types_json'])
   for lab in c.execute('select type_code from video_type_labels where video_id=? and taxonomy_id=?',(v['video_id'],tax['taxonomy_id'])):
    name=names.get(lab[0],lab[0])
    if not re.search(r'정주행|Shorts|쇼츠|20\d\d년',name,re.I):v['corners'].append(name)
  videos.append(v)
 for v in videos:v.update(compare(v,videos))
 all_comments=[dict(x) for x in c.execute('select * from observation_comments where run_id=?',(rid,))];author_videos=defaultdict(set)
 # 시청자 행동은 분석 대상 댓글만 센다 (analysis_eligible, docs/design/comment-eligibility.md). 수집 커버리지는 raw 전체로 센다
 audience=[x for x in all_comments if x.get('analysis_eligible',1)]
 for x in audience:
  if x['author_id']:author_videos[x['author_id']].add(x['video_id'])
 for v in videos:
  vid=v['video_id'];rows=[x for x in all_comments if x['video_id']==vid];aud=[x for x in rows if x.get('analysis_eligible',1)];authors={x['author_id'] for x in aud if x['author_id']};collection=c.execute('select * from observation_collection where run_id=? and video_id=?',(rid,vid)).fetchone();threads=[dict(x) for x in c.execute('select * from observation_threads where run_id=? and video_id=?',(rid,vid))]
  v['collection_status']=collection['status'] if collection else 'not_sampled';v['collected_comments']=len(rows);v['eligible_comments']=len(aud);v['excluded_comments']=dict(Counter(x['exclusion_reason'] for x in rows if not x.get('analysis_eligible',1)));v['unique_commenters']=len(authors) if collection else None;v['author_missing_rate']=ratio(sum(x['author_id'] is None for x in rows),len(rows));v['observed_repeat_share']=ratio(sum(len(author_videos[a])>1 for a in authors),len(authors));v['participant_breadth']=ratio(len(authors),v['view_count']) if collection else None
  v['collection_to_api_ratio']=ratio(len(rows),v['comment_count']) if collection else None
  v['threads']=len(threads) if collection else None;v['replies_collected']=sum(t['collected_replies'] for t in threads) if collection else None;v['api_replies_sampled_threads']=sum(t['api_replies'] for t in threads) if threads and all(t['api_replies'] is not None for t in threads) else None;v['reply_rate']=ratio(v['replies_collected'],v['threads']);v['reply_incomplete_threads']=sum(t['status']!='complete' for t in threads);v['reply_fetch_coverage']=ratio(v['replies_collected'],v['api_replies_sampled_threads']);v['max_thread_size']=max((1+t['collected_replies'] for t in threads),default=None)
  v['timestamp']=clusters(aud,v['duration_sec']);v['timestamp']['sensitivity_60s']=max((b['n'] for b in clusters(aud,v['duration_sec'],60)['bins']),default=0)
  legacy=[dict(x) for x in c.execute('select l.* from comment_labels l join comments co using(comment_id) where co.video_id=? and co.analysis_eligible=1',(vid,))];v['sentiment']=dict(Counter(x['sentiment'] for x in legacy));v['sentiment_sources']=dict(Counter(x['model'] for x in legacy));v['sentiment_n']=len(legacy)
  v['reaction']={'status':'not_labeled_for_this_channel','lift':None}
 evidence=[]
 for axis in ['shorts','standard','long']:
  pop=[v for v in videos if v['length_axis']==axis and v['view_multiple'] is not None]
  features=[('주말 업로드',lambda v:v['weekday']>=5),('업로드 간격 24시간 이상',lambda v:v['gap_hours']>=24 if v['gap_hours'] is not None else None)]
  for name in sorted({n for v in pop for n in v['corners']}):features.append((name,lambda v,n=name: n in v['corners'] if v['corners'] else None))
  for name,pred in features:
   a=[v for v in pop if pred(v) is True];b=[v for v in pop if pred(v) is False];e=effect([v['view_multiple'] for v in a],[v['view_multiple'] for v in b])
   if e:
    e.update(evidence_id=f'feature-{len(evidence)+1}',feature=name,length_axis=axis,target_ids=[v['video_id'] for v in a],comparison_ids=[v['video_id'] for v in b],outcome='view_multiple',feature_missing_n=sum(pred(v) is None for v in pop),reaction_delta=None,time_effect=[])
    for month in sorted({v['month'] for v in pop}):
     z=effect([v['view_multiple'] for v in a if v['month']==month],[v['view_multiple'] for v in b if v['month']==month])
     if z:e['time_effect'].append({'month':month,**z})
    e['allowed_claim']='탐색적 관계. 인과·미래 성과 보장 불가';evidence.append(e)
 for e in evidence:c.execute('INSERT OR REPLACE INTO observable_evidence VALUES(?,?,?)',(rid,e['evidence_id'],json.dumps(e,ensure_ascii=False)))
 monthly=[]
 for month in sorted({v['month'] for v in videos}):
  for axis in ['shorts','standard','long']:
   vs=[v for v in videos if v['month']==month and v['length_axis']==axis];vals=[v['view_multiple'] for v in vs if v['view_multiple'] is not None]
   monthly.append({'month':month,'length_axis':axis,'n':len(vs),'comparable_n':len(vals),'median_multiple':median(vals)})
 return {'version':VERSION,'run_id':rid,'run_status':run['status'],'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'channel':'침착맨','videos':videos,'evidence':evidence,'monthly':monthly,'sampling':json.loads(run['policy_json']),'summary':{'video_n':len(videos),'sample_video_n':sum(v['collection_status']!='not_sampled' for v in videos),'comment_n':len(all_comments),'eligible_comment_n':len(audience),'unique_authors':len(author_videos),'comparable_n':sum(v['view_multiple'] is not None for v in videos),'labeled_n':sum(v['sentiment_n'] for v in videos)},'limitations':['Shorts/일반/롱폼은 180초·1200초 기준 길이 proxy','라이브/프리미어 판정 미확정 영상 포함','비교군은 같은 길이축·게시 후 나이 ±20%(최소 2일), 5편 이상. 동일 7일 성과가 아님','최신 댓글 최대 100개/영상의 비확률 표본. 댓글 전수 대표성 없음','수집/API 댓글 비율은 서로 다른 시점과 공개 범위 때문에 coverage의 근사치','코너는 기존 단일 할당 자료이며 다중 소속 미복원. 모음 목록 제외','감성 판정은 과거 2개 영상 표본이며 Reaction과 다름','특성 효과는 비교군 공유·계절성·다중 비교 영향을 받는 탐색 결과','장기 시간 변화 및 변곡 검증은 반복 snapshot 축적 필요']}
