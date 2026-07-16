#!/usr/bin/env python3
"""Minimal fail-closed Paperclip adapter for tools/fleet_wave.py.

Commands:
  show ISSUE --json
  comment ISSUE PAYLOAD [--idempotency-key KEY] [--json]

The comment path encodes receipt bytes in a versioned base64 envelope, de-duplicates
by a stable marker, and re-reads both the exact envelope and decoded payload from
Paperclip before reporting success. No credentials are read or emitted.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import sys
from urllib.parse import urlsplit


class AdapterError(RuntimeError):
    pass


def base_parts() -> tuple[str, int, str]:
    raw = os.environ.get("PAPERCLIP_BASE_URL", "http://127.0.0.1:3100")
    parsed = urlsplit(raw)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise AdapterError("Paperclip adapter permits loopback HTTP only")
    return parsed.hostname, parsed.port or 80, parsed.path.rstrip("/")


def request(method: str, path: str, body: object | None = None) -> object:
    host, port, prefix = base_parts()
    conn = http.client.HTTPConnection(host, port, timeout=30)
    payload = None if body is None else json.dumps(body, separators=(",", ":"))
    try:
        conn.request(
            method,
            prefix + path,
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
    finally:
        conn.close()
    if response.status >= 300:
        raise AdapterError(f"{method} {path} returned HTTP {response.status}: {raw[:500]}")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise AdapterError(f"{method} {path} returned invalid JSON") from exc


def issue(issue_ref: str) -> dict[str, object]:
    value = request("GET", f"/api/issues/{issue_ref}")
    if not isinstance(value, dict):
        raise AdapterError("Paperclip issue readback was not an object")
    if issue_ref not in {value.get("id"), value.get("identifier")}:
        raise AdapterError("Paperclip issue identity readback mismatch")
    return value


def comments(canonical_id: str) -> list[dict[str, object]]:
    value = request("GET", f"/api/issues/{canonical_id}/comments")
    if isinstance(value, dict):
        value = value.get("comments", value.get("items", []))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AdapterError("Paperclip comments readback was not a list")
    return value


def comment_transport(payload: str, key: str | None) -> tuple[str, str, str, str]:
    """Encode payload bytes in a transport Paperclip will not rewrite."""
    payload_bytes = payload.encode("utf-8")
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    stable_key = key or f"terminal-{payload_sha}"
    marker = f"[fleet-wave-v2:{stable_key}]"
    envelope = {
        "encoding": "base64",
        "payload_base64": base64.b64encode(payload_bytes).decode("ascii"),
        "payload_sha256": payload_sha,
        "schema_version": "fleet-wave-comment.v2",
    }
    body = marker + "\n" + json.dumps(envelope, separators=(",", ":"), sort_keys=True)
    return marker, body, payload_sha, stable_key


def decode_comment_body(body: str, marker: str) -> str:
    prefix = marker + "\n"
    if not body.startswith(prefix):
        raise AdapterError("Paperclip comment marker readback mismatch")
    try:
        envelope = json.loads(body[len(prefix) :])
    except json.JSONDecodeError as exc:
        raise AdapterError("Paperclip comment envelope was not valid JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "encoding",
        "payload_base64",
        "payload_sha256",
        "schema_version",
    }:
        raise AdapterError("Paperclip comment envelope shape mismatch")
    if envelope["schema_version"] != "fleet-wave-comment.v2" or envelope["encoding"] != "base64":
        raise AdapterError("Paperclip comment envelope version/encoding mismatch")
    try:
        payload_bytes = base64.b64decode(str(envelope["payload_base64"]), validate=True)
        payload = payload_bytes.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise AdapterError("Paperclip comment payload was not canonical base64 UTF-8") from exc
    if hashlib.sha256(payload_bytes).hexdigest() != envelope["payload_sha256"]:
        raise AdapterError("Paperclip comment payload hash mismatch")
    return payload


def command_show(argv: list[str]) -> dict[str, object]:
    if len(argv) not in {1, 2} or (len(argv) == 2 and argv[1] != "--json"):
        raise AdapterError("usage: show ISSUE [--json]")
    return issue(argv[0])


def command_comment(argv: list[str]) -> dict[str, object]:
    if len(argv) < 2:
        raise AdapterError("usage: comment ISSUE PAYLOAD [--idempotency-key KEY] [--json]")
    issue_ref, payload = argv[0], argv[1]
    key = None
    index = 2
    while index < len(argv):
        if argv[index] == "--json":
            index += 1
            continue
        if argv[index] == "--idempotency-key" and index + 1 < len(argv):
            key = argv[index + 1]
            index += 2
            continue
        raise AdapterError(f"unknown comment argument: {argv[index]}")
    marker, exact_body, payload_sha, stable_key = comment_transport(payload, key)
    record = issue(issue_ref)
    canonical_id = str(record["id"])
    identifier = str(record.get("identifier") or canonical_id)
    before = comments(canonical_id)
    same_marker = [item for item in before if str(item.get("body", "")).startswith(marker + "\n")]
    if same_marker and not any(item.get("body") == exact_body for item in same_marker):
        raise AdapterError("Paperclip idempotency marker already exists with different payload")
    if not any(item.get("body") == exact_body for item in same_marker):
        request("POST", f"/api/issues/{canonical_id}/comments", {"body": exact_body})
    after = comments(canonical_id)
    matches = [item for item in after if item.get("body") == exact_body]
    if not matches:
        raise AdapterError("Paperclip exact comment body was not present after write")
    latest = matches[-1]
    if decode_comment_body(str(latest["body"]), marker) != payload:
        raise AdapterError("Paperclip decoded payload readback mismatch")
    return {
        "issue_id": identifier,
        "canonical_id": canonical_id,
        "comment_id": latest.get("id"),
        "idempotency_key": stable_key,
        "payload_sha256": payload_sha,
        "readback_body_sha256": hashlib.sha256(exact_body.encode("utf-8")).hexdigest(),
        "exact_readback": True,
        "transport_version": "fleet-wave-comment.v2",
    }


def main(argv: list[str]) -> int:
    try:
        if not argv:
            raise AdapterError("expected show or comment command")
        command, rest = argv[0], argv[1:]
        if command == "show":
            result = command_show(rest)
        elif command == "comment":
            result = command_comment(rest)
        else:
            raise AdapterError(f"unsupported command: {command}")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AdapterError, OSError, ValueError, KeyError) as exc:
        print(f"fleet-wave-paperclip-adapter: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
