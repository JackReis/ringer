# Weekly scorecard

`./ringer.py scorecard` is the fail-closed gate for the receipts plane. Do not mark done, and do not soft-ship, when this command fails. Exit 0 is the only pass.

The command prints findings. It does not rewrite `docs/RECEIPTS.md`, `docs/agent-memory/INDEX.json`, run snapshots, or this file.

`which_host` stays the locked enum in [`docs/RECEIPTS.md`](RECEIPTS.md): exactly `aegis`, `talaris`, or `box`. The Multica stamp bar remains `which_host=<aegis|talaris|box>`. `box` cites `lane=scratch` and is never a vault or a host fork of talaris or aegis.

`check-receipts` still lints run snapshots for `which_host`. A clean receipts line does not replace this gate.

## Axes

| id | What it checks |
|---|---|
| `sot_drift` | Source-of-truth agreement inside the receipts plane. |
| `agent_memory_freshness` | `harvested_on` on `docs/agent-memory/INDEX.json`, plus the docs that index lists. |

Default run checks both axes.

### sot_drift

The bar is any ERROR-class disagreement. One ERROR fails the axis. There is no silent auto-rewrite.

An ERROR includes:

- The `## Locked enum` table in `docs/RECEIPTS.md` is not the same set as `WHICH_HOSTS` in `ringer.py` (`aegis`, `talaris`, `box`).
- A Multica stamp set (`which_host=<...>`) in the contract docs differs from that enum.
- A line that locks `which_host` with "exactly" names a different set. `docs/agent-memory/HARVEST.md` must have one.
- Box prescribed onto the registered-machine Shell lane. Box stays scratch.
- `docs/RECEIPTS.md` drops `which_host=box lane=scratch` or the "never a vault" rule.
- `INDEX.json` `docs[]` paths are missing, escape the repo, or omit `docs/RECEIPTS.md` or `docs/SCORECARD.md`.
- `fleet_information_unification` drops `skill`, `vault_path`, `doctrine`, or `fleet_sot_map`, or the map drops `Ringer receipts`.
- Trust guidelines omit `./ringer.py scorecard`.
- `HARVEST.md` or `RECEIPTS.md` no longer points at this command.

`vault_path` is a vault pointer. This gate does not resolve it inside the Ringer repo. A `source_anchors` entry that is a repo path (contains `/`, no spaces) must exist.

### agent_memory_freshness

`harvested_on` is `YYYY-MM-DD`. The clock is UTC today unless `--today` is set.

Age is `(today - harvested_on)` in days. The default bar is 7 days: older than 7 fails, and age 7 still passes. A future `harvested_on` fails.

These also fail the axis:

- Missing `docs/agent-memory/INDEX.json`.
- Missing `harvested_on`, or a value that is not a real `YYYY-MM-DD`.
- A `docs[]` path that is not a file in the repo.

Override the bar with `--max-age-days N` or `RINGER_SCORECARD_MAX_AGE_DAYS`. The flag wins. A negative or non-integer override fails closed and does not fall through to 7. An invalid `--today` fails the same way.

Optional content hash: when a `docs[]` entry already has `sha256` (64 hex digits), a mismatch with the file bytes fails. Entries without `sha256` are not hashed. This harvest does not stamp hashes; adding them is a follow-on if a later card wants them required.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every axis passed. |
| 1 | One or more axes failed. The report names the axis id and the ERROR. |

Human output is one block on stdout. `--json` prints one object and nothing else:

```json
{
  "axes": [
    {"id": "sot_drift", "status": "pass", "findings": []},
    {"id": "agent_memory_freshness", "status": "pass", "findings": []}
  ],
  "ok": true
}
```

`status` is `pass` or `fail`. `ok` is true only when every axis passed.

## Multica soft-ship

Do not mark done and do not soft-ship when `./ringer.py scorecard` fails. That includes a weekly specialist close on the receipts plane. Fix the finding, re-run the command, and only then stamp the card.

## Flags

```bash
./ringer.py scorecard
./ringer.py scorecard --json
./ringer.py scorecard --max-age-days 7
./ringer.py scorecard --today 2026-09-28
./ringer.py scorecard --repo .
```

`--repo` selects the tree to read. The default is the directory that contains `ringer.py`.
