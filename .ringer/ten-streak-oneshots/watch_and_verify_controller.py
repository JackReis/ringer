#!/usr/bin/env python3
from __future__ import annotations
import json, os, signal, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path('/Users/hermes/ringer/.ringer/ten-streak-oneshots'); RUNS=Path('/Users/hermes/.ringer/runs'); EVAL=Path('/Users/hermes/.ringer/runs.jsonl')
STATE=ROOT/'verified-continuation-state.json'; LEDGER=ROOT/'verified-run-ledger.jsonl'; REG=ROOT/'controller-run-registry.json'
CONTROLLER=49609; START='2026-07-14T19:45:20'; BAD={'FAIL','ERROR','TIMEOUT','DIED','SPEC_FAIL'}
registry=set(json.loads(REG.read_text())) if REG.exists() else set(); processed=set(); streak=0
if STATE.exists():
 d=json.loads(STATE.read_text()); processed=set(d.get('processed_run_ids',[])); streak=int(d.get('streak',0))
def ppid_map():
 out=subprocess.run(['ps','-ax','-o','pid=,ppid='],capture_output=True,text=True).stdout; return {int(a):int(b) for a,b in (ln.split() for ln in out.splitlines())}
def descendant(pid,parents):
 seen=set()
 while pid>1 and pid not in seen:
  if pid==CONTROLLER:return True
  seen.add(pid); pid=parents.get(pid,0)
 return False
def save(status='running'):
 STATE.write_text(json.dumps({'status':status,'streak':streak,'target':10,'controller_pid':CONTROLLER,'registered_run_ids':sorted(registry),'processed_run_ids':sorted(processed),'updated_at':datetime.now(timezone.utc).isoformat(),'safe_word':'jack-green-phoenix'},indent=2)+'\n')
save()
while True:
 parents=ppid_map()
 for p in RUNS.glob('*.json'):
  try:d=json.loads(p.read_text())
  except Exception:continue
  if str(d.get('started_at',''))<START:continue
  rid=d.get('run_id'); pid=int(d.get('pid') or 0)
  if rid and (rid in registry or descendant(pid,parents)): registry.add(rid)
 REG.write_text(json.dumps(sorted(registry),indent=2)+'\n')
 states=[]
 for rid in registry:
  p=RUNS/(rid+'.json')
  if p.exists():
   try: states.append((json.loads(p.read_text()).get('started_at',''),p,json.loads(p.read_text())))
   except Exception: pass
 for _,p,d in sorted(states):
  rid=d.get('run_id')
  if rid in processed or not d.get('finished'):continue
  rows=[]
  for line in EVAL.read_text().splitlines():
   try:r=json.loads(line)
   except Exception:continue
   if r.get('run_id')==rid:rows.append(r)
  tasks=d.get('tasks') or []
  workdir=Path(tasks[0].get('taskdir','')).parent if tasks else Path()
  manifest=workdir.parent/'swarm.json'
  lint=subprocess.run(['/Users/hermes/.local/bin/ringer','lint',str(manifest)],capture_output=True,text=True) if manifest.exists() else None
  clean=bool(lint and lint.returncode==0 and 'lint: clean' in lint.stdout and d.get('state')=='finished' and (d.get('summary') or {}).get('fail')==0 and tasks and all(t.get('status')=='pass' and t.get('verdict')=='PASS' and t.get('check_returncode')==0 and not t.get('check_timed_out') and t.get('attempts')==1 for t in tasks) and len(rows)==len(tasks) and all(r.get('verdict')=='PASS' and r.get('verify_method')=='executed-check' for r in rows) and not any(str(r.get('verdict','')).upper() in BAD for r in rows))
  streak=streak+1 if clean else 0; processed.add(rid)
  rec={'ts':datetime.now(timezone.utc).isoformat(),'run_id':rid,'clean':clean,'streak':streak,'manifest':str(manifest),'lint_rc':None if lint is None else lint.returncode,'run_state':str(p),'run_exit_success':d.get('finished') and d.get('state')=='finished' and (d.get('summary') or {}).get('fail')==0,'task_verdicts':[t.get('verdict') for t in tasks],'attempts':[t.get('attempts') for t in tasks],'eval_verdicts':[r.get('verdict') for r in rows],'safe_word':'jack-green-phoenix'}
  with LEDGER.open('a') as f:f.write(json.dumps(rec,sort_keys=True)+'\n')
  save()
  if streak>=10:
   try: os.kill(CONTROLLER,signal.SIGTERM)
   except ProcessLookupError: pass
   save('complete'); raise SystemExit(0)
 if CONTROLLER not in parents:
  save('controller-exited-before-target'); raise SystemExit(2)
 time.sleep(2)
