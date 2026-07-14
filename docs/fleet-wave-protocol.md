# Fleet Wave protocol v1

`tools/fleet_wave.py` is a stdlib-only, fail-closed controller implementing the active Fleet Wave authority order. Beads is sole work/disposition authority; Paperclip is a one-way projection; Ringer executes; Ringside performs GET-only observation; Bifrost remains unproven/null.

## Manifest and strong checks

Start from `templates/fleet-wave/manifest-v1.json`; validate against `schema/fleet-wave.v1.json`. The immutable manifest binds the full Beads tuple (`issue_id`, host, store, claimant), unique `attempt_id`, version/digest, Ringer manifest/state directory, and tasks. Retries use a new attempt. Supersession uses the immediately preceding immutable manifest path/digest.

Every work type—including `other`—requires a criterion-specific `check` and at least two structured executable negative controls (`name` plus fixture-mutating `setup`). Execute creates an immutable content-addressed inventory/snapshot. Acceptance launches `replay-one` as a distinct checker subprocess with a minimal environment, validates the snapshot digest, and never reruns against the mutable worker directory. Every negative fixture is derived from that snapshot and must make the same check exit nonzero. This rejects `true`, `exit 0`, wrappers, and test-only/existence-only checks; expected-file existence is only an artifact precondition.

Paperclip readback accepts the requested key only when it equals returned `identifier` or canonical `id`; both values are retained in the prepared receipt. Beads readback remains exact for ID, status, claimant, host and store.

## Commands and state order

```sh
python3 tools/fleet_wave.py prepare manifest-v1.json --bd-bin BD --ringer-bin RINGER \
 --paperclip-bin PAPERCLIP --ringside-bin RINGSIDE --beads-host HOST \
 --beads-store STORE --beads-claimant CLAIMANT --receipt prepared.json
python3 tools/fleet_wave.py execute manifest-v1.json --prepared-receipt prepared.json \
 --bd-bin BD --ringer-bin RINGER --beads-host HOST --beads-store STORE \
 --beads-claimant CLAIMANT --receipt executed.json
python3 tools/fleet_wave.py accept manifest-v1.json --prepared-receipt prepared.json \
 --execute-receipt executed.json --bd-bin BD --ringer-bin RINGER \
 --paperclip-bin PAPERCLIP --ringside-bin RINGSIDE --beads-host HOST \
 --beads-store STORE --beads-claimant CLAIMANT --receipt terminal.json
```

Prepare invokes the fakeable atomic Beads `claim acquire` CLI/CAS operation, binding claimant, attempt, authority and dispatch reservation. Every claim error writes local `UNKNOWN_DEGRADED`, `dispatch_allowed:false`, non-authoritative truth, exits nonzero, and performs no Ringer or Paperclip operation. Execute renews with the prepared issue version immediately before dispatch. It requires the same claim ID and exactly one new immutable Ringer run receipt.

The exact state order is `INTAKE → LEDGERED → CLAIMED → MANIFEST-vN → LINTED → DRY-RUN → PAPERCLIP PREPARED RECEIPT → RINGER RUN → INDEPENDENT CHECK REPLAY → FRESH JUDGE` (only for judgmental work) `→ BEADS ACCEPTED/BLOCKED → Paperclip mirror → Ringside GETs`. A prepared receipt may carry the pre-execution states as one immutable composite bundle, but every transition is separately predecessor-chained; it never claims a walkthrough. Judgmental criteria require a fresh never-resumed Judge, a configured harness-secret HMAC over the complete attestation, and normalized principal/session non-overlap with controller and replay checker. There is no receipt-only pseudo-terminal: acceptance always closes and reads back Beads. Projection degradations use unique stage-specific immutable receipts.

Canonical JSON is UTF-8 JSON with sorted keys and separators `,`/`:`. `integrity.digest` is SHA-256 of that canonical object with `integrity` removed; predecessor digests ending in receipt files are SHA-256 of the immutable serialized file. Consumers recompute outer integrity and every inner transition integrity. `schema/fleet-wave-receipt.v1.json` is the companion schema and matches runtime field names, types and nullability; its E3 condition requires accepted receipts to carry command, zero exit status, tool hashes, environment digest, machine result, and separate stdout/stderr digests.

## Explicit fail-closed block

Every fallible stage has an operator-invocable durable edge:

```sh
python3 tools/fleet_wave.py block manifest-v1.json --predecessor-receipt prior.json \
 --failed-stage LINTED --reason-code lint_failure --bd-bin BD --ringer-bin RINGER \
 --beads-host HOST --beads-store STORE --beads-claimant CLAIMANT --receipt blocked.json
```

Allowed failed stages are LEDGERED, CLAIMED, MANIFEST-vN, LINTED, DRY-RUN, PAPERCLIP PREPARED RECEIPT, RINGER RUN, INDEPENDENT CHECK REPLAY, and FRESH JUDGE. The command revalidates the claim, appends the chained `BEADS BLOCKED` receipt to Beads, and writes it append-only locally. Failures never become acceptance; projection outages are the sole degraded post-terminal case.
