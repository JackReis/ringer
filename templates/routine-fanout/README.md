# routine-fanout

A Ringer manifest template for Paperclip Routine execution. When a Paperclip Routine fires and the assigned agent needs to produce verified work products in parallel, this template wires the Ringer swarm's verdicts back to the routine's active issue and (optionally) a linked goal.

## When to reach for it

- A Paperclip Routine fires on schedule (or manually) and the work is decomposable into 2-5 parallel tasks.
- You need the Ringer verdict (pass/fail counts, run ID, task-level results) auto-projected to the routine's active issue via `paperclip_projector.py`.
- The routine's work products are files that can be checked with shell commands.

## How it wires to Paperclip

Each task in the manifest carries these cross-reference fields:

| Field | What it does |
|-------|-------------|
| `paperclip_issue` | Paperclip issue ID — the projector posts the full verdict table as a comment |
| `routine_id` | Paperclip Routine UUID — the projector posts a progress comment to the routine's active issue |
| `goal_id` | Paperclip Goal UUID — the projector posts a progress comment to the goal's most recent in-progress issue |

After a Ringer run completes, `paperclip_projector.py` (in `~/.ringer/hooks/`) reads the run state JSON, extracts these fields from task specs, and posts the verdict to each linked entity. The projection is fail-open — a posting error is logged but never blocks the run.

## Fill-in guide

1. Set `{{ROUTINE_NAME}}` to a short slug matching the Paperclip Routine title.
2. Set `{{WORKDIR}}` to an absolute path where task subdirectories will be created.
3. Set `{{ROUTINE_ID}}` to the Paperclip Routine UUID (from the routines API or dashboard).
4. Set `{{GOAL_ID}}` to the Paperclip Goal UUID, or remove the field if no goal is linked.
5. Set `{{PAPERCLIP_ISSUE}}` to the issue ID if the routine has an existing issue, or remove it.
6. For each task: fill `{{TASK_N_SPEC}}`, `{{TASK_N_CHECK}}`, `{{TASK_N_EXPECT_FILE}}`, and `{{TASK_N_VERIFIED}}`.
7. Set `{{MODEL}}` and `{{TASK_TYPE}}` to match the engine and work category.
8. Run `./ringer.py lint templates/routine-fanout/manifest.json` to validate.

## Check guidance

Checks must be shell commands that exit 0 on success and print a reason on failure. A silent `exit 1` gives the retry prompt no failure context and records an undiagnosable eval row. Prefer `diff` over `diff -q`; prefer an assert with a message over a bare test.

## Composition

- Pair with `routine-queue-sweep` when the routine's first task is "scan the board" and subsequent tasks act on findings.
- Pair with `routine-health-check` when the routine is a health monitoring sweep.
- Lift individual tasks into any other manifest when you need routine projection on a non-routine swarm.