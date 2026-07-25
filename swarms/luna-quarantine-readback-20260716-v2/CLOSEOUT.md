# Closeout — Luna Quarantine Readback v2

## Result

- Ringer run: `luna-quarantine-readback-20260716-v2-20260716T213542Z-p35344`
- Ringer exit: `0`
- Tasks: `1 PASS / 0 FAIL`
- Attempts: `1`
- Executed check: `SNAPSHOT_CHECK=PASS expected_verdict=SAFE_HOLD`
- Audit verdict at capture time: `SAFE_HOLD`
- Scope: read-only governance evidence; no implementation authorization.

## Why the captured verdict was SAFE_HOLD

The v2 snapshot at `2026-07-16T21:34:57.934063+00:00` had all quarantine invariants green, but `JAC-3609` was still `in_progress` with execution run `09c85b42-8619-4dbb-a3aa-c11996e061c3`. The manifest therefore failed closed rather than declaring terminal completion.

## Post-run live readback

After the immutable snapshot and Ringer verdict:

- `JAC-3609`: `blocked`, `executionRunId=null`
- `JAC-3626`: `done`, `executionRunId=null`
- `JAC-3592`–`JAC-3595`: each `blocked`, unassigned, `executionRunId=null`
- Luna High Planner remains pinned to `provider=copilot`, `model=gpt-5.6-luna`
- Luna agent runtime status remains `error`; the human Copilot entitlement/auth gate is therefore not claimed resolved.
- `JAC-3625` read back `done`, unassigned, `executionRunId=null` after successful projection.

This means the quarantine action reached a stable terminal board state after the captured audit, while the separate Copilot entitlement problem remains fail-closed.

## Projection evidence

- Paperclip `JAC-3625`: successful v2 verdict comment at `2026-07-16T21:36:48.720Z`, `1 pass / 0 fail`.
- Beads `hermes-klxo.2`: comment `019f6cdc-5f27-77c4-8533-9fd2fa3647e5` at `2026-07-16T21:36:49Z`.

## Preserved predecessor failure

The first immutable run, `luna-quarantine-readback-20260716-20260716T213002Z-p28304`, remains `0 PASS / 1 FAIL`. Its check encoded a stale pre-capture assumption that `JAC-3622` was `todo`; the actual captured snapshot correctly showed `blocked`. The v2 manifest repaired the check to derive its verdict from the snapshot instead of assuming a mutable queue state.

## Checksums

- Manifest: `d5c733362c082799cf796c37f53ce02298fdc38c73175ebb4f4787d5d6acfd19`
- Snapshot: `3dc4e9fc5d04319181d85641126c7adb6782d85b89a1fbad4eef868a99227f08`
- Audit: `303703789e272224b9e2b779b8d491a9512ce773999e230766c1ebbcea5b9ce8`
- Immutable receipt: `19a26263c7d2cd00186dd8c6a5d31086dd0215a86a2b28095d520224bae8402d`

## Durable paths

- Manifest: `/Users/hermes/ringer/swarms/luna-quarantine-readback-20260716-v2/swarm.json`
- Snapshot: `/Users/hermes/ringer/swarms/luna-quarantine-readback-20260716-v2/snapshot.json`
- Audit: `/Users/hermes/ringer/swarms/luna-quarantine-readback-20260716-v2/luna-quarantine-audit-v2.md`
- Immutable receipt: `/Users/hermes/.ringer/runs/luna-quarantine-readback-20260716-v2-20260716T213542Z-p35344.json`
- HTML report: `/Users/hermes/.ringer/artifacts/luna-quarantine-readback-20260716-v2-20260716T213542Z-p35344-report.html`
