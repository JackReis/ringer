# routine-health-check

A Ringer manifest template for Paperclip Routine health monitoring sweeps. Probes all fleet services in parallel and synthesizes a health report with an overall PASS/FAIL verdict.

## When to reach for it

- A Paperclip Routine fires on a schedule (e.g., every 15 or 30 minutes) to check fleet health.
- You need verified, executed health checks — not an agent's summary — with results auto-projected to the routine's active issue.
- The fleet has services across API, memory, and infrastructure layers that each need independent probing.

## Tasks

| Key | What it does | Check |
|-----|-------------|-------|
| `api-health` | Probes Paperclip, Ringside, Bifrost HTTP endpoints | Parses JSON, asserts all three returned 200 |
| `memory-plane-check` | Probes OB1, Hindsight, Honcho endpoints | Parses JSON, asserts all three are responding |
| `container-status` | Runs `docker ps` and `lsof` for fleet ports | Asserts output contains container and port sections |
| `summary-report` | Synthesizes all three probes into a markdown report | Asserts summary has all required sections |

## Fill-in guide

1. Set `{{ROUTINE_NAME}}` to a short slug matching the Paperclip Routine title.
2. Set `{{WORKDIR}}` to an absolute path for task subdirectories.
3. Set `{{ROUTINE_ID}}` to the Paperclip Routine UUID.
4. Set `{{GOAL_ID}}` or remove the field if no goal is linked.
5. Set `{{MODEL}}` to the model for health-check workers (cheap models work well for probes).
6. Run `./ringer.py lint templates/routine-health-check/manifest.json`.

## Composition

- Use as the health-check arm of a broader routine that also does queue sweeps.
- The `container-status` task can be lifted into any manifest that needs infrastructure context.
- The `summary-report` task depends on the other three completing first — adjust `max_parallel` if you need sequential ordering.