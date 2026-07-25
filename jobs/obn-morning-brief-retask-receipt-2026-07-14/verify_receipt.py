#!/usr/bin/env python3
"""Ringer executed-check for the OBn morning brief observability receipt."""
from __future__ import annotations

import json
import select
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BEAD_ID = "notes-sbry1"
PAPERCLIP_ID = "01747674-479d-4c3b-ace4-5382b50ec8e6"
PAPERCLIP_IDENTIFIER = "JAC-3414"
BIFROST_ROW = "9fa201ba-ad61-4db4-847a-cfc9dcbbc7e0"
CONTEXTFORGE_ITEM = "dec71bf8-9b04-425c-abb7-3b21758f062b"
CORRELATION = "obn-morning-brief-retask-20260714"
CRON_ID = "da8ad7b5c684"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def remote_talaris_json(code: str, timeout: int = 30):
    # Feed the probe over stdin instead of embedding Python in a remote shell
    # argument. This avoids zsh parsing parentheses and quote-heavy literals.
    p = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "talaris", "python3", "-"],
        input=code,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    require(p.returncode == 0, f"Talaris probe exited 0 (stderr={p.stderr.strip()[:160]!r})")
    return json.loads(p.stdout)


def contextforge_query_via_talaris(query: str) -> str:
    # Query ContextForge directly from Aegis. The API key is decrypted into the
    # child environment only and is never printed or written to disk.
    key_result = subprocess.run(
        ["/Users/hermes/.local/bin/age", "--decrypt", "-i", "/Users/hermes/.config/contextforge/contextforge-token-agekey.txt", "/Users/hermes/.config/contextforge/contextforge-token.age"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    require(key_result.returncode == 0 and bool(key_result.stdout.strip()), "Aegis decrypted the ContextForge runtime key")
    import os
    env = os.environ.copy()
    env["CONTEXTFORGE_API_KEY"] = key_result.stdout.strip()
    proc = subprocess.Popen(
        ["/Users/hermes/.hermes/node/bin/contextforge-mcp", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd="/Users/hermes",
        env=env,
    )

    def send(obj):
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def recv(req_id: int, timeout: int = 90):
        assert proc.stdout is not None and proc.stderr is not None
        end = time.time() + timeout
        while time.time() < end:
            ready, _, _ = select.select([proc.stdout, proc.stderr], [], [], 1)
            for stream in ready:
                line = stream.readline()
                if not line or stream is proc.stderr:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == req_id:
                    return msg
        raise TimeoutError(f"ContextForge request {req_id} timed out")

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "ringer-verifier", "version": "1.0"}}})
    init = recv(1)
    require("result" in init, "ContextForge MCP initialized on Aegis")
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_query", "arguments": {"query": query, "project_id": "103a4d02-c875-494e-a0b7-68484013981b", "limit": 5, "min_score": 0.1}}})
    result = recv(2)
    proc.terminate()
    require("result" in result, "ContextForge query returned an MCP result")
    return "\n".join(x.get("text", "") for x in result["result"].get("content", []) if x.get("type") == "text")


def main() -> int:
    receipt_path = Path(sys.argv[1] if len(sys.argv) > 1 else "receipt.md")
    text = receipt_path.read_text()
    for needle in [BEAD_ID, PAPERCLIP_IDENTIFIER, PAPERCLIP_ID, BIFROST_ROW, CONTEXTFORGE_ITEM, CORRELATION, CRON_ID]:
        require(needle in text, f"receipt contains {needle}")

    cron_probe = remote_talaris_json(
        "import json,pathlib; d=json.loads((pathlib.Path.home()/'.hermes/cron/jobs.json').read_text()); j=next(x for x in d['jobs'] if x['id']=='da8ad7b5c684'); s=(pathlib.Path.home()/'.hermes/scripts/obn-morning-brief.sh').read_text(); p=pathlib.Path('/Users/jack.reis/Documents/=notes/claude/scheduled-tasks/vault-ingest/obn_telegram_brief.py').read_text(); print(json.dumps({'id':j['id'],'name':j['name'],'script':j.get('script'),'no_agent':j.get('no_agent'),'deliver':j.get('deliver'),'enabled':j.get('enabled'),'last_status':j.get('last_status'),'shell_has_kimi':('kimi' in s.lower()),'python_invokes_kimi':('[\\\"kimi\\\"' in p or 'kimi mcp telegram-bridge' in p)}))"
    )
    require(cron_probe["id"] == CRON_ID, "live cron ID matches")
    require(cron_probe["script"] == "obn-morning-brief.sh", "live cron uses obn-morning-brief.sh")
    require(cron_probe["no_agent"] is True, "live cron is no_agent=true")
    require(cron_probe["deliver"] == "telegram:7618822262", "live cron uses native Telegram delivery")
    require(cron_probe["enabled"] is True and cron_probe["last_status"] == "ok", "live cron is enabled and last_status=ok")
    require(cron_probe["shell_has_kimi"] is False, "cron shell script contains no Kimi dependency")
    require(cron_probe["python_invokes_kimi"] is False, "manual Python fallback no longer invokes Kimi")

    bead = remote_talaris_json(
        "import json,subprocess; p=subprocess.run(['bd','--db','/Users/jack.reis/Documents/=notes/.beads','show','notes-sbry1','--json'],capture_output=True,text=True); assert p.returncode==0,p.stderr; print(json.dumps(json.loads(p.stdout)[0]))"
    )
    require(bead["id"] == BEAD_ID and bead["status"] in {"in_progress", "closed"}, "Beads SSOT record is active or closed")
    require(f"paperclip:{PAPERCLIP_IDENTIFIER}" in bead.get("labels", []), "Beads record cross-links Paperclip")

    with urllib.request.urlopen(f"http://127.0.0.1:3100/api/issues/{PAPERCLIP_ID}", timeout=15) as response:
        issue = json.load(response)
    require(issue.get("identifier") == PAPERCLIP_IDENTIFIER, "Paperclip mirror identifier matches")
    require(issue.get("title") == "Record OBn morning brief retask across fleet observability surfaces", "Paperclip mirror title matches Beads")

    con = sqlite3.connect(Path.home() / ".bifrost/logs.db")
    con.row_factory = sqlite3.Row
    row = con.execute("select id,provider,model,status,total_tokens from logs where id=?", (BIFROST_ROW,)).fetchone()
    require(row is not None, "Bifrost telemetry row exists")
    require(row["status"] == "success" and row["provider"] == "mistral", "Bifrost row is a successful routed request")
    require((row["total_tokens"] or 0) > 0, "Bifrost row includes token telemetry")

    cf = contextforge_query_via_talaris("OBn morning brief retask observability receipt 2026-07-14")
    require(CONTEXTFORGE_ITEM in cf, "ContextForge pointer is live and queryable")
    require(BEAD_ID in cf and PAPERCLIP_IDENTIFIER in cf, "ContextForge pointer cross-links Beads and Paperclip")

    print("VERIFIED: live downstream checks prove the Kimi-free cron and all fleet observability cross-links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
