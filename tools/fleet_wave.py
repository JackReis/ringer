#!/usr/bin/env python3
"""Fail-closed Fleet Wave v1 controller (stdlib only)."""
from __future__ import annotations
import argparse, hashlib, hmac, json, os, re, shutil, socket, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
class ProtocolError(RuntimeError): pass
SANDBOX_POLICY_VERSION='fleet-wave-seatbelt.v1'
def verification_env(temp_home):
 return {'PATH':'/usr/bin:/bin','HOME':str(temp_home),'TMPDIR':str(temp_home),'LANG':'C','LC_ALL':'C','TZ':'UTC'}
def replay_interpreter():
 if sys.platform=='darwin':
  system_python=Path('/usr/bin/python3')
  if not system_python.is_file() or not os.access(system_python,os.X_OK):raise ProtocolError('system Python required for macOS sandbox replay')
  return str(system_python)
 return sys.executable
def _seatbelt_quote(path):return '"'+str(Path(path).resolve()).replace('\\','\\\\').replace('"','\\"')+'"'
def sandbox_profile(cwd,temp_home):
 # macOS 26 aborts sandbox-exec when deny-default profiles use filtered
 # file-read-data allows. Permit reads generally, then deny credential/user
 # roots and carve back only the isolated fixture and temporary home.
 denied_reads=['/Users','/Volumes','/Network','/opt','/private/tmp','/private/var/folders','/private/var/tmp','/Library/Keychains']
 reads=[cwd,temp_home];writes=[cwd,temp_home]
 lines=['(version 1)','(deny default)','(deny network*)','(allow process*)','(allow file-read*)']
 lines += [f'(deny file-read* (subpath {_seatbelt_quote(x)}))' for x in denied_reads]
 lines += [f'(allow file-read* (subpath {_seatbelt_quote(x)}))' for x in reads]
 lines += [f"(allow file-write* {' '.join(f'(subpath {_seatbelt_quote(x)})' for x in writes)})",'']
 return '\n'.join(lines)
def sandboxed_shell(command,cwd,temp_home,sandbox_bin):
 cwd=Path(cwd).resolve();home=Path(temp_home).resolve()
 if not sandbox_bin:raise ProtocolError('sandbox backend required on this platform')
 sandbox=Path(sandbox_bin).resolve()
 if not sandbox.is_file() or not os.access(sandbox,os.X_OK):raise ProtocolError(f'sandbox backend unavailable: {sandbox_bin}')
 profile_text=sandbox_profile(cwd,home);marker=home/f'.fleet-wave-child-status-{os.getpid()}-{hashlib.sha256(command.encode()).hexdigest()[:12]}';profile=None
 try:
  try:
   fd,profile=tempfile.mkstemp(prefix='fleet-wave-seatbelt-',suffix='.sb',dir=home)
   with os.fdopen(fd,'w') as f:f.write(profile_text);f.flush();os.fsync(f.fileno())
  except OSError as e:raise ProtocolError(f'sandbox profile creation failed: {e}') from e
  quoted=subprocess.list2cmdline([str(marker)]);wrapped=f"{command}\nstatus=$?\nprintf '%s\\n' \"$status\" > {quoted}\nexit \"$status\""
  try:r=subprocess.run([str(sandbox),'-f',profile,'/bin/sh','-c',wrapped],cwd=cwd,env=verification_env(home),text=True,capture_output=True)
  except OSError as e:raise ProtocolError(f'sandbox backend unavailable: {e}') from e
  try:status=int(marker.read_text().strip())
  except (OSError,ValueError) as e:raise ProtocolError(f'sandbox backend/policy failure (exit {r.returncode}): {r.stderr.strip()}') from e
  if status!=r.returncode:raise ProtocolError('sandbox backend returned a status different from the child')
  r.sandbox_metadata={'executable':str(sandbox),'profile_digest':hashlib.sha256(profile_text.encode()).hexdigest(),'policy_version':SANDBOX_POLICY_VERSION,'environment_digest':json_digest(verification_env(home))}
  return r
 finally:
  for q in (profile,marker):
   if q:
    try:Path(q).unlink()
    except OSError:pass
def now(): return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
def load(path):
 try:v=json.loads(Path(path).read_text())
 except (OSError,json.JSONDecodeError) as e:raise ProtocolError(f'cannot read JSON {path}: {e}') from e
 if not isinstance(v,dict):raise ProtocolError(f'{path} must contain a JSON object')
 return v
def digest(path):
 try:return hashlib.sha256(Path(path).read_bytes()).hexdigest()
 except OSError as e:raise ProtocolError(f'cannot hash {path}: {e}') from e
def resolve(base,value):
 p=Path(value).expanduser();return p if p.is_absolute() else base/p
def write_receipt(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 encoded=(json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
 if path.exists():
  if path.read_bytes()==encoded:return
  raise ProtocolError(f'refusing to overwrite non-identical receipt: {path}')
 fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(encoded);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run(argv,cwd=None,env=None):
 try:r=subprocess.run(argv,cwd=cwd,env=env,text=True,capture_output=True)
 except OSError as e:raise ProtocolError(f'could not execute {argv[0]}: {e}') from e
 if r.returncode:raise ProtocolError(f"command failed ({' '.join(argv)}): {r.stderr.strip() or r.stdout.strip() or r.returncode}")
 return r
def exact(v,keys,label):
 if not isinstance(v,dict) or set(v)!=set(keys):raise ProtocolError(f'invalid {label} object shape')
def nonempty(v):return isinstance(v,str) and bool(v.strip())
def sha(v):return isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) is not None
def json_digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def receipt_digest(v):return hashlib.sha256((json.dumps(v,indent=2,sort_keys=True)+'\n').encode()).hexdigest()
def authority(m):
 b=m['beads']; core={'issue_id':b['issue_id'],'authority_host':b['host'],'store_locator':b['store'],'claimant':b['claimant']};return {**core,'digest':json_digest(core)}
def enrich(rec,m,receipt_type,from_state,to_state,predecessor=None,result='PASS',reason=None,evidence=None,stage=None):
 rec.update({'protocol_version':'1.0.0','receipt_id':f"{m['attempt_id']}:{receipt_type}",'receipt_type':receipt_type,'authority':authority(m),'work_id':m['beads']['issue_id'],'beads_issue_version':'readback','claim_id':m['attempt_id']+':claim','attempt_id':m['attempt_id'],'manifest_version':f"v{m['manifest_version']}",'manifest_digest':rec['manifest_sha256'],'predecessor':{'receipt_id':predecessor.get('receipt_id') if predecessor else None,'digest':predecessor.get('digest') if predecessor else None},'actor':{'identity':os.environ.get('USER','controller'),'role':'controller','service':'fleet-wave','host':socket.gethostname(),'execution_id':str(os.getpid()),'session_id':None,'model':None,'attestation':{'type':'process','cryptographic':False}},'timestamps':{'started_at':rec.get('prepared_at') or rec.get('executed_at') or rec.get('accepted_at'),'ended_at':rec.get('prepared_at') or rec.get('executed_at') or rec.get('accepted_at')},'transition':{'from':from_state,'to':to_state},'result':result,'reason_code':reason,'evidence':evidence or [],'stage_extension':stage or {}})
 rec['integrity']={'digest':json_digest(rec),'attestation_type':'sha256-non-cryptographic','attested_by':'fleet-wave-controller'};return rec
def strings(v,unique=False):return isinstance(v,list) and all(nonempty(x) for x in v) and (not unique or len(v)==len(set(v)))
def parse_item(output,label='Beads'):
 try:v=json.loads(output)
 except json.JSONDecodeError as e:raise ProtocolError(f'{label} returned invalid JSON') from e
 if isinstance(v,list):
  if len(v)!=1 or not isinstance(v[0],dict):raise ProtocolError(f'{label} must return exactly one item')
  v=v[0]
 if not isinstance(v,dict):raise ProtocolError(f'{label} must return an object or one-item array')
 return v
def bd(a,*parts):
 env=os.environ.copy();env['BEADS_DIR']=a.beads_store
 return run([a.bd_bin,*parts,'--json'],env=env)
def validate_beads_item(item,m,status,active=True):
 issue=m['beads']['issue_id'];claimant=m['beads']['claimant']
 if item.get('id')!=issue or item.get('status')!=status:raise ProtocolError('Beads readback does not exactly match issue and status')
 if active and item.get('assignee')!=claimant:raise ProtocolError('Beads readback does not exactly match claimant')
 if active:
  if not nonempty(item.get('updated_at')):raise ProtocolError('Beads active claim readback lacks updated_at')
  dt(item['updated_at'])
 return item
def claim(a,m):
 issue=m['beads']['issue_id'];claimant=m['beads']['claimant']
 updated=parse_item(bd(a,'update',issue,'--claim','--actor',claimant).stdout)
 validate_beads_item(updated,m,'in_progress')
 item=validate_beads_item(parse_item(bd(a,'show',issue).stdout),m,'in_progress')
 if any(updated.get(k)!=item.get(k) for k in ('id','status','assignee','updated_at')):raise ProtocolError('Beads atomic claim and exact readback differ')
 evidence={'issue_id':item['id'],'claimant':item['assignee'],'attempt_id':m['attempt_id'],'updated_at':item['updated_at']}
 return {**evidence,'evidence_digest':json_digest(evidence),'lease_supported':False,'atomic_operation':'bd update ISSUE --claim --actor CLAIMANT --json'}
def show_disposition(a,m,status):
 return validate_beads_item(parse_item(bd(a,'show',m['beads']['issue_id']).stdout),m,status,active=False)
def actor(m):
 return {'identity':os.environ.get('USER','controller'),'role':'controller','service':'fleet-wave','host':socket.gethostname(),'execution_id':m['attempt_id'],'session_id':os.environ.get('FLEET_SESSION_ID'),'model':os.environ.get('FLEET_MODEL'),'attestation':{'type':'attempt-bound-controller','cryptographic':False}}
def transition(m,from_state,to_state,previous,claim_id,beads_version,result='PASS',evidence=None,reason=None,stage=None,at=None):
 at=at or beads_version;pred={'receipt_id':None,'digest':None} if previous is None else {'receipt_id':previous['receipt_id'],'digest':receipt_digest(previous)}
 t={'schema_version':'fleet-wave.v1','protocol_version':'1.0.0','receipt_id':f"{m['attempt_id']}:transition:{to_state}",'receipt_type':'state-transition','authority':authority(m),'work_id':m['beads']['issue_id'],'beads_issue_version':beads_version,'claim_id':claim_id,'attempt_id':m['attempt_id'],'manifest_version':f"v{m['manifest_version']}",'manifest_digest':m['_manifest_digest'],'predecessor':pred,'actor':actor(m),'timestamps':{'started_at':at,'ended_at':at},'transition':{'from':from_state,'to':to_state},'result':result,'reason_code':reason,'evidence':evidence or [],'stage_extension':stage or {}}
 t['integrity']={'digest':json_digest(t),'attestation_type':'sha256-non-cryptographic','attested_by':'fleet-wave-controller'};return t
def transition_path(base,index,to_state):return Path(base).parent/'transition-receipts'/f"{index:02d}-{to_state.lower().replace(' ','-')}.json"
def persist_transitions(base,chain):
 for i,item in enumerate(chain,1):write_receipt(transition_path(base,i,item['transition']['to']),item)
def transition_chain(m,states,claim_id,beads_version,evidence=None,existing=None):
 out=list(existing or []);start=states[0]
 for to_state in states[1:]:
  out.append(transition(m,start,to_state,out[-1] if out else None,claim_id,beads_version,evidence=(evidence or {}).get(to_state),stage={'state':to_state}));start=to_state
 return out
def validate_transitions(value,states,m,claim_id,beads_version):
 expected=list(zip(states,states[1:]))
 if not isinstance(value,list) or [x.get('transition') for x in value]!=[{'from':a,'to':b} for a,b in expected]:raise ProtocolError('receipt transition chain is incomplete, illegal, or out of order')
 if len({x.get('receipt_id') for x in value})!=len(value):raise ProtocolError('transition receipt IDs are not unique')
 prev=None
 for x in value:
  required={'schema_version','protocol_version','receipt_id','receipt_type','authority','work_id','beads_issue_version','claim_id','attempt_id','manifest_version','manifest_digest','predecessor','actor','timestamps','transition','result','reason_code','evidence','stage_extension','integrity'}
  if not isinstance(x,dict) or set(x)!=required or x['schema_version']!='fleet-wave.v1' or x['protocol_version']!='1.0.0' or x['receipt_type']!='state-transition' or x['result']!='PASS':raise ProtocolError('invalid complete transition receipt')
  if x['authority']!=authority(m) or x['work_id']!=m['beads']['issue_id'] or x['attempt_id']!=m['attempt_id'] or x['manifest_version']!=f"v{m['manifest_version']}" or x['manifest_digest']!=m['_manifest_digest'] or x['claim_id']!=claim_id or x['beads_issue_version']!=beads_version:raise ProtocolError('transition receipt binding mismatch')
  exact(x['actor'],{'identity','role','service','host','execution_id','session_id','model','attestation'},'transition actor');exact(x['timestamps'],{'started_at','ended_at'},'transition timestamps')
  if not all(nonempty(x['actor'][k]) for k in ('identity','role','service','host','execution_id')) or not isinstance(x['actor']['attestation'],dict) or not isinstance(x['stage_extension'],dict) or not isinstance(x['evidence'],list):raise ProtocolError('invalid transition actor, evidence, or extension')
  for ev in x['evidence']:
   exact(ev,{'class','uri','digest','size_bytes','provenance','observed_at','freshness'},'typed evidence')
   if ev['class'] not in {'E0','E1','E2','E3','E4','E5'} or not nonempty(ev['uri']) or not sha(ev['digest']) or type(ev['size_bytes']) is not int or ev['size_bytes']<0 or not isinstance(ev['provenance'],dict):raise ProtocolError('invalid typed evidence')
   dt(ev['observed_at'])
   if ev['uri'].startswith('file://'):
    q=Path(ev['uri'][7:]);
    if not q.is_file() or digest(q)!=ev['digest'] or q.stat().st_size!=ev['size_bytes']:raise ProtocolError('evidence artifact binding mismatch')
  validate_integrity(x);dt(x['timestamps']['started_at']);dt(x['timestamps']['ended_at'])
  expected_pred={'receipt_id':None,'digest':None} if prev is None else {'receipt_id':prev['receipt_id'],'digest':receipt_digest(prev)}
  if x.get('predecessor')!=expected_pred:raise ProtocolError('broken transition predecessor chain')
  prev=x
def write_projection_receipt(base,suffix,value):write_receipt(str(Path(base).with_suffix(Path(base).suffix+suffix)),value)
def degraded(base,m,stage,error,predecessor=None):
 rec={'schema_version':'fleet-wave.v1','event':'projection_degraded','at':now(),'attempt_id':m['attempt_id'],'stage':stage,'error':str(error),'predecessor_digest':predecessor,'idempotency_key':f"{m['attempt_id']}:{stage}:projection_degraded"};rec['integrity']={'digest':json_digest(rec)};write_projection_receipt(base,f'.{stage}-projection-degraded.json',rec)
def validate_manifest(m,path):
 allowed={'schema_version','manifest_version','wave_id','attempt_id','supersedes','run_name','workdir','max_parallel','ringer_manifest','ringer_state_dir','beads','paperclip','ringside','bifrost','tasks'}
 required={'schema_version','manifest_version','wave_id','attempt_id','supersedes','ringer_manifest','ringer_state_dir','beads','tasks'}
 if set(m)-allowed or required-set(m):raise ProtocolError('invalid manifest object shape')
 if m['schema_version']!='fleet-wave.v1' or type(m['manifest_version']) is not int or m['manifest_version']<1 or not nonempty(m['wave_id']) or not nonempty(m['attempt_id']):raise ProtocolError('invalid Fleet Wave identity/version/attempt')
 for k in ('ringer_manifest','ringer_state_dir'):
  if not nonempty(m[k]):raise ProtocolError(f'invalid {k}')
 if 'run_name' in m and not nonempty(m['run_name']) or 'workdir' in m and not nonempty(m['workdir']) or 'max_parallel' in m and (type(m['max_parallel']) is not int or m['max_parallel']<1):raise ProtocolError('invalid optional manifest field')
 n=m['manifest_version'];match=re.fullmatch(r'manifest-v(\d+)\.json',path.name)
 if not match or int(match.group(1))!=n:raise ProtocolError(f'manifest filename must be manifest-v{n}.json')
 if n==1:
  if m['supersedes'] is not None:raise ProtocolError('manifest-v1.json must not supersede')
 else:
  s=m['supersedes'];exact(s,{'path','sha256'},'supersedes')
  if not nonempty(s['path']) or not sha(s['sha256']):raise ProtocolError('invalid supersedes binding')
  prior=resolve(path.parent,s['path']).resolve();expected=path.with_name(f'manifest-v{n-1}.json').resolve()
  if prior!=expected or not prior.is_file() or digest(prior)!=s['sha256']:raise ProtocolError('superseded manifest path/hash mismatch')
  old=load(prior)
  if old.get('wave_id')!=m['wave_id'] or old.get('manifest_version')!=n-1:raise ProtocolError('invalid supersession chain')
 b=m['beads'];exact(b,{'host','store','claimant','issue_id','existing_ids'},'beads')
 if not all(nonempty(b[k]) for k in ('host','store','claimant','issue_id')) or not strings(b['existing_ids'],True) or b['issue_id'] in b['existing_ids']:raise ProtocolError('invalid Beads authority')
 for name in ('paperclip',):
  if name in m:
   x=m[name];exact(x,{'issue_id','existing_ids'},name)
   if not nonempty(x['issue_id']) or not strings(x['existing_ids'],True) or x['issue_id'] in x['existing_ids']:raise ProtocolError(f'invalid {name}')
 if 'ringside' in m:
  exact(m['ringside'],{'base_url'},'ringside')
  if not nonempty(m['ringside']['base_url']):raise ProtocolError('invalid Ringside URL')
 if 'bifrost' in m:
  exact(m['bifrost'],{'correlation'},'bifrost')
  if m['bifrost']['correlation'] is not None:raise ProtocolError('Bifrost correlation must be null/unproven')
 tasks=m['tasks']
 if not isinstance(tasks,list) or not tasks:raise ProtocolError('tasks must be non-empty')
 keys=[]
 for t in tasks:
  allowed_t={'key','work_type','spec','check','expect_files','verified','negative_controls','evidence'};required_t={'key','work_type','check','negative_controls','evidence'}
  if not isinstance(t,dict) or set(t)-allowed_t or required_t-set(t) or not nonempty(t['key']) or t['work_type'] not in {'code','deployment','config','factual-research','other'}:raise ProtocolError('invalid task shape')
  for k in ('spec','check','verified'):
   if k in t and not nonempty(t[k]):raise ProtocolError(f'invalid task {k}')
  if 'expect_files' in t and not strings(t['expect_files'],True):raise ProtocolError('invalid expect_files')
  controls=t['negative_controls']
  if not isinstance(controls,list) or len(controls)<2:raise ProtocolError('at least two executable negative controls required')
  for control in controls:
   exact(control,{'name','setup'},'negative control')
   if not nonempty(control['name']) or not nonempty(control['setup']):raise ProtocolError('invalid executable negative control')
  if len({x['name'] for x in controls})!=len(controls):raise ProtocolError('duplicate negative control')
  check=t['check'].strip().lower()
  if check in {'true','exit 0',':'} or re.fullmatch(r'test\s+-(?:e|f|s)\s+[^;&|]+',check):raise ProtocolError('existence-only or unconditional check is not strong evidence')
  exact(t['evidence'],{'strength','kind'},'evidence')
  if t['evidence']['strength']!='strong' or t['evidence']['kind'] not in {'objective','judgmental'}:raise ProtocolError('strong objective/judgmental evidence required')
  keys.append(t['key'])
 if len(keys)!=len(set(keys)):raise ProtocolError('duplicate task key')
 rp=resolve(path.parent,m['ringer_manifest']).resolve();r=load(rp);rt=r.get('tasks')
 if not isinstance(rt,list):raise ProtocolError('invalid Ringer tasks')
 rkeys=[x.get('key') for x in rt if isinstance(x,dict)]
 if set(keys)!=set(rkeys) or len(keys)!=len(rkeys):raise ProtocolError('Fleet/Ringer task keys differ')
 rby={x['key']:x for x in rt}
 for t in tasks:
  if rby[t['key']].get('check')!=t['check']:raise ProtocolError('Fleet/Ringer strong checks differ')
 return rp
def context(a):
 p=Path(a.manifest).resolve();m=load(p);rp=validate_manifest(m,p);b=m['beads']
 if a.beads_host!=socket.gethostname() or (a.beads_host,a.beads_store,a.beads_claimant)!=(b['host'],b['store'],b['claimant']):raise ProtocolError('Beads authority does not match actual host/manifest store/claimant')
 m['_manifest_digest']=digest(p)
 return p,m,rp
def validate_prepared_receipt(r,m):
 required={'schema_version','event','prepared_at','wave_id','manifest_sha256','ringer_manifest_sha256','beads_authority','dispatch_authorized','claim_proof','transitions','protocol_version','receipt_id','receipt_type','authority','work_id','beads_issue_version','claim_id','attempt_id','manifest_version','manifest_digest','predecessor','actor','timestamps','transition','result','reason_code','evidence','integrity','stage_extension'}
 exact(r,required,'prepared receipt')
 if r['schema_version']!='fleet-wave.v1' or r['event']!='prepared' or not nonempty(r['wave_id']) or not sha(r['manifest_sha256']) or not sha(r['ringer_manifest_sha256']) or r['dispatch_authorized'] is not True:raise ProtocolError('invalid prepared receipt fields')
 dt(r['prepared_at'])
 if r['beads_authority']!=m['beads']:raise ProtocolError('prepared receipt authority mismatch')
 if r['claim_id']!=r['claim_proof'].get('evidence_digest') or r['beads_issue_version']!=r['claim_proof'].get('updated_at') or r['claim_proof'].get('lease_supported') is not False:raise ProtocolError('prepared receipt claim binding mismatch')
 validate_transitions(r['transitions'],['INTAKE','LEDGERED','CLAIMED',f"MANIFEST-v{m['manifest_version']}",'LINTED','DRY-RUN','PAPERCLIP PREPARED RECEIPT'],m,r['claim_id'],r['beads_issue_version'])
def validate_execute_receipt(r):
 required={'schema_version','event','executed_at','wave_id','manifest_sha256','ringer_manifest_sha256','prepared_receipt_sha256','run_state_path','run_state_sha256','replay_inputs','transitions','protocol_version','receipt_id','receipt_type','authority','work_id','beads_issue_version','claim_id','attempt_id','manifest_version','manifest_digest','predecessor','actor','timestamps','transition','result','reason_code','evidence','integrity','stage_extension'}
 exact(r,required,'execute receipt')
 if r['schema_version']!='fleet-wave.v1' or r['event']!='executed' or not nonempty(r['wave_id']) or not sha(r['manifest_sha256']) or not sha(r['ringer_manifest_sha256']) or not sha(r['prepared_receipt_sha256']) or not nonempty(r['run_state_path']) or not sha(r['run_state_sha256']):raise ProtocolError('invalid execute receipt fields')
 dt(r['executed_at'])
def binding(p,m,rp,r,event):
 if r.get('event')!=event or r.get('wave_id')!=m['wave_id'] or r.get('manifest_sha256')!=digest(p) or r.get('ringer_manifest_sha256')!=digest(rp):raise ProtocolError(f'{event} receipt binding mismatch')
def validate_integrity(r):
 i=r.get('integrity');exact(i,{'digest','attestation_type','attested_by'},'integrity')
 if i['digest']!=json_digest({k:v for k,v in r.items() if k!='integrity'}):raise ProtocolError('receipt canonical integrity mismatch')
def inventory_tree(root):
 out=[]
 for q in sorted(root.rglob('*')):
  if q.is_symlink():raise ProtocolError('replay inputs may not contain symlinks')
  if q.is_file():out.append({'path':q.relative_to(root).as_posix(),'size':q.stat().st_size,'mode':q.stat().st_mode&0o777,'sha256':digest(q)})
  elif not q.is_dir():raise ProtocolError('replay inputs contain unsupported file type')
 return out
def snapshot_tasks(base,m,state):
 root=Path(str(base)+'.cas');root.mkdir(parents=True,exist_ok=True);result={};by={x['key']:x for x in state['tasks']}
 for t in m['tasks']:
  src=Path(by[t['key']]['taskdir']).resolve();inv=inventory_tree(src);tree=json_digest(inv);dst=root/tree
  if not dst.exists():shutil.copytree(src,dst)
  if inventory_tree(dst)!=inv:raise ProtocolError('content-addressed replay snapshot mismatch')
  result[t['key']]={'tree_digest':tree,'inventory':inv,'path':str(dst)}
 return result
def replay_child(a):
 root=Path(a.snapshot).resolve();inv=json.loads(Path(a.inventory).read_text())
 if inventory_tree(root)!=inv or json_digest(inv)!=a.tree_digest:raise ProtocolError('replay CAS validation failed')
 with tempfile.TemporaryDirectory(prefix='fleet-wave-independent-') as d:
  task=Path(d)/'task';shutil.copytree(root,task)
  r=sandboxed_shell(a.check,task,d,a.sandbox_bin)
  write_receipt(a.output,{'checker':{'principal':'fleet-wave-independent-replay','session_id':str(os.getpid()),'parent_pid':os.getppid()},'tree_digest':a.tree_digest,'exit_status':r.returncode,'stdout_sha256':hashlib.sha256(r.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(r.stderr.encode()).hexdigest(),'sandbox':r.sandbox_metadata})
  if r.returncode:raise ProtocolError('independent replay check failed')
def prepare(a):
 p,m,rp=context(a);b=m['beads']
 try:claim_item=claim(a,m)
 except ProtocolError as e:
  rec={'schema_version':'fleet-wave.v1','event':'claim_unknown_degraded','prepared_at':now(),'wave_id':m['wave_id'],'manifest_sha256':digest(p),'ringer_manifest_sha256':digest(rp),'beads_authority':b,'dispatch_authorized':False}
  enrich(rec,m,'degraded-prepare','INTAKE','UNKNOWN_DEGRADED',result='DEGRADED',reason='claim_error',stage={'claim_state':'UNKNOWN_DEGRADED','dispatch_allowed':False,'authoritative':False,'error':str(e)});rec['claim_id']=None;rec['integrity']={'digest':json_digest({k:v for k,v in rec.items() if k!='integrity'}),'attestation_type':'sha256-non-cryptographic','attested_by':'fleet-wave-controller'};write_receipt(a.receipt,rec)
  raise
 paperclip_readbacks=[]
 for x in b['existing_ids']:
  item=parse_item(bd(a,'show',x).stdout)
  if item.get('id')!=x:raise ProtocolError(f'Beads existing ID readback mismatch: {x}')
 if 'paperclip' in m:
  if not a.paperclip_bin:raise ProtocolError('Paperclip executable required')
  for x in [m['paperclip']['issue_id'],*m['paperclip']['existing_ids']]:
   item=parse_item(run([a.paperclip_bin,'show',x,'--json']).stdout,'Paperclip')
   canonical=item.get('id');identifier=item.get('identifier')
   if x not in (canonical,identifier):raise ProtocolError(f'Paperclip ID readback mismatch: {x}')
   paperclip_readbacks.append({'requested':x,'identifier':identifier,'canonical_id':canonical})
 run([a.ringer_bin,'lint',str(rp)]);run([a.ringer_bin,'run',str(rp),'--dry-run'])
 names=['INTAKE','LEDGERED','CLAIMED',f"MANIFEST-v{m['manifest_version']}",'LINTED','DRY-RUN','PAPERCLIP PREPARED RECEIPT']
 rec={'schema_version':'fleet-wave.v1','event':'prepared','prepared_at':now(),'wave_id':m['wave_id'],'manifest_sha256':digest(p),'ringer_manifest_sha256':digest(rp),'beads_authority':b,'dispatch_authorized':True,'claim_proof':claim_item,'transitions':transition_chain(m,names,claim_item['evidence_digest'],claim_item['updated_at'])}
 enrich(rec,m,'prepared','DRY-RUN','PAPERCLIP PREPARED RECEIPT',stage={'paperclip_readbacks':paperclip_readbacks,'mirrored_beads_snapshot_digest':json_digest(b),'execution_envelope_digest':digest(rp)})
 rec['claim_id']=claim_item['evidence_digest'];rec['beads_issue_version']=claim_item['updated_at'];rec['integrity']={'digest':json_digest({k:v for k,v in rec.items() if k!='integrity'}),'attestation_type':'sha256-non-cryptographic','attested_by':'fleet-wave-controller'}
 persist_transitions(a.receipt,rec['transitions']);write_receipt(a.receipt,rec)
 if 'paperclip' in m:
  payload=json.dumps(rec,sort_keys=True);posted=parse_item(run([a.paperclip_bin,'comment',m['paperclip']['issue_id'],payload,'--idempotency-key',rec['receipt_id'],'--json']).stdout,'Paperclip')
  if posted.get('payload_sha256')!=hashlib.sha256(payload.encode()).hexdigest() or posted.get('issue_id') not in (paperclip_readbacks[0]['identifier'],paperclip_readbacks[0]['canonical_id']):raise ProtocolError('Paperclip prepared receipt readback mismatch')
def execute(a):
 p,m,rp=context(a);prep=load(a.prepared_receipt);validate_prepared_receipt(prep,m);validate_integrity(prep);binding(p,m,rp,prep,'prepared');live=claim(a,m)
 runs=resolve(p.parent,m['ringer_state_dir']).resolve()/'runs';before={x.resolve():digest(x) for x in runs.glob('*.json')} if runs.is_dir() else {}
 run([a.ringer_bin,'run',str(rp)])
 after={x.resolve():digest(x) for x in runs.glob('*.json')} if runs.is_dir() else {}
 if any(after.get(k)!=v for k,v in before.items()):raise ProtocolError('Ringer overwrote an existing run-state receipt')
 new=set(after)-set(before)
 if len(new)!=1:raise ProtocolError(f'Ringer must create exactly one new run-state receipt; found {len(new)}')
 state=next(iter(new));snapshots=snapshot_tasks(a.receipt,m,load(state));chain=transition_chain(m,['PAPERCLIP PREPARED RECEIPT','RINGER RUN'],live['evidence_digest'],live['updated_at'],existing=prep['transitions']);rec={'schema_version':'fleet-wave.v1','event':'executed','executed_at':now(),'wave_id':m['wave_id'],'manifest_sha256':digest(p),'ringer_manifest_sha256':digest(rp),'prepared_receipt_sha256':digest(a.prepared_receipt),'run_state_path':str(state),'run_state_sha256':digest(state),'replay_inputs':snapshots,'transitions':chain}
 enrich(rec,m,'executed','PAPERCLIP PREPARED RECEIPT','RINGER RUN',predecessor={'receipt_id':prep['receipt_id'],'digest':digest(a.prepared_receipt)},stage={'run_state_path':str(state),'run_state_sha256':digest(state)})
 rec['claim_id']=live['evidence_digest'];rec['beads_issue_version']=live['updated_at'];rec['integrity']={'digest':json_digest({k:v for k,v in rec.items() if k!='integrity'}),'attestation_type':'sha256-non-cryptographic','attested_by':'fleet-wave-controller'}
 persist_transitions(a.receipt,rec['transitions']);write_receipt(a.receipt,rec)
def validate_state(s,keys):
 if not nonempty(s.get('run_id')):raise ProtocolError('Ringer run_id must be a nonempty scalar string')
 if s.get('state')!='finished' or s.get('finished') is not True or s.get('fail')!=0 or s.get('pass')!=len(keys):raise ProtocolError('Ringer state is not a finished all-pass run')
 for name in ('totals','summary'):
  x=s.get(name)
  if not isinstance(x,dict) or x.get('pass')!=len(keys) or x.get('fail')!=0:raise ProtocolError(f'invalid Ringer {name}')
 if s['totals'].get('running')!=0 or s['totals'].get('done')!=len(keys):raise ProtocolError('invalid Ringer finished totals')
 tasks=s.get('tasks')
 if not isinstance(tasks,list) or len(tasks)!=len(keys):raise ProtocolError('invalid Ringer tasks')
 by={x.get('key'):x for x in tasks if isinstance(x,dict)}
 if set(by)!=set(keys):raise ProtocolError('Ringer state task mismatch')
 for k,x in by.items():
  if x.get('status')!='pass' or x.get('verdict')!='PASS' or x.get('check_returncode')!=0:raise ProtocolError(f'Ringer task is not exact pass: {k}')
 return by
def dt(v):
 try:d=datetime.fromisoformat(v.replace('Z','+00:00'))
 except (AttributeError,ValueError) as e:raise ProtocolError('invalid timestamp') from e
 if d.tzinfo is None:raise ProtocolError('timestamp must be timezone-aware')
 return d
def recursively_contains(value,target):
 if value==target:return True
 if isinstance(value,dict):return any(recursively_contains(x,target) for x in value.values())
 if isinstance(value,list):return any(recursively_contains(x,target) for x in value)
 return False
def accept(a):
 controller_now=datetime.now(timezone.utc)
 p,m,rp=context(a);prep=load(a.prepared_receipt);validate_prepared_receipt(prep,m);validate_integrity(prep);binding(p,m,rp,prep,'prepared');ex=load(a.execute_receipt);validate_execute_receipt(ex);validate_integrity(ex);validate_transitions(ex['transitions'],['INTAKE','LEDGERED','CLAIMED',f"MANIFEST-v{m['manifest_version']}",'LINTED','DRY-RUN','PAPERCLIP PREPARED RECEIPT','RINGER RUN'],m,ex['claim_id'],ex['beads_issue_version']);binding(p,m,rp,ex,'executed')
 if ex.get('prepared_receipt_sha256')!=digest(a.prepared_receipt):raise ProtocolError('execute/prepared binding mismatch')
 sp=Path(str(ex.get('run_state_path',''))).resolve()
 runs=(resolve(p.parent,m['ringer_state_dir']).resolve()/'runs').resolve()
 if runs not in sp.parents:raise ProtocolError('run-state path is outside bound Ringer runs directory')
 if not sp.is_file() or digest(sp)!=ex.get('run_state_sha256'):raise ProtocolError('run-state hash mismatch')
 keys=[x['key'] for x in m['tasks']];fleet={x['key']:x for x in m['tasks']};by=validate_state(load(sp),keys);ringer={x['key']:x for x in load(rp)['tasks']};workroot=Path(load(rp).get('workdir',rp.parent)).resolve();replay={};check_execution={};clean_replay={}
 for k in keys:
  td=Path(str(by[k].get('taskdir',''))).resolve()
  if not td.is_dir() or td!=workroot and workroot not in td.parents:raise ProtocolError(f'path-unsafe taskdir: {k}')
  for item in ringer[k].get('expect_files',[]):
   if not nonempty(item):raise ProtocolError('invalid expected artifact path')
   q=(td/item).resolve()
   if td not in q.parents or not q.is_file() or not q.stat().st_size:raise ProtocolError(f'missing/path-unsafe expected artifact: {k}/{item}')
  command=ringer[k]['check'];snap=ex['replay_inputs'].get(k);expected_inv=inventory_tree(Path(snap['path']))
  if expected_inv!=snap['inventory'] or json_digest(expected_inv)!=snap['tree_digest']:raise ProtocolError('execute-bound replay input mismatch')
  with tempfile.TemporaryDirectory(prefix='fleet-wave-checker-receipt-') as out:
   inv=Path(out)/'inventory.json';inv.write_text(json.dumps(snap['inventory']));result=Path(out)/'result.json'
   run([replay_interpreter(),str(Path(__file__).resolve()),'replay-one','--snapshot',snap['path'],'--inventory',str(inv),'--tree-digest',snap['tree_digest'],'--check',command,'--output',str(result),'--sandbox-bin',a.sandbox_bin])
   rr=load(result)
  raw_digest=json_digest({'stdout_sha256':rr['stdout_sha256'],'stderr_sha256':rr['stderr_sha256']})
  replay[k]={'checker':rr['checker'],'tree_digest':rr['tree_digest']};check_execution[k]={'command':['/bin/sh','-c',command],'exit_status':rr['exit_status'],'tool_check_versions':[{'tool':'/bin/sh','sha256':digest('/bin/sh')},{'tool':'fleet_wave.py','sha256':digest(__file__)}],'environment_digest':rr['sandbox']['environment_digest'],'sandbox':rr['sandbox'],'machine_readable_result':{'verdict':'PASS','stdout_sha256':rr['stdout_sha256'],'stderr_sha256':rr['stderr_sha256']},'raw_output_digest':raw_digest};clean_replay[k]={'isolated_copy':True,'checker':rr['checker'],'tree_digest':rr['tree_digest'],'exit_status':rr['exit_status'],'negative_controls':[]}
  for control in fleet[k]['negative_controls']:
   with tempfile.TemporaryDirectory(prefix='fleet-wave-negative-') as neg:
    fixture=Path(neg)/'task';shutil.copytree(Path(snap['path']),fixture);setup=sandboxed_shell(control['setup'],fixture,neg,a.sandbox_bin)
    if setup.returncode:raise ProtocolError(f"negative control setup failed: {k}/{control['name']}")
    nr=sandboxed_shell(command,fixture,neg,a.sandbox_bin)
    if nr.returncode==0:raise ProtocolError(f"negative control did not fail strong check: {k}/{control['name']}")
    clean_replay[k]['negative_controls'].append({'name':control['name'],'setup':control['setup'],'observed_exit_status':nr.returncode,'raw_output_sha256':hashlib.sha256((nr.stdout+nr.stderr).encode()).hexdigest()})
 judge_hash=None;judgment=[x['key'] for x in m['tasks'] if x['evidence']['kind']=='judgmental']
 if judgment:
  if not a.judge_receipt or not nonempty(a.judge_nonce):raise ProtocolError('fresh judge attestation and caller nonce required')
  j=load(a.judge_receipt);required={'judge_id','session_id','model','harness_attestation','new_session','resumed','role_history','attempt_id','nonce','session_created_at','evidence_fetched_at','issued_at','judged_at','expires_at','criteria','rationale','task_keys','independent','verdict','wave_id','manifest_sha256','execute_receipt_sha256','run_state_sha256'};exact(j,required,'judge attestation')
  h=j['harness_attestation'];forbidden={'author','worker','executor','checker','replay_checker','deliberator'};secret=os.environ.get('FLEET_JUDGE_ATTESTATION_SECRET')
  unsigned={**j,'harness_attestation':{k:v for k,v in h.items() if k!='signature'}} if isinstance(h,dict) else {}
  harness_ok=isinstance(h,dict) and set(h)=={'attestation_id','provider','session_id','judge_id','issuer','signature'} and all(nonempty(h[x]) for x in h) and nonempty(secret) and hmac.compare_digest(h['signature'],hmac.new(secret.encode(),json.dumps(unsigned,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()) and h['session_id'].strip().casefold()==j['session_id'].strip().casefold() and h['judge_id'].strip().casefold()==j['judge_id'].strip().casefold()
  roles={str(x).strip().casefold() for x in j['role_history']} if isinstance(j['role_history'],list) else forbidden
  prior_principals={ex['actor']['identity'].strip().casefold(),*[x['checker']['principal'].strip().casefold() for x in replay.values()]};prior_sessions={str(ex['actor']['session_id']).strip().casefold(),*[x['checker']['session_id'].strip().casefold() for x in replay.values()]}
  executed_at=dt(ex['executed_at']);session_created_at=dt(j['session_created_at']);evidence_fetched_at=dt(j['evidence_fetched_at']);issued_at=dt(j['issued_at']);judged_at=dt(j['judged_at']);expires_at=dt(j['expires_at'])
  nonce_ok=nonempty(j['nonce']) and hmac.compare_digest(j['nonce'].encode(),a.judge_nonce.encode())
  fresh=executed_at<=session_created_at<=evidence_fetched_at<=issued_at<=judged_at<expires_at and judged_at<=controller_now+timedelta(seconds=30) and controller_now-judged_at<=timedelta(minutes=5) and expires_at>controller_now and expires_at-issued_at<=timedelta(minutes=10)
  if not nonempty(j['judge_id']) or not nonempty(j['session_id']) or j['judge_id'].strip().casefold() in prior_principals or j['session_id'].strip().casefold() in prior_sessions or not nonempty(j['model']) or not harness_ok or j['new_session'] is not True or j['resumed'] is not False or forbidden.intersection(roles) or not strings(j['criteria'],True) or not nonempty(j['rationale']) or j['task_keys']!=judgment or j['independent'] is not True or j['verdict']!='PASS' or j['wave_id']!=m['wave_id'] or j['attempt_id']!=m['attempt_id'] or j['manifest_sha256']!=digest(p) or j['execute_receipt_sha256']!=digest(a.execute_receipt) or j['run_state_sha256']!=digest(sp) or not nonce_ok or not fresh:raise ProtocolError('invalid/stale/conflicted judge attestation')
  judge_hash=digest(a.judge_receipt)
 evidence_dir=Path(a.receipt).parent/'evidence';observed=now();evidence_entries=[];e3_digests={}
 for key in keys:
  artifact={'schema_version':'fleet-wave-e3.v1','class':'E3','work_id':m['beads']['issue_id'],'attempt_id':m['attempt_id'],'manifest_digest':digest(p),'task_key':key,'cas_tree_digest':ex['replay_inputs'][key]['tree_digest'],'input_inventory_digest':json_digest(ex['replay_inputs'][key]['inventory']),'check_execution':check_execution[key],'observed_at':observed}
  path=evidence_dir/f"e3-{key}.json";write_receipt(path,artifact);e3_digests[key]=digest(path);evidence_entries.append({'class':'E3','uri':path.resolve().as_uri(),'digest':digest(path),'size_bytes':path.stat().st_size,'provenance':{'producer':'fleet-wave-independent-replay','task_key':key,'cas_tree_digest':artifact['cas_tree_digest']},'observed_at':observed,'freshness':{'basis':'acceptance-run','status':'fresh'}})
 e4={'schema_version':'fleet-wave-e4.v1','class':'E4','work_id':m['beads']['issue_id'],'attempt_id':m['attempt_id'],'manifest_digest':digest(p),'execute_receipt_digest':digest(a.execute_receipt),'run_state_digest':digest(sp),'e3_artifact_digests':e3_digests,'cas_tree_digests':{k:ex['replay_inputs'][k]['tree_digest'] for k in keys},'input_inventory_digests':{k:json_digest(ex['replay_inputs'][k]['inventory']) for k in keys},'checker_receipts':replay,'sandbox_policy':{k:check_execution[k]['sandbox'] for k in keys},'observed_at':observed}
 e4_path=evidence_dir/'e4-independent-replay.json';write_receipt(e4_path,e4);evidence_entries.append({'class':'E4','uri':e4_path.resolve().as_uri(),'digest':digest(e4_path),'size_bytes':e4_path.stat().st_size,'provenance':{'producer':'fleet-wave-controller','e3_artifact_digests':e3_digests},'observed_at':observed,'freshness':{'basis':'acceptance-run','status':'fresh'}})
 chain=transition_chain(m,['RINGER RUN','INDEPENDENT CHECK REPLAY'],ex['claim_id'],ex['beads_issue_version'],evidence={'INDEPENDENT CHECK REPLAY':evidence_entries},existing=ex['transitions'])
 if judgment:chain=transition_chain(m,['INDEPENDENT CHECK REPLAY','FRESH JUDGE'],ex['claim_id'],ex['beads_issue_version'],existing=chain)
 chain=transition_chain(m,[chain[-1]['transition']['to'],'BEADS ACCEPTED'],ex['claim_id'],ex['beads_issue_version'],existing=chain)
 final_states=['INTAKE','LEDGERED','CLAIMED',f"MANIFEST-v{m['manifest_version']}",'LINTED','DRY-RUN','PAPERCLIP PREPARED RECEIPT','RINGER RUN','INDEPENDENT CHECK REPLAY']+(['FRESH JUDGE'] if judgment else [])+['BEADS ACCEPTED'];validate_transitions(chain,final_states,m,ex['claim_id'],ex['beads_issue_version'])
 rec={'schema_version':'fleet-wave.v1','event':'accepted','accepted_at':now(),'wave_id':m['wave_id'],'manifest_sha256':digest(p),'ringer_manifest_sha256':digest(rp),'execute_receipt_sha256':digest(a.execute_receipt),'run_state_sha256':digest(sp),'independent_replay':replay,'check_execution':check_execution,'clean_replay':clean_replay,'judge_receipt_sha256':judge_hash,'bifrost_correlation':None,'ringside_read_only':[],'accept_mode':'close','beads_close_reason':None,'authoritative_disposition':'accepted','transitions':chain}
 terminal_state='BEADS ACCEPTED'
 enrich(rec,m,'terminal','FRESH JUDGE' if judgment else 'INDEPENDENT CHECK REPLAY',terminal_state,predecessor={'receipt_id':ex['receipt_id'],'digest':digest(a.execute_receipt)},stage={'policy_evaluation':'all mandatory checks passed','accepted_evidence_set':[digest(sp)],'unresolved_discrepancy_count':0,'sandbox_policy':{k:check_execution[k]['sandbox'] for k in keys}})
 close_reason=f"Fleet Wave accepted: wave_id={m['wave_id']}; manifest_sha256={digest(p)}; execute_receipt_sha256={digest(a.execute_receipt)}"
 rec['beads_close_reason']=close_reason
 rec['claim_id']=ex['claim_id'];rec['beads_issue_version']=ex['beads_issue_version']
 # Finalize before any authority/projection write.  This object is never mutated.
 rec['integrity']={'digest':json_digest({k:v for k,v in rec.items() if k!='integrity'}),'attestation_type':'sha256-non-cryptographic','attested_by':'fleet-wave-controller'}
 persist_transitions(a.receipt,chain)
 summary=json.dumps(rec,sort_keys=True);issue=m['beads']['issue_id'];bd(a,'comments','add',issue,summary)
 bd(a,'close',issue,'--reason',close_reason);show_disposition(a,m,'closed')
 write_receipt(a.receipt,rec);terminal_digest=digest(a.receipt)
 if 'paperclip' in m:
  try:
   if not a.paperclip_bin:raise ProtocolError('Paperclip executable required after terminal truth')
   run([a.paperclip_bin,'comment',m['paperclip']['issue_id'],summary]);rb=parse_item(run([a.paperclip_bin,'show',m['paperclip']['issue_id'],'--json']).stdout,'Paperclip')
   if m['paperclip']['issue_id'] not in (rb.get('id'),rb.get('identifier')):raise ProtocolError('Paperclip mirror readback identity mismatch')
   pr={'schema_version':'fleet-wave.v1','event':'paperclip_mirrored','at':now(),'terminal_receipt_sha256':terminal_digest,'payload_sha256':hashlib.sha256(summary.encode()).hexdigest(),'readback':rb};pr['integrity']={'digest':json_digest(pr)};write_projection_receipt(a.receipt,'.paperclip.json',pr)
  except ProtocolError as e:degraded(a.receipt,m,'paperclip',e,terminal_digest);raise ProtocolError(f'projection_degraded: {e}') from e
 if 'ringside' in m:
  try:
   if not a.ringside_bin:raise ProtocolError('Ringside executable required after terminal truth')
   base=m['ringside']['base_url'].rstrip('/');run_id=load(sp).get('run_id')
   if not nonempty(run_id):raise ProtocolError('Ringer run_id must be a nonempty scalar string')
   observations=[]
   for endpoint in ('/api/runs','/api/library'):
    raw=run([a.ringside_bin,'get',base+endpoint]).stdout;value=parse_item(raw,'Ringside')
    if not recursively_contains(value,run_id):raise ProtocolError(f'Ringside {endpoint} lacks exact run id')
    observations.append({'endpoint':endpoint,'response':value,'response_sha256':hashlib.sha256(raw.encode()).hexdigest(),'run_id':run_id})
   rr={'schema_version':'fleet-wave.v1','event':'ringside_observed','at':now(),'terminal_receipt_sha256':terminal_digest,'observations':observations};rr['integrity']={'digest':json_digest(rr)};write_projection_receipt(a.receipt,'.ringside.json',rr)
  except ProtocolError as e:degraded(a.receipt,m,'ringside',e,terminal_digest);raise ProtocolError(f'projection_degraded: {e}') from e
def block(a):
 p,m,rp=context(a);pred=load(a.predecessor_receipt);validate_integrity(pred)
 if pred.get('attempt_id')!=m['attempt_id'] or pred.get('manifest_digest')!=digest(p) or pred.get('authority')!=authority(m):raise ProtocolError('blocked predecessor binding mismatch')
 if not nonempty(a.reason_code):raise ProtocolError('reason code must be nonempty')
 failed=f"MANIFEST-v{m['manifest_version']}" if a.failed_stage=='MANIFEST-vN' else a.failed_stage
 try:live=claim(a,m);authoritative=True;claim_error=None
 except ProtocolError as e:authoritative=False;claim_error=str(e);live=None
 rec={'schema_version':'fleet-wave.v1','event':'blocked' if authoritative else 'local_incident','accepted_at':now(),'wave_id':m['wave_id'],'manifest_sha256':digest(p),'ringer_manifest_sha256':digest(rp)}
 enrich(rec,m,'terminal-blocked',failed,'BEADS BLOCKED' if authoritative else 'UNKNOWN_DEGRADED',predecessor={'receipt_id':pred.get('receipt_id'),'digest':digest(a.predecessor_receipt)},result='BLOCKED' if authoritative else 'DEGRADED',reason=a.reason_code,stage={'policy_evaluation':'fail-closed','failed_stage':failed,'unresolved_discrepancy_count':1,'authoritative':authoritative,'claim_error':claim_error})
 rec['claim_id']=live['evidence_digest'] if live else None;rec['beads_issue_version']=live['updated_at'] if live else 'unavailable';rec['integrity']={'digest':json_digest({k:v for k,v in rec.items() if k!='integrity'}),'attestation_type':'sha256-non-cryptographic','attested_by':'fleet-wave-controller'}
 if authoritative:
  receipt=json.dumps(rec,sort_keys=True)
  validate_beads_item(parse_item(bd(a,'update',m['beads']['issue_id'],'--status','blocked','--append-notes',receipt,'--actor',m['beads']['claimant']).stdout),m,'blocked',active=False)
  show_disposition(a,m,'blocked')
 write_receipt(a.receipt,rec)
def parser():
 c=argparse.ArgumentParser(add_help=False)
 for x in ('manifest',):c.add_argument(x)
 for x in ('--bd-bin','--ringer-bin','--beads-host','--beads-store','--beads-claimant','--receipt'):c.add_argument(x,required=True)
 c.add_argument('--paperclip-bin');c.add_argument('--ringside-bin');c.add_argument('--sandbox-bin',default='/usr/bin/sandbox-exec' if sys.platform=='darwin' else None);root=argparse.ArgumentParser(description=__doc__);subs=root.add_subparsers(dest='command',required=True);subs.add_parser('prepare',parents=[c]);e=subs.add_parser('execute',parents=[c]);e.add_argument('--prepared-receipt',required=True);a=subs.add_parser('accept',parents=[c]);a.add_argument('--prepared-receipt',required=True);a.add_argument('--execute-receipt',required=True);a.add_argument('--judge-receipt');a.add_argument('--judge-nonce');b=subs.add_parser('block',parents=[c]);b.add_argument('--predecessor-receipt',required=True);b.add_argument('--failed-stage',required=True,choices=['INTAKE','LEDGERED','CLAIMED','MANIFEST-vN','LINTED','DRY-RUN','PAPERCLIP PREPARED RECEIPT','RINGER RUN','INDEPENDENT CHECK REPLAY','FRESH JUDGE']);b.add_argument('--reason-code',required=True);r=subs.add_parser('replay-one');r.add_argument('--snapshot',required=True);r.add_argument('--inventory',required=True);r.add_argument('--tree-digest',required=True);r.add_argument('--check',required=True);r.add_argument('--output',required=True);r.add_argument('--sandbox-bin',default='/usr/bin/sandbox-exec' if sys.platform=='darwin' else None);return root
def main(argv=None):
 a=parser().parse_args(argv)
 try:{'prepare':prepare,'execute':execute,'accept':accept,'block':block,'replay-one':replay_child}[a.command](a)
 except (ProtocolError,OSError,ValueError,KeyError,TypeError) as e:print(f'fleet-wave: {e}',file=sys.stderr);return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
