"""Regression checks for resumed channel reports; all data is synthetic."""
import json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from app.db.connection import connect
from app.pipeline import aggregate as ag, classify_videos as cv
from app.pipeline.offline_llm import save_labels
class ResumeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=connect(pathlib.Path(self.tmp.name)/'test.db')
  self.c.execute("INSERT INTO channels(channel_id,input_url,title,uploads_playlist,first_analyzed_at) VALUES('ch','url','channel','UU','2026-01-01')")
  for i in range(6):
   self.c.execute("INSERT INTO videos(video_id,channel_id,title,duration_sec,published_at,length_axis,first_seen_at) VALUES(?,?,?,?,?,?,?)",(f'v{i}','ch',f'video{i}',100,'2026-01-01','shorts','2026-01-01'))
   self.c.execute("INSERT INTO video_metrics(video_id,run_id,view_count,view_multiple,computed_at) VALUES(?,?,?,?,?)",(f'v{i}','norm',100,1.2,'2026-01-01'))
 def tearDown(self):
  self.c.close();self.tmp.cleanup()
 def taxonomy(self,axis='segment',confidence=None):
  tid=cv.save_taxonomy(self.c,'ch',{'A':'A'},'test','v1',axis)
  cv.save_labels(self.c,tid,[dict(video_id=f'v{i}',type_code='A',confidence=confidence) for i in range(6)],'v1','test')
  return tid
 def test_report_builds_missing_segment_metrics(self):
  self.taxonomy();rs=ag.run(self.c,'ch','report')
  self.assertTrue(rs);self.assertTrue(all(r['completeness']=='performance_only' for r in rs));self.assertTrue(all(r['type_count']==1 for r in rs))
  self.c.execute("UPDATE video_metrics SET view_multiple=2.3")
  rs=ag.run(self.c,'ch','report2');self.assertIn('2.30',rs[0]['conclusion'])
 def test_low_confidence_cannot_headline(self):
  self.taxonomy('topic',.2);r=ag.run(self.c,'ch','report')[0]
  self.assertEqual(r['excluded_topics'],['A']);self.assertNotIn('가장 높은',r['conclusion']);self.assertIn('보류',r['conclusion'])
 def test_confidence_roundtrip(self):
  rows=cv.validate({'types':{'A':'A'},'labels':{'1':'A'},'confidence':{'1':.25}},{'1':'v0'})
  tid=cv.save_taxonomy(self.c,'ch',{'A':'A'},'test','v1')
  cv.save_labels(self.c,tid,rows,'v1','test');self.assertEqual(self.c.execute('SELECT confidence FROM video_type_labels').fetchone()[0],.25)
  with self.assertRaises(cv.ValidationError):cv.validate({'types':{'A':'A'},'labels':{'1':'A'},'confidence':{'1':2}},{'1':'v0'})
 def test_explicit_sources_sum_once_and_provenance(self):
  self.taxonomy()
  for i,mdl in enumerate(['claude-code-offline','codex-offline']):
   cid=f'c{i}';self.c.execute("INSERT INTO comments(comment_id,video_id,text,published_at,fetched_at) VALUES(?,?,?,?,?)",(cid,'v0','text','2026-01-01','2026-01-01'))
   save_labels(self.c,[dict(comment_id=cid,sentiment='positive',confidence=.8,sarcasm_suspect=False,topics=['T8'])],'v2',mdl)
  sources=[('v2','claude-code-offline'),('v2','codex-offline')]
  r=ag.run(self.c,'ch','report',label_sources=sources)[0]
  self.assertEqual(r['comment_rows'][0]['valid_comment_count'],2)
  versions=json.loads(self.c.execute('SELECT prompt_version_set_json FROM reports LIMIT 1').fetchone()[0]);self.assertEqual(len(versions['label_sources']),2)
  save_labels(self.c,[dict(comment_id='c0',sentiment='neutral',confidence=.6,sarcasm_suspect=False,topics=['T9'])],'v2','codex-offline')
  with self.assertRaises(ValueError):ag.run(self.c,'ch','overlap',label_sources=sources)
 def test_empty_reasons_differ(self):
  text,_=ag.conclusion_draft([],[],{}, {},'topic','all');self.assertIn('집계가 없다',text)
  text,_=ag.conclusion_draft([dict(video_count=6,med_view_multiple=None)],[],{}, {},'topic','all');self.assertIn('조회 배수가 없어',text)
if __name__=='__main__':unittest.main()
