# Simplifications for agent reads

The receipt files are complete on purpose: raw logs, full specs, HTML pages, a derived database, a catalog snapshot. A chief-of-staff read keeps three questions and drops the rest.

## Three questions

1. **Is it alive?** `active-runs.json` contains `run_id` (pid still up). Library `state: "live"` without that entry is a dead run; call the outcome `died`.
2. **Did the check pass?** Task `verdict == "PASS"` and `check_returncode == 0`. Library `pass` means every task passed. `ask` passing means the answer file was non-empty.
3. **Who earned the lane?** `first_try_pass_rate` for this machine, this `task_type`, from `./ringer.py models --json`. Median tokens and duration are the cost. `docs/MODEL-NOTES.md` is the one-line judgment.

Anything that does not serve those three stays on disk.

## Collapse the words

Store one of: `working`, `retry`, `pass`, `fail`, `died`, `waiting`.

Map with the table in `HARVEST.md`. Treat `error` and `timeout` as `fail` on the card, and keep the raw `verdict` (`ERROR` or `TIMEOUT`) in a single extra field so a post-mortem can still tell spawn failure from a bad check.

`finished` on a run snapshot is not an outcome. Pair it with `summary.fail` (or library `state`) before writing `pass` or `fail`.

## Bounded fields, in this order

| Need | Read | Skip |
|---|---|---|
| Label | `spec_short` or task `key` | Full `spec`, unless you are reviewing the brief |
| Why it failed | `check_output_tail` (4,000 chars) | `notes` in the JSONL row, then the worker log |
| Live activity | `activity`, else last line of `log_tail` (3 lines) | `log_tail_full` (40 lines) unless the activity line is empty |
| Proof file | `deliverables[].path` | The task directory after PASS in worktrees mode |
| History | `versions[0]` (newest) then older only if the card names that `run_id` | HTML under `artifacts/live`, `artifacts/versions`, `{run_id}.html`, `{run_id}-report.html`, `index.html` |
| Routing | `models --json` groups for one `task_type` | Full catalog, Postgres, `ringer.db` |

Worker log tail served by Ringside is 64 KiB. The check excerpt inside a steering observation is 500 characters. The eval `spec` is 500 characters. Prefer the run snapshot over reconstructing a story from those truncations.

## Surfaces that are not the memory

- **HTML artifacts** are the human view of the same JSON. Zero LLM, safe to ignore for a read.
- **Ringside.app / `hud/`** is behind the web page. Do not poll it for status.
- **Postgres `swarm_runs`** omits `model`, `task_type`, `reasoning_effort`, and `retry`. It cannot route.
- **`ringer.db`** repeats `runs.jsonl`. Read it only through `models --json` when the command chooses the db itself.
- **Catalog `--refresh`** rewrites `openrouter-catalog.json`. A read uses the snapshot already on disk.
- **Steering profiles** are install policy. Agents append observations by running Ringer; they do not edit profiles or change rule status (`candidate`, `confirmed`, `refuted`, `stale-pending-reverify`).
- **Self-update state** (`self-update.json`) is about the Ringer checkout, not the job.

## Checks that look like status and are not

- **Baseline** (`./ringer.py run <manifest> --baseline`) runs checks with no workers and writes no eval rows. A failing assertion about the new behavior is the expected baseline. A failing assertion about unchanged behavior means the check is wrong. Do not file a baseline fail as a worker receipt.
- **Lint** warns; it does not stop `run`. A clean lint line is not a PASS.
- **`expect_files`** is the floor. The check is the receipt. A file can exist and still fail.
- **Silent check output** gets a Ringer line: check failed with no output. That line means the check needs a reason string, and the retry had nothing to bite on.
- **Token totals** sum attempts. Grok Build often reports none (`worker_tokens: null`); plan cost is "included," not zero work.
- **`children`** on a task is a process-tree count for the HUD. It is not a deliverable count.

## One job, one key, one card

Do not invent round keys, batch keys, or a second status doc. Re-read `artifacts[<run_name>]` and replace the card's pointer fields in the memory store with the new version. Leave Ringer's files untouched while you do it.

Same-second launches are already distinct `run_id`s (pid suffix). You do not need to disambiguate them by renaming the job.

## What not to import

Scoreboards are per machine and per workload. A proven tier elsewhere is `untested` here until `runs.jsonl` on this machine says otherwise. Do not copy `runs.jsonl`, `ringer.db`, or `docs/MODEL-NOTES.md` conclusions from another user into this install's routing.

Redacted tasks contribute a verdict and a model to the scoreboard. They do not contribute a brief. Skip their logs.

Reserved fixture model names and unattributed rows are already excluded from tiers. Do not "fix" them by assigning an engine default.
