from __future__ import annotations
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
