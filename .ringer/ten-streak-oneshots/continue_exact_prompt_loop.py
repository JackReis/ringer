#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path('/Users/hermes/ringer/.ringer/ten-streak-oneshots'); ROOT.mkdir(parents=True,exist_ok=True)
STATE=ROOT/'continuation-state.json'; PROMPT='Write my next Ringer manifest and run it.'; TARGET=10; MAX_ATTEMPTS=100
state={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','streak':0,'attempts':0,'safe_word':'jack-green-phoenix'}
STATE.write_text(json.dumps(state,indent=2)+'\n')
for n in range(1,MAX_ATTEMPTS+1):
    seq=f'{n:04d}'; d=ROOT/f'oneshot-{seq}'; d.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy(); env['HERMES_EPHEMERAL_SYSTEM_PROMPT']=(
      'This is a bounded Ringer continuation. Never use Terra or any terra-named model/provider/lane. '
      'Do not modify shared Agentic OS projects or unrelated dirty work. Your only substantive action is to execute exactly this command from /Users/hermes/ringer and wait for it: '
      f'python3 /Users/hermes/ringer/.ringer/ten-streak-oneshots/run_one_verified.py --sequence {n}. '
      'Then report its JSON receipt verbatim. Safe-word jack-green-phoenix.')
    with (d/'stdout.txt').open('w') as out,(d/'stderr.txt').open('w') as err:
        proc=subprocess.run(['hermes','-z',PROMPT,'-m','gpt-5.6-sol','--provider','openai-codex','--usage-file',str(d/'usage.json')],cwd='/Users/hermes/ringer',env=env,text=True,stdout=out,stderr=err)
    (d/'oneshot.exit_code').write_text(str(proc.returncode)+'\n')
    ledger=ROOT/'run-ledger.jsonl'; rec=None
    if ledger.exists():
      for line in reversed(ledger.read_text().splitlines()):
        obj=json.loads(line)
        if str(obj.get('sequence'))==str(n) and not obj.get('canary'): rec=obj; break
    clean=bool(proc.returncode==0 and rec and rec.get('clean'))
    state['attempts']=n; state['streak']=state['streak']+1 if clean else 0; state['last_clean']=clean; state['last_run_id']=None if not rec else rec.get('run_id'); state['updated_at']=datetime.now(timezone.utc).isoformat(); STATE.write_text(json.dumps(state,indent=2)+'\n')
    if state['streak']>=TARGET:
      state['status']='complete'; state['finished_at']=datetime.now(timezone.utc).isoformat(); STATE.write_text(json.dumps(state,indent=2)+'\n'); raise SystemExit(0)
    time.sleep(5)
state['status']='blocked-max-attempts'; state['finished_at']=datetime.now(timezone.utc).isoformat(); STATE.write_text(json.dumps(state,indent=2)+'\n'); raise SystemExit(2)
