# routine-queue-sweep

A Ringer manifest template for Paperclip Routine queue coordination. Scans the Paperclip board, detects stale issues, and generates routing recommendations — all with executed checks and auto-projection to the routine's active issue.

## When to reach for it

- A Paperclip Routine fires on a schedule (e.g., daily at 9am or every 4 hours) to review the fleet's task queue.
- You need verified board state — not an agent's summary — with structured data for downstream routing decisions.
- The Coordinator agent needs a routing report to decide reassignment, unblocking, or escalation actions.

## Tasks

| Key | What it does | Check |
|-----|-------------|-------|
| `scan-board` | Queries Paperclip API for all issues, groups by agent and status | Asserts JSON has total_issues, by_agent, blocked_issues |
| `stale-detection` | Reads board scan, flags issues stale >48h in in_progress/blocked | Asserts output is a valid JSON array |
| `routing-recommendations` | Synthesizes scan + stale data into a markdown routing report | Asserts report has all required sections |

## Fill-in guide

1. Set `{{ROUTINE_NAME}}` to a short slug matching the Paperclip Routine title.
2. Set `{{WORKDIR}}` to an absolute path for task subdirectories.
3. Set `{{ROUTINE_ID}}` to the Paperclip Routine UUID.
4. Set `{{GOAL_ID}}` or remove the field if no goal is linked.
5. Set `{{MODEL}}` to the model for queue-sweep workers.
6. Run `./ringer.py lint templates/routine-queue-sweep/manifest.json`.

## Composition

- The `scan-board` task can be lifted into any manifest that needs current Paperclip board state.
- Pair with `routine-health-check` for a combined health + queue sweep routine.
- The `routing-recommendations` output feeds directly into Coordinator decision-making or can be posted to a Paperclip issue for human review.