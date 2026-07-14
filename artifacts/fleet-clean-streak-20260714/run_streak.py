#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RINGER = Path("/Users/hermes/.local/bin/ringer")
CONFIG = ROOT / "ringer-stability.toml"
STATE_RUNS = Path.home() / ".ringer" / "runs"
TARGET_STREAK = 10

LOCAL_PROBE = r'''from __future__ import annotations
import json
import sys
import urllib.request

endpoints = {
    "paperclip": "http://127.0.0.1:3100/api/health",
    "ringside": "http://127.0.0.1:8700/api/runs",
    "openbrain": "http://127.0.0.1:8787/health",
    "bifrost": "http://127.0.0.1:8078/health",
    "hindsight": "http://127.0.0.1:8888/health",
}
results = {}
errors = []
for name, url in endpoints.items():
    try:
        with urllib.request.urlopen(url, timeout=6) as response:
            payload = json.load(response)
            results[name] = {"status": response.status, "json_type": type(payload).__name__}
            if response.status != 200:
                errors.append(f"{name}: expected HTTP 200, got {response.status}")
    except Exception as exc:
        results[name] = {"error": str(exc)}
        errors.append(f"{name}: {exc}")
print(json.dumps({"results": results, "errors": errors}, sort_keys=True))
if errors:
    print("FAIL: " + "; ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("PASS: all five Aegis control-plane endpoints returned HTTP 200 with JSON")
'''

TALARIS_PROBE = r'''from __future__ import annotations
import json
import subprocess
import sys

urls = [
    "http://127.0.0.1:8082/api/health",
    "http://127.0.0.1:3110/api/health",
    "http://127.0.0.1:8700/api/runs",
    "http://127.0.0.1:8078/health",
]
remote = "set -eu; hostname -s; " + " ".join(
    f"code=$(/usr/bin/curl -sS -o /dev/null -w '%{{http_code}}' --max-time 6 {url}); printf '%s %s\\n' \"$code\" {url};"
    for url in urls
)
proc = subprocess.run(
    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "jack.reis@100.97.178.76", remote],
    text=True,
    capture_output=True,
    timeout=45,
)
lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
errors = []
if proc.returncode != 0:
    errors.append(f"ssh exited {proc.returncode}: {proc.stderr.strip()}")
if not lines or not lines[0].lower().startswith("talaris"):
    errors.append(f"unexpected remote hostname output: {lines[:1]}")
observed = {}
for line in lines[1:]:
    parts = line.split(maxsplit=1)
    if len(parts) == 2:
        observed[parts[1]] = parts[0]
for url in urls:
    if observed.get(url) != "200":
        errors.append(f"{url}: expected 200, got {observed.get(url, 'missing')}")
print(json.dumps({"returncode": proc.returncode, "observed": observed, "stderr": proc.stderr.strip(), "errors": errors}, sort_keys=True))
if errors:
    print("FAIL: " + "; ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("PASS: Talaris and all four cross-host/tunnel surfaces are healthy")
'''

WORK_STATE_PROBE = r'''from __future__ import annotations
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
'''

FORK_PROBE = r'''from __future__ import annotations
import json
import subprocess
import sys

errors = []
def run(args, timeout=20):
    proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        errors.append(f"{' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout.strip()
url = run(["git", "-C", "/Users/hermes/ringer", "remote", "get-url", "fleet"])
heads = run(["git", "-C", "/Users/hermes/ringer", "ls-remote", "--heads", "fleet", "fleet-sync/paperclip-to-ringer-20260709"], timeout=40)
help_line = run(["/Users/hermes/.local/bin/ringer", "--help"]).splitlines()
if url != "https://github.com/JackReis/ringer-fleet.git":
    errors.append(f"fleet fork URL mismatch: {url}")
if not heads.startswith("47ccc11"):
    errors.append(f"owned fork branch head mismatch/unreachable: {heads[:80]}")
if not help_line or not help_line[0].startswith("usage: ringer.py"):
    errors.append("pinned Ringer launcher did not execute supported Python entrypoint")
print(json.dumps({"fleet_remote": url, "head": heads.split()[0] if heads else None, "launcher": help_line[0] if help_line else None, "errors": errors}, sort_keys=True))
if errors:
    print("FAIL: " + "; ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("PASS: fleet-owned Ringer fork and pinned Python 3.12 launcher are operational")
'''


def mock_spec(script: str, purpose: str) -> str:
    return f"{purpose}\nMOCK_FILE: probe.py\n{script}MOCK_END\n"


def task(key: str, purpose: str, script: str, verified: str, project: bool = False) -> dict:
    item = {
        "key": key,
        "spec": mock_spec(script, purpose),
        "check": "python3.12 probe.py || { rc=$?; echo \"FAIL: probe.py exited $rc; see output above\"; exit $rc; }",
        "expect_files": ["probe.py"],
        "engine": "mock",
        "timeout_s": 120,
        "task_type": "probe",
        "verified": verified,
    }
    if project:
        item["paperclip_issue"] = "JAC-3415"
        item["bead_id"] = "hermes-ujgu"
    return item


def write_manifest(cycle: int) -> Path:
    cycle_root = ROOT / f"cycle-{cycle:02d}"
    cycle_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_name": f"fleet-clean-streak-{cycle:02d}",
        "workdir": str(cycle_root / "work"),
        "max_parallel": 4,
        "tasks": [
            task("aegis-control-plane", "Install and execute a deterministic probe of Aegis fleet control-plane endpoints.", LOCAL_PROBE, "All five Aegis control-plane endpoints returned HTTP 200 and valid JSON."),
            task("talaris-cross-host", "Install and execute a deterministic SSH-before-verification probe of Talaris and fleet tunnels.", TALARIS_PROBE, "Talaris was reachable non-interactively and its Command Centre plus three Aegis tunnels returned HTTP 200."),
            task("canonical-work-state", "Install and execute a deterministic read-only probe of canonical Beads and Paperclip work state.", WORK_STATE_PROBE, "Beads hermes-ujgu and Paperclip JAC-3415 were readable and in an allowed active/completed state.", project=True),
            task("owned-ringer-fork", "Install and execute a deterministic probe of the fleet-owned Ringer fork and launcher.", FORK_PROBE, "The JackReis/ringer-fleet branch was reachable at the expected integration commit and the Python 3.12 launcher worked."),
        ],
    }
    path = cycle_root / "swarm.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def newest_run_for(run_name: str, not_before: float) -> tuple[Path, dict]:
    candidates = []
    for path in STATE_RUNS.glob(f"{run_name}-*.json"):
        if path.stat().st_mtime >= not_before - 2:
            candidates.append(path)
    if not candidates:
        raise RuntimeError(f"no state JSON found for {run_name}")
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    return path, json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    env = os.environ.copy()
    env["BEADS_DIR"] = "/Users/hermes/.beads"
    env["RINGER_NO_CATALOG_REFRESH"] = "1"
    evidence = {
        "schema_version": 1,
        "target_streak": TARGET_STREAK,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "runs": [],
    }
    evidence_path = ROOT / "streak-evidence.json"
    for cycle in range(1, TARGET_STREAK + 1):
        manifest = write_manifest(cycle)
        lint = subprocess.run([str(RINGER), "--config", str(CONFIG), "lint", str(manifest)], text=True, capture_output=True, env=env)
        print(f"cycle {cycle:02d} lint rc={lint.returncode}: {lint.stdout.strip()} {lint.stderr.strip()}", flush=True)
        if lint.returncode != 0 or "lint: clean" not in lint.stdout:
            raise RuntimeError(f"cycle {cycle:02d} lint failed: {lint.stdout}\n{lint.stderr}")
        started = time.time()
        run = subprocess.run([str(RINGER), "--config", str(CONFIG), "run", str(manifest), "--no-dashboard", "--identity", "aegis"], text=True, capture_output=True, env=env)
        print(run.stdout, end="", flush=True)
        if run.stderr:
            print(run.stderr, end="", file=sys.stderr, flush=True)
        state_path, state = newest_run_for(f"fleet-clean-streak-{cycle:02d}", started)
        summary = state.get("summary") or {}
        task_receipts = [
            {
                "key": item.get("key"),
                "status": item.get("status"),
                "verdict": item.get("verdict"),
                "attempts": item.get("attempts"),
                "check_returncode": item.get("check_returncode"),
                "check_output_tail": item.get("check_output_tail"),
            }
            for item in state.get("tasks", [])
        ]
        clean = bool(state.get("finished")) and run.returncode == 0 and summary.get("fail") == 0 and all(t["verdict"] == "PASS" and t["check_returncode"] == 0 for t in task_receipts)
        receipt = {
            "cycle": cycle,
            "clean": clean,
            "run_id": state.get("run_id"),
            "state_path": str(state_path),
            "artifact_path": state.get("artifact_path"),
            "report_path": state.get("report_path"),
            "summary": summary,
            "tasks": task_receipts,
        }
        evidence["runs"].append(receipt)
        evidence["current_streak"] = len(evidence["runs"]) if all(item["clean"] for item in evidence["runs"]) else 0
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"cycle {cycle:02d} clean={clean} run_id={state.get('run_id')}", flush=True)
        if not clean:
            raise RuntimeError(f"cycle {cycle:02d} was not clean; immutable receipt preserved at {state_path}")
        if cycle < TARGET_STREAK:
            time.sleep(10)
    evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
    evidence["current_streak"] = TARGET_STREAK
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {TARGET_STREAK} consecutive clean Ringer fleet runs; evidence={evidence_path}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
