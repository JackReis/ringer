# Harvest: how an agent reads Ringer receipts

Ringer is the harness-and-check plane in the Open Engine / Multica loop. Open Engine keeps memory, harness, model, and skills as separate primitives. Multica is the coordination plane: one repo per project, cards nested project → parent → child, one inspectable deliverable per child card. Ringer does not store that memory. Its local files are routing receipts: an executed check, a copied deliverable, and the model that produced them.

This map is for a chief-of-staff agent that must answer "what happened, and which lane earned it" without loading a swarm into its own context. The Sep 19 Ankit/Jack working direction is the placement rule: Ringer data routes work; the Multica child card holds the pointer.

Defaults below assume `state_dir = ~/.ringer` (`RINGER_HOME` overrides the home root; `state_dir` in `~/.config/ringer/config.toml` overrides the state root). Paths are relative to that root.

## What counts as a receipt

A receipt is evidence an executed check produced. Worker prose is not a receipt. These are:

| Receipt | Where | What it proves |
|---|---|---|
| Attempt row | `runs.jsonl` (one JSON object per line) | This attempt's verdict came from running the check. `verify_method` is `executed-check`. |
| Run snapshot | `runs/<run_id>.json` | Per-task status, verdict, check exit, check excerpt, deliverable copies, log path. Flushed about once a second while the process lives. |
| Library version | `artifacts/library.json` → `artifacts[<run_name>].versions[]` | One finished round of a job: outcome, pass/fail counts, deliverable names and paths. Newest version is first. Cap is 20. |
| Deliverable copy | `artifacts/deliverables/<run_id>/<task_key>/<filename>` | The file survived the run. In worktrees mode the task directory is deleted on PASS; this copy is what remains. |
| Steering observation | `<steering-dir>/observations/ringer/<YYYY-MM-DD>.jsonl` | One attempt row for model-behavior evidence. It never changes a steering profile. |

`ask` is the weak receipt. Its check is that `answer.md` exists and is non-empty. It proves a worker wrote something. The orchestrator still reads the answer.

## Read order

Stop at the first surface that answers the question. Do not open the next file "to be sure" when the bounded field already holds the evidence.

1. **Job pointer.** If you already have `run_name`, open `artifacts/library.json` and read `artifacts[<run_name>]`. Fields: `state`, `identity`, `current_run_id`, `updated_at`, `live_path`, `versions`.
2. **Alive check.** `state: "live"` in the library or in a run snapshot means the writer intended the run to still be going. Confirm it. `active-runs.json` is a map of `run_id` → `{pid, identity, run_name, workdir, started_at}`. A read of that file drops entries whose pid is dead. A `run_id` absent from the pruned map is not running. `/api/library` on Ringside reconciles stale library rows to `died` before it responds; a direct file read does not, so do the pid check yourself.
3. **Task truth.** Open `runs/<current_run_id>.json`. For each task use `status`, `verdict`, `check_returncode`, `check_timed_out`, `attempts`, `setup_error`, and `check_output_tail` (capped at 4,000 characters). `verified` is the human sentence for what the check was meant to prove; the exit code is the proof.
4. **Failure context.** For `retrying`, `fail`, `TIMEOUT`, or `ERROR`, read `check_output_tail` first. Open `log_path` only when the excerpt does not say why. The raw log is verbatim worker output plus `[ringer.py]` lines. It is the post-mortem, not the summary.
5. **Deliverable.** Read `deliverables[]` (`name`, `path`, `bytes`). The path is the copy under `artifacts/deliverables/`. `deliverable_notes` records skips (over 20 MB, or more than 8 fallback files).
6. **Routing.** For "which model should type the next task," run `./ringer.py models --json --task-type <type>` against this machine's `runs.jsonl`. The routing number is `first_try_pass_rate`. `pass_rate` includes the single retry. Another machine's log is not this user's evidence.

Ringside (`./ringer.py hud`, `http://127.0.0.1:8700`) is the human page. Agents use the JSON it is built from. Useful localhost GETs, all on that port: `/api/runs` (newest 12 run snapshots plus `active`), `/api/library`, `/api/models`, `/logs/<run_id>/<task_key>` (last 64 KiB of the worker log). The per-run server on port 8787 (`/state.json`, `/logs/<task_key>`) exists for `--browser`. It is not the watch surface.

## Status words

Three vocabularies sit on top of each other. Read the one that matches the file you opened.

**Attempt verdict** (`verdict` on a task, and `verdict` in `runs.jsonl`): `PASS`, `FAIL`, `TIMEOUT`, `ERROR`.

- `PASS` — check exit 0, expected files present and non-empty, worker did not time out or error.
- `FAIL` — check ran and did not pass.
- `TIMEOUT` — worker timer (`timeout_s`, default 900) or check timer (60s) fired.
- `ERROR` — worker failed to spawn, or task setup failed before a worker existed (`setup_error` is set). A cancelled run marks still-open tasks `fail` / `ERROR`.

**Task status** (lowercase, the live lane): `queued` → `running` → `verifying` → `pass`, or → `retrying` → `running` → `verifying` → `pass` or `fail`. Default `max_attempts` is 2. `ERROR` does not retry.

Plain-English buckets used on the results page:

| Bucket | Statuses | Say |
|---|---|---|
| pass | `pass` | finished & checked |
| working | `running`, `verifying` | working |
| retry | `retrying` | sent back — redoing |
| fail | `fail`, `error`, `timeout`, `died` | failed |
| waiting | anything else, including `queued` | waiting |

**Run / library outcome:**

| Surface | Values | Meaning |
|---|---|---|
| `runs/<run_id>.json` `state` | `live`, `finished` | The writer sets `finished` only in `finish()`. A killed orchestrator leaves the file `live` forever. |
| `runs/<run_id>.json` `summary` | `null` until finish, then `{pass, fail, tokens}` | Absent summary means the run did not finish cleanly. |
| Library `state` | `live`, `pass`, `fail`, `died` | `pass` when a finished run has zero task failures; `fail` when it does not. `died` when a library row was `live` and its `current_run_id` is gone from `active-runs.json`. |
| Process exit | `0` if every task `status` is `pass`, else `1` | Same bar as library `pass`. |

`totals.running` counts `running`, `verifying`, and `retrying`. `totals.done` is pass + fail only.

The native Ringside.app under `hud/` recomputes `died` on its own (unfinished, pid dead or snapshot older than 30s, hidden after 300s; finished rows hidden after 60s). That app is a parked prototype. Agents follow the web page's files: run JSON plus `active-runs.json` plus library reconcile.

## Run snapshot fields an agent keeps

Top level: `run_id`, `run_name`, `identity`, `state`, `finished`, `pid`, `started_at`, `elapsed_s`, `max_parallel`, `totals`, `summary`, `pass`, `fail`, `tokens`, `report_ready`, `live_path`, `report_path`.

`run_id` shape: `<sanitized-run_name>-<UTC yyyymmddThhmmssZ>-p<pid>`.

Per task, keep: `key`, `status`, `verdict`, `engine`, `model`, `attempts`, `task_type` is on the eval row (the snapshot stores engine and resolved model), `check_returncode`, `check_output_tail`, `setup_error`, `log_path`, `deliverables`, `elapsed_s`, `tokens`.

`spec` in the snapshot is the full brief unless `redact_spec` replaced it with `[redacted request packet]`. The eval row stores at most the first 500 characters of that same text. Prefer `spec_short` (120 characters) when you only need a label.

Identity stamped on the run, in order: `--identity`, then `FLEET_IDENTITY` or `RINGER_IDENTITY`, then the nearest `.fleet-agent` file walking up from the working directory, then `identity_default`, then the short hostname.

## Eval row fields

Written by `EvalLogger.log_attempt` to `runs.jsonl` (config may point `jsonl_path` elsewhere):

`run_id`, `pattern` (`ringer-py`), `task_key`, `spec`, `worker_engine`, `shepherd_model` (`none (ringer.py)`), `verify_method` (`executed-check`), `verdict`, `duration_ms`, `worker_tokens`, `notes`, `orchestrator`, `model`, `reported_model`, `expected_model`, `reasoning_effort`, `task_type`, `retry`, and on the JSONL line also `logged_at`, `log_sink`, `fallback_reason`.

`model` is the harness-reported model when the log names one, otherwise the manifest/config resolution. When they differ, `expected_model` holds the resolution and the worker log gains a `[ringer.py] identity:` line. `retry` is false on attempt 1.

`notes` embeds worker return code, model, task type, missing `expect_files`, and the first 2,000 characters of check output. Read `check_output_tail` from the run snapshot before parsing `notes`.

A Postgres sink, when configured, inserts a narrower row and drops `model`, `reasoning_effort`, `task_type`, and `retry`. Routing reads the JSONL. The derived SQLite file `ringer.db` (`./ringer.py db sync`) is a cache of that JSONL. Rebuild it only when a human asks; a memory read uses `./ringer.py models --json`.

Scoreboard columns, in order: Model, Lab, Harness, API/Plan, Tier, Tasks, First try, Pass, Tokens (median), Speed (median), Last used, Notes. Tiers: proven (3+ tasks of that `task_type`, first-try ≥ 0.67), probation (some evidence, not yet proven), untested (catalog only). Rows with an empty `model` stay under `(unattributed legacy rows)` and do not rank. `misrouted` rows keep their real harness and plan, resolve to the canonical model, and do not rank. Fixture names `proven-model`, `probation-model`, `mock-model`, and `test-model` never appear on a scoreboard.

Judgment that the numbers cannot carry lives in `docs/MODEL-NOTES.md` in this repo. The newest dated bullet for a model is the Notes cell.

## What lands on the Multica child card

One card, one deliverable. The deliverable is a pointer, small enough to re-read:

- `run_name` (the job, stable across rounds)
- `run_id` of the round you are accepting
- library `state` (`pass`, `fail`, or `died`)
- `tasks_pass`, `tasks_fail`
- deliverable `name` + `path` for each file the card claims
- `engine`, `model`, `task_type`, `retry` for the lane decision
- one sentence from `verified`, plus `check_returncode`

Leave worker logs, full specs, and HTML pages on disk. Link `live_path` for the human. If the file is not in `expect_files` (or the pass-time fallback harvest), it is a harvest gap: fix the manifest, do not paste the missing file into the card from a terminal dump.

## Secrets stay in their files

`redact_spec` / `ask --redact` replaces the brief in run state, the logged command line, and the eval row. It does not rewrite `worker.log`. A worker that echoes its prompt leaves the secret in the raw log. A memory read skips `log_path` and `check_output_tail` when the task is redacted, and it never copies those fields onto a card.

Do not open `[eval.postgres] env_file`, engine auth files, or catalog credentials. Config keys named like passwords are out of scope for this harvest. Catalog snapshots (`openrouter-catalog.json`, `openrouter-catalog.changes.jsonl`) are public model metadata; read them with `./ringer.py catalog --file <snapshot> --json`. A memory read does not pass `--refresh`.

## Agents read; Ringer writes

Run JSON, `library.json`, `active-runs.json`, and the HTML artifacts are replaced atomically by Ringer's own writer. `runs.jsonl` and steering observations are append-only. An agent harvesting memory does not write, truncate, or replace those paths, and does not pass a flag whose job is to overwrite them. The derived scoreboard database and the catalog snapshot are the same: read, or regenerate only when the human asked for a refresh.

Source of this map: `StateWriter.snapshot`, `artifact_outcome_from_state`, `append_artifact_library_version`, `read_active_runs`, `EvalLogger.log_attempt`, `verdict_for`, `_harvest_deliverables_on_pass`, and the Ringside routes in `PersistentHudServer`.

## Fleet trust guidelines

Vault and skill source of truth is the fleet-information-unification skill and `Architecture/fleet/FLEET-INFORMATION-UNIFICATION-DOCTRINE-20260927.md` (Multica AEGI-164 / AEGI-186, PASS stamp `01a0e549-8ddd-7624-b95d-9355e6d3d314`). These pointers cover harvest, draft, and review. They do not change receipt files.

- Prefer Cursor cloud for draft/review.
- Trust rotation: Claude Code → ChatGPT/Codex → Gemini (Antigravity) → Kimi.
- Soft ship: draft → review → Multica stamp → apply (profile-mutate way-of-work).
- CoS may soft-ship after stamp. Jack-gated: `--replace`, secrets, spend, irreversible.

Fleet source-of-truth map: Multica assigns · Open Engine protocol · Kata closes · Hermes executes · Ringer receipts · prover proves · Vault narrative · Dune constraints.

On that map, Ringer stays the receipts plane. A harvest read still does not write those files.
