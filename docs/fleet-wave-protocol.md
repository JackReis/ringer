# Fleet Wave protocol v1

`tools/fleet_wave.py` is a small, fail-closed controller around Ringer. It does not replace Ringer: **Beads is canonical work authority, Ringer owns the verdict, and Paperclip is visibility only**.

## Manifest

Start from `templates/fleet-wave/manifest-v1.json`; the machine-readable contract is `schema/fleet-wave.v1.json`. Task keys must exactly match the referenced Ringer manifest. Evidence must be `strong` and either `objective` (replayable check) or `judgmental` (also needs a judge receipt). Version 2 and later manifests must name `supersedes`. `existing_ids` are reconciled; identifiers in examples are placeholders and are never implicit defaults.

All executable paths are explicit. This prevents accidental use of live state in tests and automation.

## Prepare

```sh
python3 tools/fleet_wave.py prepare wave.json \
  --bd-bin /explicit/path/to/bd \
  --ringer-bin /explicit/path/to/ringer.py \
  --paperclip-bin /explicit/path/to/paperclip \
  --receipt .fleet-wave/prepared.json
```

Prepare validates the versioned manifest and evidence policy, claims the canonical Bead and reads it back, reads existing Bead IDs, invokes `ringer lint` before `ringer run --dry-run`, and writes a SHA-256-bound prepared receipt. No real run is dispatched by this controller. If Beads is unavailable, `--degraded-no-dispatch` records an explicit non-authorizing receipt and skips all Ringer commands.

## Post-run

```sh
python3 tools/fleet_wave.py post-run wave.json \
  --bd-bin /explicit/path/to/bd --ringer-bin /explicit/path/to/ringer.py \
  --paperclip-bin /explicit/path/to/paperclip \
  --prepared-receipt .fleet-wave/prepared.json \
  --run-state /path/to/ringer-run-state.json \
  --receipt .fleet-wave/post-run.json
```

Post-run rejects changed manifests, independently checks expected files and executes every Ringer check again, and requires passing Ringer task/run verdicts. Judgmental work additionally requires `--judge-receipt`; it must be newer than preparation, pass, and bind the wave ID and manifest hash. The resulting receipt binds the prepared receipt and run state hashes.

Reconciliation is ordered: every Beads comment must succeed before any Paperclip comment is attempted. A Beads failure stops projection. Commands do not infer or call example IDs.
