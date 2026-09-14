import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from app.pipeline.observable import timestamps,clusters,compare,effect,reaction_lift
from app.pipeline.observable_collect import collect_sample,ensure_schema
from app.db.connection import connect
import tempfile
class ObservableTests(unittest.TestCase):
 def test_timestamp_validation_and_dedup(self):
  self.assertEqual(timestamps('1:02 1:02 1:99 12:01:02 1234:56 1:00:00',100),[62])
  r=clusters([{'comment_id':'a','text':'1:02 1:04 1:02'},{'comment_id':'b','text':'1:05'}],100)
  self.assertEqual(r['timestamp_comments'],2);self.assertEqual(r['bins'][0]['n'],2)
 def test_peer_age_self_length_and_missing(self):
  vs=[dict(video_id=str(i),age_days=10,length_axis='long',is_live=0,view_count=100,like_rate=None,comment_rate=0) for i in range(6)]
  vs[0]['view_count']=200;r=compare(vs[0],vs)
  self.assertEqual(r['view_multiple'],2);self.assertEqual(r['comparison_n'],5);self.assertIsNone(r['like_rate_multiple']);self.assertNotIn('0',r['comparison_ids'])
  vs[1]['age_days']=100;self.assertIsNone(compare(vs[0],vs)['view_multiple'])
 def test_effect_small_n_and_outlier(self):
  self.assertIsNone(effect([1]*4,[1]*9));r=effect([1,1,2,2,100],[1]*5)
  self.assertEqual(r['estimate'],1);self.assertLess(r['leave_one_out_range'][0],r['estimate'])
 def test_reaction_provenance(self):
  self.assertEqual(reaction_lift([{'share':.4,'provenance':['v','p','m']}],[{'share':.2,'provenance':['v','p','m']}])['estimate'],20)
  with self.assertRaises(ValueError):reaction_lift([{'share':.4,'provenance':['v','p','a']}],[{'share':.2,'provenance':['v','p','b']}])
 def test_reply_pagination_and_cap(self):
  class Fake:
   def _get(self,endpoint,**kw):
    if endpoint=='commentThreads':return {'items':[{'id':'thread','snippet':{'topLevelComment':{'id':'top','snippet':{'textOriginal':'x'}},'totalReplyCount':3}}], 'nextPageToken':'moretops'}
    return {'items':[{'id':'r'+kw.get('pageToken','1'),'snippet':{'textOriginal':'reply'}}], 'nextPageToken':'2'}
  with tempfile.TemporaryDirectory() as t:
   c=connect(pathlib.Path(t)/'test.db');ensure_schema(c);collect_sample(c,Fake(),'r','v',reply_pages=2)
   row=c.execute('select * from observation_threads').fetchone();self.assertEqual(row['collected_replies'],2);self.assertEqual(row['status'],'capped');self.assertEqual(c.execute('select status from observation_collection').fetchone()[0],'capped');c.close()
if __name__=='__main__':unittest.main()
