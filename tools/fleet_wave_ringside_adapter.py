#!/usr/bin/env python3
"""Read-only loopback HTTP adapter for Fleet Wave Ringside observations."""

from __future__ import annotations

import http.client
import json
import sys
from urllib.parse import urlsplit


class AdapterError(RuntimeError):
    pass


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 2 or argv[0] != "get":
            raise AdapterError("usage: get URL")
        parsed = urlsplit(argv[1])
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AdapterError("Ringside adapter permits loopback HTTP only")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise AdapterError("Ringside URL must not contain credentials, query, or fragment")
        if parsed.path not in {"/api/runs", "/api/library"}:
            raise AdapterError("unsupported Ringside endpoint")
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
        try:
            conn.request("GET", parsed.path)
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
        finally:
            conn.close()
        if response.status != 200:
            raise AdapterError(f"GET {parsed.path} returned HTTP {response.status}")
        value = json.loads(raw)
        if not isinstance(value, (dict, list)):
            raise AdapterError("Ringside response must be a JSON object or list")
        print(json.dumps(value, sort_keys=True))
        return 0
    except (AdapterError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"fleet-wave-ringside-adapter: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
