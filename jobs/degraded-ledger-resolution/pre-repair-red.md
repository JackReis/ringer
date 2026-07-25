# Pre-repair RED receipt — legacy `append-commit`

- Captured: 2026-07-14 UTC
- Scope: isolated temporary tracking root only; production `~/tracking/commit-log.md` was not modified.
- Source implementation: `/Users/jack.reis/Documents/=notes/claude/scripts/ledger.py` before repair.
- Seed candidate: `dec964d98330c56c4d44865d53b6a9c478a5214066525eb2b8e0758102a29db9`.

## Commands exercised

The command was executed twice with `LEDGER_TRACKING_ROOT` pointed at a temporary writable copy and `--repo /Users/jack.reis/Documents/=notes --count 20`.

## Fresh output

```text
--- old implementation run 1 ---
[ledger] Appended 20 commits to commit-log
--- old implementation run 2 ---
[ledger] Appended 20 commits to commit-log
{
  "entries": 1387,
  "unique_parser_identities": 1347,
  "excess_duplicates": 40,
  "bytes": 337766
}
```

## RED verdict

**RED confirmed.** Repeating an identical 20-commit window appended 40 rows and created 40 excess duplicates. The old command did not distinguish `new` from `skipped` and was not idempotent.
