from __future__ import annotations
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
