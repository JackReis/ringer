# Branches: which plane owns which Ringer fact

"Branch" here is a lane of ownership, not a git branch the agent should create. Ringer's git worktrees are detached at `HEAD`. The durable name of a job is `run_name`.

## Plane ownership

| Plane | Owns | Does not own |
|---|---|---|
| Open Engine memory | The decision, the card pointer, settled constraints (`ask --state` files, steering profiles the install owns) | Raw worker transcripts, another user's scoreboard |
| Open Engine harness | The worker CLI that Ringer invokes (Codex CLI, Grok Build CLI, OpenCode) | The trained model, the lab, the billing plan |
| Open Engine model | Trained artifact + lab + explicit reasoning effort, as in `docs/TAXONOMY.md` and `registry/model-identity.toml` | The harness name. "Grok Build" is a harness. |
| Open Engine skills | The orchestrator playbook (`.claude/skills/ringer/SKILL.md`), loaded when a run is about to start | Per-attempt evidence. That evidence is an observation row. |
| Multica card | project → parent → child. The child card's single deliverable is the receipt pointer from `HARVEST.md` | A second narrative status channel beside the card |
| Ringer process | Execution, the check, the local receipt files under `state_dir` | Long-term memory. Routing input only. |

A chief-of-staff agent dispatches. It reads the receipt, writes the card pointer into memory, and leaves the receipt files on the harness plane.

## `run_name` is the job branch

One human job uses one `run_name` for every round (`sd-crate-launch`, not `sd-crate-r1` / `sd-crate-r2`). Each `./ringer.py run` mints a new `run_id` (`<name>-<UTC stamp>-p<pid>`) and prepends a version under `artifacts/library.json` → `artifacts[<run_name>].versions`. The live page is `artifacts/live/<sanitized run_name>.html`, overwritten for the current round. History is `artifacts/versions/<sanitized run_name>/<sanitized run_id>.html`.

`run_name` `model-scoreboard` is reserved for `./ringer.py models --open`.

Agents addressing a job use `run_name` first, then `current_run_id` or a specific `versions[].run_id`. Round indexes in the name split one job across tabs and across memory keys.

## Worktree lane

Run-level `"worktrees": true` plus `"repo"` gives each task `git -C <repo> worktree add <workdir>/<task.key> HEAD`. That is a detached checkout of the repo's current `HEAD`, not a named branch, and not a branch an agent should push.

Consequences for readers:

- PASS deletes the worktree after copying deliverables and, when present, `report.md` / `report.html` to `<log dir>/<task.key>.worker.reports/`. Those copies are on the task as `report_paths`. The task directory is gone.
- Relative `expect_files` are unsafe here: lint flags them because the worktree disappears. Absolute paths (or the check copying out) are the deliverables that exist after PASS.
- FAIL leaves the worktree in place for a post-mortem. A later run with the same task directory stops at setup with `status: fail`, `verdict: ERROR`, `setup_error` naming `git -C <repo> worktree remove --force <taskdir>`. That message is for the orchestrator after review. A memory read records the blocker; it does not remove the worktree.
- Worker `git commit` inside the worktree dies with it. The pattern that survives is an uncommitted diff exported by the check to a path outside the worktree. Integrate by staging named paths. A checkout that holds scratch files is not a place for `git add -A`.
- Gitignored outputs (build directories) are absent from `git add -A` patch exports. If the check did not `cp` them outside the worktree, they are gone on PASS. Absence in the patch is the receipt.
- Logs do not live inside the worktree. They are `workdir/logs/<task.key>.worker.log`. Non-worktree tasks log to `workdir/<task.key>/worker.log`.

Fallback harvest (top-of-taskdir files with document/image/media suffixes, at most 8, skip over 20 MB) runs only when `expect_files` is empty and the task is not a worktree. Worktree roots are full checkouts; Ringer refuses to guess that `README.md` is the work.

## Identity lane

Every receipt is stamped with the orchestrator identity. That stamp is how Ringside and the eval log separate concurrent swarms. Resolution order is in `HARVEST.md`. A repo that should show up under its own name carries a one-line `.fleet-agent` file (letters, digits, `_`, `-` only).

Memory keys include `identity` beside `run_name`. Two identities can legally use the same `run_name`; they still share one library entry because the library key is `run_name` alone. The entry's `identity` and `current_run_id` are whoever wrote last. When that collision is possible, bind the card to `run_id`, not to the shared name.

## Host lane

`which_host` is a separate pin from identity: exactly `aegis`, `talaris`, or `box` on each new `runs/<run_id>.json`. The Multica comment before done cites `runs/<run_id>` and that field. Host-craft (`aegis`, `talaris`) cites registered-machine Shell. `box` is Scratch and stays scratch in the stamp. Contract: `docs/RECEIPTS.md`.

## Model lane

The manifest field `engine` selects the harness block in config. The manifest field `model` selects the model inside a harness that has a `{model}` placeholder. OpenCode is that harness for OpenRouter slugs. Codex and Grok Build are first-class harnesses. Cloning an engine block or hiding the model in `engine_args` makes the receipt lie about who typed.

Canonical route lives in `registry/model-identity.toml` (`noncanonical_slugs`). Lint and `run` refuse a non-sanctioned route unless `--allow-noncanonical-route` is set for a bakeoff. Historical rows stay in `runs.jsonl` and display as `misrouted` with no tier.

`task_type` is what makes the lane learnable. Untyped tasks bucket as `(untyped)` / `(none)` and teach the scoreboard nothing. Suggested vocabulary is in the README manifest table (`code-feature`, `code-fix`, `docs`, `research`, `probe`, …).

Exploration is a small slice of a 3+ task run: about one low-stakes task from `./ringer.py models --explore --task-type <type>`. The card for that task says it was an audition. Promotion and demotion are recorded as a dated line in `docs/MODEL-NOTES.md`, grounded in the executed check.

## Card shape

```text
project card     repo / Open Engine install
  parent card    the human's job          run_name
    child card   one round or one task    run_id + task key
      deliverable  pointer in HARVEST.md  one file list, one outcome
```

Parallel tasks in one run are sibling child cards under the same parent only when each child has its own disjoint deliverable. Review and fix are different runs: the reviewer does not author the fix. Persona tasks are one worker each; they do not share a session directory.

The parent card's status is the library outcome of `current_run_id` after the alive check, not a sentence synthesized beside it.
