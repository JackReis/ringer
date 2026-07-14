#!/usr/bin/env python3
from __future__ import annotations
import hashlib, hmac, json, os, socket, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; TOOL=ROOT/'tools/fleet_wave.py'
def executable(path, body):
 path.write_text('#!/usr/bin/env python3\n'+body); path.chmod(0o755); return path
class FleetWaveTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.log=self.root/'calls.jsonl'; self.runs=self.root/'state'/'runs'; self.runs.mkdir(parents=True)
  self.work=self.root/'work'; (self.work/'alpha').mkdir(parents=True); (self.work/'alpha'/'proof.txt').write_text('proof\n')
  self.bd=executable(self.root/'bd',"""import json,os,sys
with open(os.environ['CALL_LOG'],'a') as f:f.write(json.dumps(['bd',*sys.argv[1:]])+'\\n')
if os.environ.get('BEADS_DIR')!='/ledger/main.db':raise SystemExit(7)
marker=os.environ['CALL_LOG']+'.closed'
if os.environ.get('BD_FAIL')=='1' and 'close' in sys.argv:raise SystemExit(9)
if 'close' in sys.argv:open(marker,'w').close()
status='closed' if os.path.exists(marker) else os.environ.get('BD_STATUS','in_progress')
requested=sys.argv[3] if sys.argv[1:3]==['claim','acquire'] else (sys.argv[2] if len(sys.argv)>2 else 'x')
item_id=os.environ.get('BD_WRONG_ID',requested) if requested==os.environ.get('BD_WRONG_ID_TARGET',requested) else requested
item={'id':item_id,'status':status,'assignee':os.environ.get('BD_ASSIGNEE','alice'),'authority_host':os.uname().nodename,'store_locator':'/ledger/main.db','claim_id':os.environ.get('BD_CLAIM_ID','claim-live-1'),'attempt_id':'attempt-1','issue_version':'7','reservation':'acquired','lease_expires_at':os.environ.get('BD_LEASE','2999-01-01T00:00:00Z'),'capabilities':['dispatch'],'concurrency':{'active':int(os.environ.get('BD_ACTIVE','0')),'limit':1}}
n=int(os.environ.get('BD_ARRAY','1')) if requested==os.environ.get('BD_ARRAY_ID',requested) else 1
print(json.dumps(item if n==-1 else [item]*n))
""")
  self.ringer=executable(self.root/'ringer',"""import json,os,sys,pathlib
with open(os.environ['CALL_LOG'],'a') as f:f.write(json.dumps(['ringer',*sys.argv[1:]])+'\\n')
if sys.argv[1]=='run' and '--dry-run' not in sys.argv:
 d=pathlib.Path(os.environ['RUNS']); d.mkdir(parents=True,exist_ok=True); taskdir=pathlib.Path(os.environ['TASKDIR'])
 state={'run_id':'r1','state':'finished','finished':True,'pass':1,'fail':0,'summary':{'pass':1,'fail':0,'tokens':0},'totals':{'running':0,'done':1,'pass':1,'fail':0,'tokens':0},'tasks':[{'key':'alpha','status':'pass','verdict':'PASS','check_returncode':0,'taskdir':str(taskdir)}]}
 mode=os.environ.get('STATE_MODE','new')
 if mode=='new':(d/'r1.json').write_text(json.dumps(state))
 elif mode=='two':(d/'r1.json').write_text(json.dumps(state));(d/'r2.json').write_text(json.dumps(state))
 elif mode=='overwrite':(d/'old.json').write_text(json.dumps(state))
""")
  self.pc=executable(self.root/'paperclip',"""import json,os,sys
with open(os.environ['CALL_LOG'],'a') as f:f.write(json.dumps(['paperclip',*sys.argv[1:]])+'\\n')
if len(sys.argv)>2 and sys.argv[1]=='show':print(json.dumps({'id':'canonical-'+sys.argv[2],'identifier':sys.argv[2]}))
elif len(sys.argv)>3 and sys.argv[1]=='comment':
 import hashlib
 print(json.dumps({'issue_id':sys.argv[2],'payload_sha256':hashlib.sha256(sys.argv[3].encode()).hexdigest(),'comment_id':'c1'}))
""")
  self.ringside=executable(self.root/'ringside',"""import json,os,sys
with open(os.environ['CALL_LOG'],'a') as f:f.write(json.dumps(['ringside',*sys.argv[1:]])+'\\n')
if os.environ.get('RINGSIDE_FAIL')=='1':raise SystemExit(8)
print(json.dumps({'runs':[{'run_id':'r1'}]} if sys.argv[-1].endswith('/api/runs') else {'artifacts':[{'metadata':{'run_id':'r1'}}]}))
""")
  self.rm=self.root/'ringer.json'; self.rm.write_text(json.dumps({'workdir':str(self.work),'tasks':[{'key':'alpha','check':'test -s proof.txt && grep -q proof proof.txt','expect_files':['proof.txt']}]}))
  self.m=self.root/'manifest-v1.json'; self.write_manifest(); self.prep=self.root/'prepared.json'; self.exe=self.root/'executed.json'; self.done=self.root/'done.json'
 def tearDown(self):self.t.cleanup()
 def write_manifest(self,**kw):
  d={'schema_version':'fleet-wave.v1','manifest_version':1,'wave_id':'wave','attempt_id':'attempt-1','supersedes':None,'ringer_manifest':str(self.rm),'ringer_state_dir':str(self.runs.parent),'beads':{'host':socket.gethostname(),'store':'/ledger/main.db','claimant':'alice','issue_id':'bead-child','existing_ids':[]},'paperclip':{'issue_id':'pc-parent','existing_ids':[]},'ringside':{'base_url':'http://127.0.0.1:9999'},'bifrost':{'correlation':None},'tasks':[{'key':'alpha','work_type':'other','check':'test -s proof.txt && grep -q proof proof.txt','negative_controls':[{'name':'missing artifact','setup':'rm -f proof.txt'},{'name':'wrong content','setup':"printf 'wrong\\n' > proof.txt"}],'evidence':{'strength':'strong','kind':'objective'}}]};d.update(kw);self.m.write_text(json.dumps(d))
 def cli(self,cmd,extra=(),env=None):
  receipts={'prepare':self.prep,'execute':self.exe,'accept':self.done}; a=[sys.executable,str(TOOL),cmd,str(self.m),'--bd-bin',str(self.bd),'--ringer-bin',str(self.ringer),'--paperclip-bin',str(self.pc),'--ringside-bin',str(self.ringside),'--beads-host',socket.gethostname(),'--beads-store','/ledger/main.db','--beads-claimant','alice','--receipt',str(receipts[cmd])]
  if cmd=='execute':a += ['--prepared-receipt',str(self.prep)]
  if cmd=='accept':a += ['--prepared-receipt',str(self.prep),'--execute-receipt',str(self.exe)]
  e=os.environ.copy();e.update({'CALL_LOG':str(self.log),'RUNS':str(self.runs),'TASKDIR':str(self.work/'alpha')});e.update(env or {})
  return subprocess.run(a+list(extra),text=True,capture_output=True,env=e)
 def calls(self):return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []
 def prepare_ok(self):
  r=self.cli('prepare');self.assertEqual(0,r.returncode,r.stderr);self.log.unlink()
 def execute_ok(self):
  self.prepare_ok();r=self.cli('execute');self.assertEqual(0,r.returncode,r.stderr);self.log.unlink()
 def test_prepare_accepts_array_and_posts_projection_only_after_lint_dryrun(self):
  r=self.cli('prepare');self.assertEqual(0,r.returncode,r.stderr); c=self.calls(); lint=['ringer','lint',str(self.rm.resolve())];dry=['ringer','run',str(self.rm.resolve()),'--dry-run'];post=next(x for x in c if x[:2]==['paperclip','comment']);self.assertFalse(any(x[:2]==['bd','update'] for x in c));self.assertEqual(['bd','claim','acquire','bead-child'],c[0][:4]);self.assertLess(c.index(lint),c.index(dry));self.assertLess(c.index(dry),c.index(post));self.assertEqual('prepared',json.loads(self.prep.read_text())['event'])
 def test_prepare_requires_exact_claimant_and_status(self):
  for env in ({'BD_ASSIGNEE':'bob'},{'BD_STATUS':'open'}):
   r=self.cli('prepare',env=env);self.assertNotEqual(0,r.returncode);self.assertNotIn('ringer',[x[0] for x in self.calls()]);self.log.unlink()
 def test_authority_host_store_mismatch_fails_before_commands(self):
  for flag,value in (('--beads-host','other'),('--beads-store','/other')):
   r=self.cli('prepare',(flag,value));self.assertNotEqual(0,r.returncode);self.assertFalse(self.log.exists())
 def test_execute_rereads_claim_then_dispatches_and_binds_one_new_state(self):
  self.prepare_ok();r=self.cli('execute');self.assertEqual(0,r.returncode,r.stderr);c=self.calls();cas=next(i for i,x in enumerate(c) if x[1:3]==['claim','acquire']);dispatch=c.index(['ringer','run',str(self.rm.resolve())]);self.assertLess(cas,dispatch);rec=json.loads(self.exe.read_text());self.assertEqual(hashlib.sha256((self.runs/'r1.json').read_bytes()).hexdigest(),rec['run_state_sha256'])
 def test_execute_rejects_nonterminal_or_orphaned_and_ambiguous_receipts(self):
  self.prepare_ok();r=self.cli('execute',env={'BD_STATUS':'open'});self.assertNotEqual(0,r.returncode);self.assertNotIn('ringer',[x[0] for x in self.calls()]);self.log.unlink()
  (self.runs/'old.json').write_text('{}'); r=self.cli('execute',env={'BD_ASSIGNEE':''});self.assertNotEqual(0,r.returncode)
 def test_accept_validates_real_state_without_top_level_verdict_and_replays_state_taskdir(self):
  self.execute_ok();r=self.cli('accept');self.assertEqual(0,r.returncode,r.stderr);self.assertTrue(json.loads(self.done.read_text())['independent_replay']['alpha'])
 def test_accept_rejects_bad_real_state_fields(self):
  self.execute_ok();state=self.runs/'r1.json';d=json.loads(state.read_text());d['tasks'][0]['check_returncode']=1;state.write_text(json.dumps(d)); rec=json.loads(self.exe.read_text());rec['run_state_sha256']=hashlib.sha256(state.read_bytes()).hexdigest();self.exe.write_text(json.dumps(rec));r=self.cli('accept');self.assertNotEqual(0,r.returncode)
 def test_beads_terminal_receipt_and_explicit_close_precede_paperclip_parent_projection(self):
  self.execute_ok();r=self.cli('accept');self.assertEqual(0,r.returncode,r.stderr);c=self.calls();rec=json.loads(self.done.read_text());reason=rec['beads_close_reason'];close_call=['bd','close','bead-child','--reason',reason,'--json'];close=c.index(close_call);comment=next(i for i,x in enumerate(c) if x[:4]==['bd','comments','add','bead-child']);readback=next(i for i,x in enumerate(c) if i>close and x[:3]==['bd','show','bead-child']);pc=next(i for i,x in enumerate(c) if x[:2]==['paperclip','comment']);self.assertLess(comment,close);self.assertLess(close,readback);self.assertLess(readback,pc)
 def test_beads_failure_blocks_paperclip(self):
  self.execute_ok();r=self.cli('accept',env={'BD_FAIL':'1'});self.assertNotEqual(0,r.returncode);self.assertNotIn('paperclip',[x[0] for x in self.calls()])
 def test_ringside_is_read_only_and_bifrost_unproven(self):
  self.execute_ok();r=self.cli('accept');self.assertEqual(0,r.returncode,r.stderr);c=self.calls();self.assertIn(['ringside','get','http://127.0.0.1:9999/api/runs'],c);self.assertIn(['ringside','get','http://127.0.0.1:9999/api/library'],c);self.assertFalse(any(x[0]=='ringside' and x[1]!='get' for x in c));self.assertIsNone(json.loads(self.done.read_text())['bifrost_correlation'])
 def test_dict_empty_and_multi_beads_outputs(self):
  self.assertEqual(0,self.cli('prepare',env={'BD_ARRAY':'-1'}).returncode);self.prep.unlink();self.log.unlink()
  for n in ('0','2'):
   self.assertNotEqual(0,self.cli('prepare',env={'BD_ARRAY':n}).returncode);self.log.unlink()
 def test_existing_beads_ids_require_exact_single_item_and_id(self):
  for env in ({'BD_ARRAY':'0','BD_ARRAY_ID':'old-bead'},{'BD_ARRAY':'2','BD_ARRAY_ID':'old-bead'},{'BD_WRONG_ID':'other','BD_WRONG_ID_TARGET':'old-bead'}):
   self.write_manifest();d=json.loads(self.m.read_text());d['beads']['existing_ids']=['old-bead'];self.m.write_text(json.dumps(d));r=self.cli('prepare',env=env);self.assertNotEqual(0,r.returncode);self.assertFalse(self.prep.exists());self.log.unlink()
 def test_manifest_supersession_is_exactly_previous_version_hash_path_and_wave(self):
  prior=json.loads(self.m.read_text());h=hashlib.sha256(self.m.read_bytes()).hexdigest();v2=self.root/'manifest-v2.json';current=dict(prior,manifest_version=2,supersedes={'path':'manifest-v1.json','sha256':h});v2.write_text(json.dumps(current));old=self.m;self.m=v2
  try:
   r=self.cli('prepare');self.assertEqual(0,r.returncode,r.stderr);self.prep.unlink();self.log.unlink()
   cases=[({'path':'manifest-v1.json','sha256':'0'*64},'wave',2),({'path':'other.json','sha256':h},'wave',2),({'path':'manifest-v1.json','sha256':h},'wave',3),({'path':'manifest-v1.json','sha256':h},'different',2)]
   for sup,wave,version in cases:
    name=self.root/f'manifest-v{version}.json';name.write_text(json.dumps(dict(current,manifest_version=version,wave_id=wave,supersedes=sup)));self.m=name;self.assertNotEqual(0,self.cli('prepare').returncode);self.assertFalse(self.log.exists())
   self.m=old;self.m.write_text(json.dumps(dict(prior,supersedes={'path':'x','sha256':'0'*64})));self.assertNotEqual(0,self.cli('prepare').returncode);self.assertFalse(self.log.exists())
  finally:self.m=old
 def test_optional_task_strings_and_expected_files_are_nonempty(self):
  for field,value in (('spec',''),('spec',' \t\n'),('check',''),('verified',''),('expect_files',['']),('expect_files',[' \n'])):
   self.write_manifest();d=json.loads(self.m.read_text());d['tasks'][0][field]=value;self.m.write_text(json.dumps(d));self.assertNotEqual(0,self.cli('prepare').returncode);self.assertFalse(self.log.exists())
 def test_actual_host_and_strict_manifest_shapes(self):
  d=json.loads(self.m.read_text());d['beads']['host']='invented';self.m.write_text(json.dumps(d));self.assertNotEqual(0,self.cli('prepare',('--beads-host','invented')).returncode);self.assertFalse(self.log.exists())
  for mutation in ('bifrost','extra','empty'):
   self.write_manifest();d=json.loads(self.m.read_text())
   if mutation=='bifrost':d['bifrost']['correlation']='claimed'
   elif mutation=='extra':d['tasks'][0]['evidence']['extra']=1
   else:d['wave_id']=''
   self.m.write_text(json.dumps(d));self.assertNotEqual(0,self.cli('prepare').returncode);self.assertFalse(self.log.exists())
 def test_execute_rejects_zero_two_and_overwrite(self):
  for mode in ('none','two','overwrite'):
   if self.prep.exists():self.prep.unlink()
   self.prepare_ok()
   if mode=='overwrite':(self.runs/'old.json').write_text('{}')
   self.assertNotEqual(0,self.cli('execute',env={'STATE_MODE':mode}).returncode);self.assertFalse(self.exe.exists())
   for x in self.runs.glob('*.json'):x.unlink()
 def test_ringside_failure_is_degraded_after_terminal_truth(self):
  self.execute_ok();r=self.cli('accept',env={'RINGSIDE_FAIL':'1'});self.assertNotEqual(0,r.returncode);c=self.calls();self.assertTrue(any(x[0]=='paperclip' for x in c));self.assertTrue(any(x[0]=='bd' and 'comments' in x for x in c));self.assertTrue(self.done.exists());self.assertTrue(Path(str(self.done)+'.ringside-projection-degraded.json').exists())
 def test_finished_totals_and_taskdir_containment(self):
  self.execute_ok();state=self.runs/'r1.json';d=json.loads(state.read_text());d['totals']['running']=1;state.write_text(json.dumps(d));rec=json.loads(self.exe.read_text());rec['run_state_sha256']=hashlib.sha256(state.read_bytes()).hexdigest();self.exe.write_text(json.dumps(rec));self.assertNotEqual(0,self.cli('accept').returncode)
 def test_judge_binds_execution_state_and_exact_shape(self):
  d=json.loads(self.m.read_text());d['tasks'][0]['evidence']['kind']='judgmental';self.m.write_text(json.dumps(d));self.execute_ok();ex=json.loads(self.exe.read_text());j=self.root/'judge.json';att={'judge_id':'independent-judge','session_id':'fresh-session','model':'judge-model','harness_attestation':{'attestation_id':'att-1','provider':'test-harness','session_id':'fresh-session','judge_id':'independent-judge','issuer':'trusted-test'},'new_session':True,'resumed':False,'role_history':['judge'],'evidence_fetched_at':'2998-01-01T00:00:00Z','judged_at':'2999-01-01T00:00:00Z','criteria':['artifact is sufficient'],'rationale':'The replayed artifact satisfies the criterion.','task_keys':['alpha'],'independent':True,'verdict':'PASS','wave_id':'wave','manifest_sha256':hashlib.sha256(self.m.read_bytes()).hexdigest(),'execute_receipt_sha256':hashlib.sha256(self.exe.read_bytes()).hexdigest(),'run_state_sha256':ex['run_state_sha256']};att['harness_attestation']['signature']=hmac.new(b'secret',json.dumps(att,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest();j.write_text(json.dumps(att));r=self.cli('accept',('--judge-receipt',str(j)),{'FLEET_JUDGE_ATTESTATION_SECRET':'secret'});self.assertEqual(0,r.returncode,r.stderr);self.assertEqual(hashlib.sha256(j.read_bytes()).hexdigest(),json.loads(self.done.read_text())['judge_receipt_sha256']);self.done.unlink();self.log.unlink();att['execute_receipt_sha256']='0'*64;j.write_text(json.dumps(att));self.assertNotEqual(0,self.cli('accept',('--judge-receipt',str(j)),{'FLEET_JUDGE_ATTESTATION_SECRET':'secret'}).returncode);self.assertFalse(self.log.exists())
 def test_prepared_receipt_is_exact_typed_authorization(self):
  self.prepare_ok();original=json.loads(self.prep.read_text())
  mutations=[('extra',dict(original,extra=1)),('authorization',dict(original,dispatch_authorized=1)),('event',dict(original,event='executed')),('naive-time',dict(original,prepared_at='2026-01-01T00:00:00')),('bad-hash',dict(original,manifest_sha256=7)),('authority',dict(original,beads_authority=dict(original['beads_authority'],claimant='mallory')))]
  for name,value in mutations:
   self.prep.write_text(json.dumps(value));r=self.cli('execute');self.assertNotEqual(0,r.returncode,name);self.assertFalse(self.log.exists(),name);self.prep.write_text(json.dumps(original))
 def test_execute_receipt_is_exact_typed_and_bound(self):
  self.execute_ok();original=json.loads(self.exe.read_text())
  mutations=[('extra',dict(original,extra=1)),('naive-time',dict(original,executed_at='2026-01-01T00:00:00')),('path-type',dict(original,run_state_path=7)),('hash-type',dict(original,run_state_sha256=True)),('prepared-hash',dict(original,prepared_receipt_sha256='0'*64))]
  for name,value in mutations:
   self.exe.write_text(json.dumps(value));r=self.cli('accept');self.assertNotEqual(0,r.returncode,name);self.assertFalse(self.log.exists(),name);self.exe.write_text(json.dumps(original))
 def test_accept_rejects_run_state_outside_bound_runs_and_path_substitution(self):
  self.execute_ok();original=json.loads(self.exe.read_text());outside=self.root/'outside.json';outside.write_bytes((self.runs/'r1.json').read_bytes())
  for candidate in (outside,self.runs/'..'/'outside.json'):
   rec=dict(original,run_state_path=str(candidate),run_state_sha256=hashlib.sha256(outside.read_bytes()).hexdigest());self.exe.write_text(json.dumps(rec));r=self.cli('accept');self.assertNotEqual(0,r.returncode);self.assertFalse(self.log.exists())
 def test_controller_enforces_cross_field_issue_ids_and_duplicate_task_keys(self):
  for surface in ('beads','paperclip'):
   self.write_manifest();d=json.loads(self.m.read_text());d[surface]['existing_ids']=[d[surface]['issue_id']];self.m.write_text(json.dumps(d));self.assertNotEqual(0,self.cli('prepare').returncode);self.assertFalse(self.log.exists())
  self.write_manifest();d=json.loads(self.m.read_text());d['tasks'].append(dict(d['tasks'][0]));self.m.write_text(json.dumps(d));self.assertNotEqual(0,self.cli('prepare').returncode);self.assertFalse(self.log.exists())
 def test_schema_documents_semantics_and_rejects_whitespace_strings(self):
  schema=json.loads((ROOT/'schema/fleet-wave.v1.json').read_text());text=json.dumps(schema)
  self.assertIn('controller-enforced',text);self.assertIn('duplicate task',text);self.assertIn('issue_id',text)
  def walk(value):
   if isinstance(value,dict):
    if value.get('type')=='string' and value.get('minLength')==1:self.assertEqual(r'\S',value.get('pattern'))
    for child in value.values():walk(child)
   elif isinstance(value,list):
    for child in value:walk(child)
  walk(schema)
 def test_paperclip_identifier_or_canonical_id_is_preserved(self):
  r=self.cli('prepare');self.assertEqual(0,r.returncode,r.stderr)
  identities=json.loads(self.prep.read_text())['stage_extension']['paperclip_readbacks']
  self.assertEqual({'requested':'pc-parent','identifier':'pc-parent','canonical_id':'canonical-pc-parent'},identities[0])
 def test_other_cannot_bypass_strong_check(self):
  for check in ('true','exit 0','test -s proof.txt'):
   self.write_manifest();d=json.loads(self.m.read_text());d['tasks'][0]['check']=check;self.m.write_text(json.dumps(d))
   self.assertNotEqual(0,self.cli('prepare').returncode);self.assertFalse(self.log.exists())
 def test_live_claim_proof_is_mandatory_and_bound(self):
  for env in ({'BD_CLAIM_ID':''},{'BD_LEASE':'2000-01-01T00:00:00Z'},{'BD_ACTIVE':'1'}):
   r=self.cli('prepare',env=env);self.assertNotEqual(0,r.returncode);self.assertEqual('UNKNOWN_DEGRADED',json.loads(self.prep.read_text())['stage_extension']['claim_state']);self.assertNotIn('ringer',[x[0] for x in self.calls()]);self.prep.unlink();self.log.unlink()
 def test_transition_chain_e3_e4_and_receipted_disposition(self):
  self.execute_ok();r=self.cli('accept');self.assertEqual(0,r.returncode,r.stderr);rec=json.loads(self.done.read_text());self.assertEqual('accepted',rec['authoritative_disposition']);self.assertEqual('BEADS ACCEPTED',rec['transition']['to']);self.assertIn('stdout_sha256',rec['check_execution']['alpha']);self.assertTrue(rec['clean_replay']['alpha']['isolated_copy']);self.assertEqual(2,len(rec['clean_replay']['alpha']['negative_controls']));self.assertEqual(['INTAKE','LEDGERED','CLAIMED','MANIFEST-v1','LINTED','DRY-RUN','PAPERCLIP PREPARED RECEIPT','RINGER RUN','INDEPENDENT CHECK REPLAY','BEADS ACCEPTED'],[x['transition'] for x in rec['transitions']])
 def test_structured_negative_controls_reject_wrapped_noop(self):
  d=json.loads(self.m.read_text());d['tasks'][0]['check']='sh -c true';self.m.write_text(json.dumps(d));rd=json.loads(self.rm.read_text());rd['tasks'][0]['check']='sh -c true';self.rm.write_text(json.dumps(rd));self.execute_ok();r=self.cli('accept');self.assertNotEqual(0,r.returncode);self.assertFalse(self.done.exists());self.assertFalse(any(x[0]=='bd' for x in self.calls()))
 def test_empty_run_id_cannot_match_null(self):
  self.execute_ok();state=self.runs/'r1.json';d=json.loads(state.read_text());d['run_id']='';state.write_text(json.dumps(d));rec=json.loads(self.exe.read_text());rec['run_state_sha256']=hashlib.sha256(state.read_bytes()).hexdigest();self.exe.write_text(json.dumps(rec));self.assertNotEqual(0,self.cli('accept').returncode)
 def test_judge_empty_harness_is_rejected(self):
  d=json.loads(self.m.read_text());d['tasks'][0]['evidence']['kind']='judgmental';self.m.write_text(json.dumps(d));self.execute_ok();j=self.root/'judge.json';j.write_text('{}');self.assertNotEqual(0,self.cli('accept',('--judge-receipt',str(j))).returncode)
 def test_manifest_and_receipts_bind_attempt_and_chain(self):
  self.prepare_ok();p=json.loads(self.prep.read_text());self.assertEqual('attempt-1',p['attempt_id']);self.assertIn('authority',p);self.assertIn('integrity',p)
  r=self.cli('execute');self.assertEqual(0,r.returncode,r.stderr);e=json.loads(self.exe.read_text());self.assertEqual(p['receipt_id'],e['predecessor']['receipt_id']);self.assertEqual(hashlib.sha256(self.prep.read_bytes()).hexdigest(),e['predecessor']['digest'])
if __name__=='__main__':unittest.main()
