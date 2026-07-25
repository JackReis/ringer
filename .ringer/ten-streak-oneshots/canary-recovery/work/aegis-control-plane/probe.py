from __future__ import annotations
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
