#!/usr/bin/env python3
"""Fail-closed Fleet Wave v1 controller (stdlib only)."""
from __future__ import annotations
import argparse, hashlib, json, os, re, socket, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
class ProtocolError(RuntimeError): pass
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
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
 try:
  with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
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
def claim(a,m,status='in_progress'):
 issue=m['beads']['issue_id'];item=parse_item(bd(a,'show',issue).stdout)
 if item.get('id')!=issue or item.get('status')!=status or item.get('assignee')!=m['beads']['claimant']:raise ProtocolError('Beads readback does not exactly match issue, status, and claimant')
 return item
def validate_manifest(m,path):
 allowed={'schema_version','manifest_version','wave_id','supersedes','run_name','workdir','max_parallel','ringer_manifest','ringer_state_dir','beads','paperclip','ringside','bifrost','tasks'}
 required={'schema_version','manifest_version','wave_id','supersedes','ringer_manifest','ringer_state_dir','beads','tasks'}
 if set(m)-allowed or required-set(m):raise ProtocolError('invalid manifest object shape')
 if m['schema_version']!='fleet-wave.v1' or type(m['manifest_version']) is not int or m['manifest_version']<1 or not nonempty(m['wave_id']):raise ProtocolError('invalid Fleet Wave identity/version')
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
  allowed_t={'key','work_type','spec','check','expect_files','verified','evidence'};required_t={'key','work_type','evidence'}
  if not isinstance(t,dict) or set(t)-allowed_t or required_t-set(t) or not nonempty(t['key']) or t['work_type'] not in {'code','deployment','config','factual-research','other'}:raise ProtocolError('invalid task shape')
  for k in ('spec','check','verified'):
   if k in t and not nonempty(t[k]):raise ProtocolError(f'invalid task {k}')
  if 'expect_files' in t and not strings(t['expect_files'],True):raise ProtocolError('invalid expect_files')
  exact(t['evidence'],{'strength','kind'},'evidence')
  if t['evidence']['strength']!='strong' or t['evidence']['kind'] not in {'objective','judgmental'}:raise ProtocolError('strong objective/judgmental evidence required')
  keys.append(t['key'])
 if len(keys)!=len(set(keys)):raise ProtocolError('duplicate task key')
 rp=resolve(path.parent,m['ringer_manifest']).resolve();r=load(rp);rt=r.get('tasks')
 if not isinstance(rt,list):raise ProtocolError('invalid Ringer tasks')
 rkeys=[x.get('key') for x in rt if isinstance(x,dict)]
 if set(keys)!=set(rkeys) or len(keys)!=len(rkeys):raise ProtocolError('Fleet/Ringer task keys differ')
 return rp
def context(a):
 p=Path(a.manifest).resolve();m=load(p);rp=validate_manifest(m,p);b=m['beads']
 if a.beads_host!=socket.gethostname() or (a.beads_host,a.beads_store,a.beads_claimant)!=(b['host'],b['store'],b['claimant']):raise ProtocolError('Beads authority does not match actual host/manifest store/claimant')
 return p,m,rp
def validate_prepared_receipt(r,m):
 exact(r,{'schema_version','event','prepared_at','wave_id','manifest_sha256','ringer_manifest_sha256','beads_authority','dispatch_authorized'},'prepared receipt')
 if r['schema_version']!='fleet-wave.v1' or r['event']!='prepared' or not nonempty(r['wave_id']) or not sha(r['manifest_sha256']) or not sha(r['ringer_manifest_sha256']) or r['dispatch_authorized'] is not True:raise ProtocolError('invalid prepared receipt fields')
 dt(r['prepared_at'])
 if r['beads_authority']!=m['beads']:raise ProtocolError('prepared receipt authority mismatch')
def validate_execute_receipt(r):
 exact(r,{'schema_version','event','executed_at','wave_id','manifest_sha256','ringer_manifest_sha256','prepared_receipt_sha256','run_state_path','run_state_sha256'},'execute receipt')
 if r['schema_version']!='fleet-wave.v1' or r['event']!='executed' or not nonempty(r['wave_id']) or not sha(r['manifest_sha256']) or not sha(r['ringer_manifest_sha256']) or not sha(r['prepared_receipt_sha256']) or not nonempty(r['run_state_path']) or not sha(r['run_state_sha256']):raise ProtocolError('invalid execute receipt fields')
 dt(r['executed_at'])
def binding(p,m,rp,r,event):
 if r.get('event')!=event or r.get('wave_id')!=m['wave_id'] or r.get('manifest_sha256')!=digest(p) or r.get('ringer_manifest_sha256')!=digest(rp):raise ProtocolError(f'{event} receipt binding mismatch')
def prepare(a):
 p,m,rp=context(a);b=m['beads'];claim(a,m)
 for x in b['existing_ids']:
  item=parse_item(bd(a,'show',x).stdout)
  if item.get('id')!=x:raise ProtocolError(f'Beads existing ID readback mismatch: {x}')
 if 'paperclip' in m:
  if not a.paperclip_bin:raise ProtocolError('Paperclip executable required')
  for x in [m['paperclip']['issue_id'],*m['paperclip']['existing_ids']]:
   item=parse_item(run([a.paperclip_bin,'show',x,'--json']).stdout,'Paperclip')
   if item.get('id')!=x:raise ProtocolError(f'Paperclip ID readback mismatch: {x}')
 run([a.ringer_bin,'lint',str(rp)]);run([a.ringer_bin,'run',str(rp),'--dry-run'])
 rec={'schema_version':'fleet-wave.v1','event':'prepared','prepared_at':now(),'wave_id':m['wave_id'],'manifest_sha256':digest(p),'ringer_manifest_sha256':digest(rp),'beads_authority':b,'dispatch_authorized':True}
 if 'paperclip' in m:run([a.paperclip_bin,'comment',m['paperclip']['issue_id'],json.dumps(rec,sort_keys=True)])
 write_receipt(a.receipt,rec)
def execute(a):
 p,m,rp=context(a);prep=load(a.prepared_receipt);validate_prepared_receipt(prep,m);binding(p,m,rp,prep,'prepared');claim(a,m)
 runs=resolve(p.parent,m['ringer_state_dir']).resolve()/'runs';before={x.resolve():digest(x) for x in runs.glob('*.json')} if runs.is_dir() else {}
 run([a.ringer_bin,'run',str(rp)])
 after={x.resolve():digest(x) for x in runs.glob('*.json')} if runs.is_dir() else {}
 if any(after.get(k)!=v for k,v in before.items()):raise ProtocolError('Ringer overwrote an existing run-state receipt')
 new=set(after)-set(before)
 if len(new)!=1:raise ProtocolError(f'Ringer must create exactly one new run-state receipt; found {len(new)}')
 state=next(iter(new));rec={'schema_version':'fleet-wave.v1','event':'executed','executed_at':now(),'wave_id':m['wave_id'],'manifest_sha256':digest(p),'ringer_manifest_sha256':digest(rp),'prepared_receipt_sha256':digest(a.prepared_receipt),'run_state_path':str(state),'run_state_sha256':digest(state)};write_receipt(a.receipt,rec)
def validate_state(s,keys):
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
def accept(a):
 p,m,rp=context(a);prep=load(a.prepared_receipt);validate_prepared_receipt(prep,m);binding(p,m,rp,prep,'prepared');ex=load(a.execute_receipt);validate_execute_receipt(ex);binding(p,m,rp,ex,'executed')
 if ex.get('prepared_receipt_sha256')!=digest(a.prepared_receipt):raise ProtocolError('execute/prepared binding mismatch')
 sp=Path(str(ex.get('run_state_path',''))).resolve()
 runs=(resolve(p.parent,m['ringer_state_dir']).resolve()/'runs').resolve()
 if runs not in sp.parents:raise ProtocolError('run-state path is outside bound Ringer runs directory')
 if not sp.is_file() or digest(sp)!=ex.get('run_state_sha256'):raise ProtocolError('run-state hash mismatch')
 keys=[x['key'] for x in m['tasks']];by=validate_state(load(sp),keys);ringer={x['key']:x for x in load(rp)['tasks']};workroot=Path(load(rp).get('workdir',rp.parent)).resolve();replay={}
 for k in keys:
  td=Path(str(by[k].get('taskdir',''))).resolve()
  if not td.is_dir() or td!=workroot and workroot not in td.parents:raise ProtocolError(f'path-unsafe taskdir: {k}')
  for item in ringer[k].get('expect_files',[]):
   if not nonempty(item):raise ProtocolError('invalid expected artifact path')
   q=(td/item).resolve()
   if td not in q.parents or not q.is_file() or not q.stat().st_size:raise ProtocolError(f'missing/path-unsafe expected artifact: {k}/{item}')
  run(['/bin/sh','-c',ringer[k]['check']],cwd=td);replay[k]=True
 judge_hash=None;judgment=[x['key'] for x in m['tasks'] if x['evidence']['kind']=='judgmental']
 if judgment:
  if not a.judge_receipt:raise ProtocolError('fresh judge attestation required')
  j=load(a.judge_receipt);exact(j,{'judge_id','judged_at','criteria','rationale','task_keys','independent','verdict','wave_id','manifest_sha256','execute_receipt_sha256','run_state_sha256'},'judge attestation')
  if not nonempty(j['judge_id']) or not strings(j['criteria'],True) or not nonempty(j['rationale']) or j['task_keys']!=judgment or j['independent'] is not True or j['verdict']!='PASS' or j['wave_id']!=m['wave_id'] or j['manifest_sha256']!=digest(p) or j['execute_receipt_sha256']!=digest(a.execute_receipt) or j['run_state_sha256']!=digest(sp) or dt(j['judged_at'])<=dt(ex['executed_at']):raise ProtocolError('invalid/stale judge attestation')
  judge_hash=digest(a.judge_receipt)
 rings=[]
 if 'ringside' in m:
  if not a.ringside_bin:raise ProtocolError('Ringside executable required')
  base=m['ringside']['base_url'].rstrip('/')
  for endpoint in ('/api/runs','/api/library'):
   raw=run([a.ringside_bin,'get',base+endpoint]).stdout;value=parse_item(raw,'Ringside');rings.append({'endpoint':endpoint,'response':value,'response_sha256':hashlib.sha256(raw.encode()).hexdigest()})
 rec={'schema_version':'fleet-wave.v1','event':'accepted','accepted_at':now(),'wave_id':m['wave_id'],'manifest_sha256':digest(p),'ringer_manifest_sha256':digest(rp),'execute_receipt_sha256':digest(a.execute_receipt),'run_state_sha256':digest(sp),'independent_replay':replay,'judge_receipt_sha256':judge_hash,'bifrost_correlation':None,'ringside_read_only':rings,'accept_mode':a.accept_mode,'beads_close_reason':None}
 close_reason=f"Fleet Wave accepted: wave_id={m['wave_id']}; manifest_sha256={digest(p)}; execute_receipt_sha256={digest(a.execute_receipt)}"
 if a.accept_mode=='close':rec['beads_close_reason']=close_reason
 summary=json.dumps(rec,sort_keys=True);issue=m['beads']['issue_id'];bd(a,'comments','add',issue,summary)
 if a.accept_mode=='close':bd(a,'close',issue,'--reason',close_reason);claim(a,m,'closed')
 if 'paperclip' in m:
  if not a.paperclip_bin:raise ProtocolError('Paperclip executable required')
  run([a.paperclip_bin,'comment',m['paperclip']['issue_id'],summary])
 write_receipt(a.receipt,rec)
def parser():
 c=argparse.ArgumentParser(add_help=False)
 for x in ('manifest',):c.add_argument(x)
 for x in ('--bd-bin','--ringer-bin','--beads-host','--beads-store','--beads-claimant','--receipt'):c.add_argument(x,required=True)
 c.add_argument('--paperclip-bin');c.add_argument('--ringside-bin');root=argparse.ArgumentParser(description=__doc__);subs=root.add_subparsers(dest='command',required=True);subs.add_parser('prepare',parents=[c]);e=subs.add_parser('execute',parents=[c]);e.add_argument('--prepared-receipt',required=True);a=subs.add_parser('accept',parents=[c]);a.add_argument('--prepared-receipt',required=True);a.add_argument('--execute-receipt',required=True);a.add_argument('--judge-receipt');a.add_argument('--accept-mode',choices=['receipt-only','close'],default='receipt-only');return root
def main(argv=None):
 a=parser().parse_args(argv)
 try:{'prepare':prepare,'execute':execute,'accept':accept}[a.command](a)
 except (ProtocolError,OSError,ValueError,KeyError,TypeError) as e:print(f'fleet-wave: {e}',file=sys.stderr);return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
