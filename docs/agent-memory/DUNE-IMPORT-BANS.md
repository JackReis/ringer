# Dune import bans

FAIL-closed import graph for Ringer. The doctrine is Dune di Jaggo §3, vault file `Architecture/fleet/DUNE-ELECTRON-VAULT-DOCTRINE-20260927.md`. This note is the Ringer adaptation: Python orchestrator and Ringside host versus the HUD and any other UI.

Multica card AEGI-178 `01a0e545-edc9-793d-be5f-2b1258ad9449`. Baton `01a0e5b2-e7d3-7dda-9c88-0c348a62797a`.

Soft-spare. Do not merge until Multica stamps this change's tip SHA.

## Planes

| Plane | Paths | What it may do |
|---|---|---|
| Privileged host | `ringer.py`, `hud/src`, `scripts/`, `checks/engine-bin-probe.py` | Read config and secret env files. Own the one Ringside board (`PersistentHudServer`). |
| Unprivileged UI | `dashboard/`, `hud/frontend/` | Render. Same-origin board GETs. `tauriInvoke` of commands listed in `generate_handler!`. |
| Unprivileged Python | `templates/**/*.py`, `engines/`, `hooks/` | Run outside the orchestrator. No import of `ringer`. |
| Native shell | `hud/frontend/` | One host event (`ringer-runs`). Not a second board client. |
| Verification | `tests/` | Import `ringer` so a check can execute. |

The per-run server on port 8787 is the internal feed for the page it serves. It is not a second watch board. A UI URL may name that port only as `${port}` on the page's own origin.

## Edges

The policy in `checks/dune_import_policy.toml` declares all four. Dropping an edge fails the gate.

1. **Unprivileged → privileged.** UI and worker Python must not import `ringer`, and UI must not import `fs`, `child_process`, or the Tauri fs/shell plugins.
2. **Shortcut IPC skip.** A command string must be on `generate_handler!`. Direct `.invoke`, `plugin:fs`, `plugin:shell`, `__TAURI_INTERNALS__`, and capability grants outside `core:default` / `core:window:` fail. The asset protocol scope stays under artifact files.
3. **Secret readers in UI.** UI and worker Python must not mention `config.toml`, `parse_env_file`, secret env files, or API-key spellings.
4. **Parallel board clients.** No `WebSocket`, `EventSource`, MQTT, `ws://`, or a hardcoded `:8700` / `:8787`. The native shell does not `fetch` a second board. `PersistentHudServer` is constructed in `ringer.py` (tests may call it).

## Run

```bash
python3 checks/dune_import_ban.py
```

CI runs that command as `Dune import-graph (FAIL-closed)` before the unittest suite. `tests/test_dune_import_ban.py` checks the live tree and one failing example of each edge.

## Waiver

`checks/dune_import_exceptions.toml` is the only waiver file. A waiver names one edge, one path, one source pattern, a stamp, and a reason. A stamp that matches nothing fails. There is no waiver that turns an edge off.
