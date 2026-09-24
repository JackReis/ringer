# CUTOVER — Multica receipt in-tree (AEGI-78)

**Status:** FORK ONLY — do **not** swap live PATH until CoS/Jack say go.

## What this branch does
- After Judge rows land in `~/.ringer/runs.jsonl`, `RingerRunner` calls
  `hooks/multica_receipt.py` to post one Multica comment on `MULTICA_ISSUE_ID`.
- Feature flag: `RINGER_MULTICA_RECEIPT=0` disables; default on when issue id present.
- Fail-open: Multica post failures log a warning and **do not** flip PASS→FAIL.
- Comment-only (no `issue update`, no agent wake). Idempotent on `run_id` via
  `~/.ringer/receipts/multica-posted.json`.

## Live PATH (must stay unchanged until gate)
- Launcher: `/Users/hermes/.local/bin/ringer` → `python3.12 /Users/hermes/ringer/ringer.py`
- SAFE-NOW wrapper remains: `~/.hermes/bin/ringer-with-receipt` + `ringer-multica-receipt`

## Cutover steps (Jack/CoS gate)
1. Land multi-model synthesis with **ship** or **fix-then-ship** (see evidence pack).
2. Merge/cherry-pick this branch onto the owned working fork tip that the launcher pins
   (`/Users/hermes/ringer`, currently `ankit-engine-env-20260905` lineage).
3. Smoke: isolated state dir canary
   ```bash
   RINGER_HOME=/tmp/ringer-receipt-canary MULTICA_ISSUE_ID=AEGI-78 \
     /Users/hermes/.local/bin/python3.12 \
     /Users/hermes/ringer/.worktrees/multica-receipt-20260924/ringer.py \
     # …tiny manifest…
   ```
4. Confirm Multica comment on AEGI-78; confirm `/Users/hermes/.local/bin/ringer` still
   points at the post-merge tree (no wrapper required for new runs with `MULTICA_ISSUE_ID`).
5. Keep wrapper for one release as fallback; then deprecate.

## Rollback
```bash
RINGER_MULTICA_RECEIPT=0   # immediate, no restart
# or revert the merge commit on the owned fork; launcher path unchanged
```

## C-2
Repair the receipt joint around Multica only. Do **not** rewrite `Vault/canon.md`.
