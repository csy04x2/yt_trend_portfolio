import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from feature_outcome.breakout import flag_breakouts,recompute_multiples,breakouts_in_split
from feature_outcome.labels import validate_labels,label_by_title_regex
from feature_outcome.outcome import feature_outcome,HoldoutSealed

def vid(i,views,axis='shorts',month='04',mult=None,title=''):
    return {'video_id':f'v{i}','title':title or f't{i}','length_axis':axis,'duration_sec':30,'published_at':f'2026-{month}-10T00:00:00Z','view_count':views,'view_multiple':mult}

class BreakoutTests(unittest.TestCase):
 def test_iqr_multiple_event_rules_flag_but_never_delete(self):
  vs=[vid(i,100+i) for i in range(8)]+[vid(9,100000,mult=20.0,title='파이리 원이')]
  f=flag_breakouts(vs,events={'title_regex':'파이리'})
  self.assertEqual(len(f),9)                       # 아무것도 지우지 않는다
  self.assertEqual(f['v9'],{'rule_iqr':1,'rule_multiple':1,'rule_event':1,'breakout':1})
  self.assertEqual(sum(x['breakout'] for x in f.values()),1)
 def test_event_window_needs_axis_date_and_multiple(self):
  vs=[vid(1,100,month='06',mult=3.5),vid(2,100,month='06',mult=1.0),vid(3,100,axis='long',month='06',mult=3.5)]
  f=flag_breakouts(vs,events={'windows':[{'axis':'shorts','start':'2026-06-01','end':'2026-06-30','min_multiple':3}]},min_group=99)
  self.assertEqual([f[k]['rule_event'] for k in ('v1','v2','v3')],[1,0,0])
 def test_recompute_excludes_self_and_breakouts_and_needs_peers(self):
  vs=[vid(i,100) for i in range(6)]+[vid(9,100000,mult=50.0)]
  f=flag_breakouts(vs)
  m=recompute_multiples(vs,f)
  self.assertAlmostEqual(m['v0'],1.0)              # 급등 영상이 분모에 없으니 1.0
  self.assertEqual(recompute_multiples(vs[:3],flag_breakouts(vs[:3],min_group=99))['v0'],None)  # 동료 부족
 def test_breakouts_in_split(self):
  f={'a':{'breakout':1},'b':{'breakout':0},'c':{'breakout':1}}
  self.assertEqual(breakouts_in_split(f,{'a':'discovery','b':'discovery'}),{'discovery':['a'],'unsplit':['c']})

class LabelTests(unittest.TestCase):
 def test_validate_rejects_unknown_feature_and_bad_value(self):
  reg={'features':[{'feature_id':'f1'}]}
  errs=validate_labels({'v':{'f1':'U','f2':1}},reg); self.assertEqual(len(errs),1)
  errs=validate_labels({'v':{'f1':2}},reg); self.assertEqual(len(errs),1)
  errs=validate_labels({'v':{'f1':True}},reg); self.assertEqual(len(errs),1)
  self.assertEqual(validate_labels({'v':{'f1':0}},reg),[])
 def test_title_regex_content_gives_U_not_zero(self):
  cfg={'features':{'food':{'kind':'content','regex':'먹방'},'host':{'kind':'form','regex':'침착맨'},'hour':{'kind':'duration','gt_seconds':3600}}}
  out=label_by_title_regex([vid(1,1,title='평냉 토크')],cfg)
  self.assertEqual(out['v1'],{'food':'U','host':0,'hour':0})

class OutcomeTests(unittest.TestCase):
 def setUp(self):
  # 대조군 0: 0.5~0.8 네 편 + 급등 영상 다섯 편(배수 30대). 중앙값이 급등 영상 쪽으로 끌려간다
  self.vs=[vid(i,100,mult=m) for i,m in enumerate([0.5,0.6,0.7,0.8,1.5,1.6,1.7,1.8])]+[vid(9+j,9,mult=30.0+j) for j in range(5)]
  self.split={v['video_id']:'development' for v in self.vs}
  self.flags=flag_breakouts(self.vs,min_group=99)
  self.labels={f'v{i}':{'f':1 if 4<=i<8 else 0} for i in range(14)}
 def test_two_versions_and_breakout_flip(self):
  r=feature_outcome(self.vs,self.labels,self.flags,self.split)[0]
  self.assertLess(r['all']['diff'],0)              # 급등 영상이 대조군에 있어 부호가 거꾸로
  self.assertGreater(r['excluded']['diff'],0)
  self.assertIn('부호반전',r['verdict'])
  self.assertIsNotNone(r['loo_range'])
 def test_U_is_skipped_unless_opted_in(self):
  labels={k:dict(v) for k,v in self.labels.items()}
  for k in ('v0','v1','v2','v3'): labels[k]['f']='U'
  r=feature_outcome(self.vs,labels,self.flags,self.split)[0]
  self.assertEqual(r['excluded']['n0'],0); self.assertIn('셀 n<4, 판단 보류',r['verdict'])
  r=feature_outcome(self.vs,labels,self.flags,self.split,u_as_control=True)[0]
  self.assertEqual(r['excluded']['n0'],4); self.assertTrue(r['u_as_control'])
 def test_holdout_is_sealed(self):
  with self.assertRaises(HoldoutSealed): feature_outcome(self.vs,self.labels,self.flags,self.split,'holdout')
  feature_outcome(self.vs,self.labels,self.flags,{k:'holdout' for k in self.split},'holdout',unseal_holdout=True)

if __name__=='__main__':unittest.main()
