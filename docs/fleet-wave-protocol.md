# Fleet Wave protocol v1

`tools/fleet_wave.py` is a stdlib-only, fail-closed controller. Beads is work authority, Ringer owns execution evidence, Paperclip is visibility, Ringside is read-only, and Bifrost remains `null` unless genuine correlation evidence is added in a future protocol.

## Bound manifest

Use `templates/fleet-wave/manifest-v1.json` and `schema/fleet-wave.v1.json`. Every schema string declared non-empty requires at least one non-whitespace character. Standard JSON Schema cannot compare `issue_id` against `existing_ids` or compare task `key` properties across task objects; the schema documents these semantic constraints and the controller enforces them fail-closed (issue IDs cannot be repeated in `existing_ids`, and duplicate task keys are rejected). The filename is exactly `manifest-vN.json`. Version N>1 uses `supersedes: {"path": "manifest-vN-1.json", "sha256": "..."}`. The manifest binds the Beads authority `host`, `store`, `claimant`, and child `issue_id`; CLI authority arguments must exactly match, `host` must equal the controller's `socket.gethostname()`, and every `bd` process receives the bound store as `BEADS_DIR`. Paperclip may identify an open parent while the child Bead closes.

## Transitions

All executable paths and authority values are explicit. Tests use fakes; never point tests at live ledgers.

```sh
python3 tools/fleet_wave.py prepare manifest-v1.json \
 --bd-bin /path/bd --ringer-bin /path/ringer --paperclip-bin /path/paperclip \
 --ringside-bin /path/read-only-client --beads-host HOST --beads-store STORE \
 --beads-claimant USER --receipt prepared.json

python3 tools/fleet_wave.py execute manifest-v1.json \
 --bd-bin /path/bd --ringer-bin /path/ringer --beads-host HOST --beads-store STORE \
 --beads-claimant USER --prepared-receipt prepared.json --receipt executed.json

python3 tools/fleet_wave.py accept manifest-v1.json \
 --bd-bin /path/bd --ringer-bin /path/ringer --paperclip-bin /path/paperclip \
 --ringside-bin /path/read-only-client --beads-host HOST --beads-store STORE \
 --beads-claimant USER --prepared-receipt prepared.json --execute-receipt executed.json \
 --accept-mode close --receipt accepted.json
```

**Prepare** is read-only with respect to Beads: it runs exactly `bd show ID --json` (with the bound `BEADS_DIR`) for the child and each existing ID, parses only an exact object or one-item array, and requires each returned `id` to match. The child must already have exact `in_progress` status and claimant. It then reconciles Paperclip IDs with equivalent exact JSON readback, lints, and dry-runs before posting a prepared Paperclip receipt.

**Execute** validates the prepared receipt fail-closed before dispatch: its schema version, `prepared` event, timezone-aware timestamp, exact allowed/required fields and types, literal `dispatch_authorized: true`, authority, manifest, and Ringer hashes must all match. It then re-reads the exact claim immediately before invoking the configured Ringer executable. It snapshots `<ringer_state_dir>/runs`, requires exactly one new JSON state file, and hash-binds it atomically. The execute receipt likewise has an exact field/type contract, timezone-aware timestamp, and hashes binding the manifest, Ringer manifest, prepared receipt, and run state.

**Accept** validates the prepared and execute receipts with those exact fail-closed contracts and rejects a resolved `run_state_path` unless it is beneath the manifest-bound `<ringer_state_dir>/runs` directory, preventing traversal and path substitution. It then validates Ringer's real finished shape (`state=finished`, `finished=true`, exact pass/fail totals and summary, and every task `status=pass`, `verdict=PASS`, `check_returncode=0`). No top-level verdict is required. Every check is replayed in a fresh `/bin/sh` subprocess in the state-recorded task directory; expected paths must stay beneath that directory. Judgmental tasks additionally require an independent judge attestation created after execution, with an exact object shape, non-empty identity/criteria/rationale, exact ordered judgmental task keys, and bindings to the manifest, executed receipt SHA-256, and run-state SHA-256. Its SHA-256 is recorded in acceptance.

Acceptance performs both read-only Ringside queries before any terminal Beads or Paperclip write and binds each full parsed response, endpoint, and raw-response SHA-256 into the exact terminal receipt. A Ringside failure therefore causes zero terminal writes. Acceptance then writes that exact terminal receipt to the canonical child Bead first. Only explicit `--accept-mode close` closes it using exactly `bd close ID --reason TEXT --json`, where `TEXT` is deterministically bound as `Fleet Wave accepted: wave_id=WAVE; manifest_sha256=MANIFEST_SHA256; execute_receipt_sha256=EXECUTE_RECEIPT_SHA256` and recorded as `beads_close_reason` in the receipt, then exactly reads back the closed Bead. Any Beads failure blocks Paperclip projection. Paperclip parents are never closed. Ringside walkthroughs call only `get BASE/api/runs` and `get BASE/api/library` and bind their read-only responses into the acceptance receipt.
