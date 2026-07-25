from __future__ import annotations
import json
import os
import subprocess
import sys
import urllib.request

env = os.environ.copy()
env["BEADS_DIR"] = "/Users/hermes/.beads"
errors = []
def run_json(args):
    proc = subprocess.run(args, text=True, capture_output=True, env=env, timeout=20)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)
try:
    stats = run_json(["bd", "stats", "--json"])
    bead = run_json(["bd", "show", "hermes-ujgu", "--json"])
    bead_obj = bead[0] if isinstance(bead, list) else bead
    if bead_obj.get("status") not in {"in_progress", "closed"}:
        errors.append(f"Bead hermes-ujgu unexpected status {bead_obj.get('status')}")
except Exception as exc:
    stats = {}
    bead_obj = {}
    errors.append(f"Beads read failed: {exc}")
try:
    url = "http://127.0.0.1:3100/api/issues/12876576-f5d1-4dff-99e8-a71a7a2c0f8e"
    with urllib.request.urlopen(url, timeout=6) as response:
        issue = json.load(response)
    if issue.get("identifier") != "JAC-3415":
        errors.append(f"Paperclip identifier mismatch: {issue.get('identifier')}")
    if issue.get("status") not in {"in_progress", "in_review", "done"}:
        errors.append(f"Paperclip JAC-3415 unexpected status {issue.get('status')}")
except Exception as exc:
    issue = {}
    errors.append(f"Paperclip read failed: {exc}")
print(json.dumps({"beads_summary": stats.get("summary", {}), "bead_status": bead_obj.get("status"), "paperclip_status": issue.get("status"), "errors": errors}, sort_keys=True))
if errors:
    print("FAIL: " + "; ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("PASS: canonical Beads and Paperclip work-state records are readable and active")
