# Ringer reliability tools run — closeout

Date: 2026-07-14
Run ID: `ringer-reliability-tools-20260714-1447-20260714T195347Z-p58930`
Status: complete and independently verified

## Execution receipt

- Ringer exit code: 0
- Tasks: 3 PASS / 0 FAIL
- Attempts: 1, 1, 1
- Final eval rows: 3 PASS using `executed-check`
- Copied run deliverables: 6 present
- Immutable state: `~/.ringer/runs/ringer-reliability-tools-20260714-1447-20260714T195347Z-p58930.json`
- HTML report: `~/.ringer/artifacts/ringer-reliability-tools-20260714-1447-20260714T195347Z-p58930-report.html`

## Hardened outputs

The immutable Ringer receipt and copied deliverables were not rewritten. Live-data exercise found and fixed two fixture gaps in the isolated work directories:

1. The evidence verifier now filters unrelated rows in the shared append-only eval log.
2. The manifest checker now recognizes and validates Ringer's required `workdir` field.

Regression and live verification after repair:

- `run-evidence-verifier`: 13 tests pass; live run report valid.
- `manifest-policy-checker`: 14 tests pass; live manifest strict report valid.
- `clean-streak-auditor`: 14 tests pass; live latest-1 streak report valid.
- Total: 41 tests pass.

Machine-readable reports:

- `live-run-verification.json`
- `manifest-policy-report.json`
- `clean-streak-report.json`

Manifest: `swarm.json`
Design record: `/Users/hermes/=notes/.hermes/plans/2026-07-14-ringer-reliability-tools-design.md`
