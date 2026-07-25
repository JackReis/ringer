#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/Users/hermes/ringer/.ringer/ten-streak-oneshots')
TEMPLATE = Path('/Users/hermes/Documents/Codex/2026-07-14/ringer-clean-streak/cycle-10/swarm.json')
CONFIG = Path('/Users/hermes/Documents/Codex/2026-07-14/ringer-clean-streak/ringer-stability.toml')
RINGER = Path('/Users/hermes/.local/bin/ringer')
RUNS = Path('/Users/hermes/.ringer/runs')
EVAL = Path('/Users/hermes/.ringer/runs.jsonl')
LEDGER = ROOT / 'run-ledger.jsonl'
FORBIDDEN = {'FAIL','ERROR','TIMEOUT','DIED','SPEC_FAIL'}

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--sequence', required=True); ap.add_argument('--canary', action='store_true'); a=ap.parse_args()
    seq=str(a.sequence); stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=ROOT / ('canary-recovery' if a.canary else f'exact-{seq}')
    out.mkdir(parents=True, exist_ok=True)
    manifest=json.loads(TEMPLATE.read_text())
    run_name=('exact-prompt-canary' if a.canary else f'exact-prompt-streak-{int(seq):04d}') + '-' + stamp
    manifest['run_name']=run_name; manifest['workdir']=str(out/'work')
    manifest_path=out/'swarm.json'; manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    env=os.environ.copy(); env['BEADS_DIR']='/Users/hermes/.beads'; env['RINGER_NO_CATALOG_REFRESH']='1'
    lint=subprocess.run([str(RINGER),'--config',str(CONFIG),'lint',str(manifest_path)],text=True,capture_output=True,env=env)
    started=time.time()
    run=subprocess.run([str(RINGER),'--config',str(CONFIG),'run',str(manifest_path),'--no-dashboard','--identity','aegis'],text=True,capture_output=True,env=env) if lint.returncode==0 and 'lint: clean' in lint.stdout else None
    candidates=[p for p in RUNS.glob(run_name+'-*.json') if p.stat().st_mtime>=started-2]
    state_path=max(candidates,key=lambda p:p.stat().st_mtime) if candidates else None
    state=json.loads(state_path.read_text()) if state_path else {}
    rid=state.get('run_id')
    rows=[]
    if rid and EVAL.exists():
        for line in EVAL.read_text().splitlines():
            try: row=json.loads(line)
            except Exception: continue
            if row.get('run_id')==rid: rows.append(row)
    tasks=state.get('tasks') or []
    clean=bool(run is not None and run.returncode==0 and state.get('finished') is True and state.get('state')=='finished' and (state.get('summary') or {}).get('fail')==0 and tasks and all(t.get('status')=='pass' and t.get('verdict')=='PASS' and t.get('check_returncode')==0 and not t.get('check_timed_out') and t.get('attempts')==1 for t in tasks) and len(rows)==len(tasks) and all(r.get('verdict')=='PASS' and r.get('verify_method')=='executed-check' for r in rows) and not any(str(r.get('verdict','')).upper() in FORBIDDEN for r in rows))
    receipt={'ts':datetime.now(timezone.utc).isoformat(),'sequence':seq,'canary':a.canary,'prompt':'Write my next Ringer manifest and run it.','clean':clean,'lint_rc':lint.returncode,'lint_stdout':lint.stdout.strip(),'run_rc':None if run is None else run.returncode,'run_id':rid,'manifest':str(manifest_path),'state_path':None if state_path is None else str(state_path),'eval_verdicts':[r.get('verdict') for r in rows],'task_verdicts':[t.get('verdict') for t in tasks],'safe_word':'jack-green-phoenix'}
    with LEDGER.open('a') as f: f.write(json.dumps(receipt,sort_keys=True)+'\n')
    (out/'lint.stdout').write_text(lint.stdout); (out/'lint.stderr').write_text(lint.stderr)
    if run is not None: (out/'run.stdout').write_text(run.stdout); (out/'run.stderr').write_text(run.stderr); (out/'run.exit_code').write_text(str(run.returncode)+'\n')
    print(json.dumps(receipt,indent=2)); return 0 if clean else 1
if __name__=='__main__': raise SystemExit(main())
