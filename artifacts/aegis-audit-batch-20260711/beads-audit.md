# Beads Audit: hermes-wvl, hermes-9ad, hermes-bcg

Date: 2026-07-11

## Source / Evidence

This audit used only the staged read-only evidence in this directory:

- `ready.json`: queue summary for `hermes-wvl`, `hermes-9ad`, and `hermes-bcg`, including ID, title, status, priority, issue type, and dependency counts.
- `hermes-wvl.txt`: detailed Bead view with problem statement, reproduction, scope, workflow gate, evidence, design, notes, labels, and acceptance criteria.
- `hermes-9ad.txt`: detailed Bead view with epic description and child Bead progress.
- `hermes-bcg.txt`: detailed Bead view with notes, acceptance criteria, explicit dependency on `hermes-csy`, and operational comments.

No Bead state was altered. `worker.log` was not used because the requested validation scope was `ready.json` plus the matching `.txt` detail files.

## Summary Table

| Bead | Identity | Current status / priority | Readiness / dependency condition | Acceptance criteria quality | Evidence sufficiency | Blockers | Recommended next action |
|---|---|---|---|---|---|---|---|
| `hermes-wvl` | Bug: fix Agentic OS Command Centre Claude CLI PATH resolution for Skills chat. | `open`, P1, type `bug`. | Functionally ready for investigation, but has an explicit workflow gate: two independent read-only reviews, synthesis, and Jack approval before modifying the shared Agentic OS project. No Bead dependencies listed. | Strong. Criteria cover user-visible fix, actual launch environment, restricted-PATH regression test, actionable secret-safe errors, existing tests/build, and completion receipt. | Sufficient to begin gated planning and reproduction. Evidence identifies screenshot path, target repo, installed CLI path, CLI version, reproduction steps, and expected discovery strategy. | Approval/review gate before changes; root cause still unverified in the app/server launch context. | Run the two read-only reviews, synthesize the repair plan, get Jack approval, then implement test-first against restricted-PATH Claude discovery. |
| `hermes-9ad` | Epic: fleet orchestration architecture wiring from Beads to Sol, Fable 5, Ringer, and Paperclip. | `open`, P1, type `epic`; detail shows 1/7 children complete. | Ready for child-level execution and coordination, not as a single directly executable task. No parent dependencies listed, but active work should route through child Beads. | Weak at parent level. The epic has a clear architecture target and resolved decisions, but no explicit parent acceptance criteria in the staged evidence. Child Beads likely carry executable criteria. | Sufficient to validate identity and planning direction. Not sufficient to implement the epic directly without reading the design doc, branch, and child Bead details. | Parent scope is broad; Phase A is in progress, Phase B/C are open P1, and the parent lacks explicit done criteria. | Inspect and execute the next P1 child Bead, starting with schema/contracts status in `hermes-9ad.1`, and add or confirm parent-level acceptance criteria for final epic closure. |
| `hermes-bcg` | Task: gate active-window qwen preload after one day telemetry. | `open`, P2, type `task`. | Blocked / conditional, not immediately executable. `ready.json` lists one dependency on `hermes-csy`; the detail view marks `hermes-csy` complete, but the Bead itself still requires telemetry evidence: one full day of safe samples and an explicit execute-sample phase showing cold-start benefit without eviction churn. | Poor to moderate. The criteria name the blocked telemetry condition, activation criteria, and rollback, but are too compressed to prove readiness or define exact thresholds from the staged evidence alone. | Sufficient to prove the gate and operational cautions exist. Insufficient to enable preload, because no telemetry log analysis or execute-sample results are included. | Telemetry gate not satisfied in the staged evidence; comments also flag server ownership/env uncertainty and possible embedding traffic on the inference lane. | Keep active-window preload disabled. Analyze `/Users/hermes/.hermes/logs/qwen-prewarm-telemetry.jsonl` after a full day, run the explicit execute-sample phase, resolve lane/embedding concerns, then decide whether activation criteria are met. |

## Individual Findings

### `hermes-wvl`

The staged evidence consistently identifies `hermes-wvl` as the Command Centre Claude CLI PATH bug. `ready.json` and `hermes-wvl.txt` agree on ID, title, type, status, and priority. The problem is concrete: the Skills chat reports `Claude CLI not found`, while Claude Code is known to exist at `/Users/hermes/.hermes/node/bin/claude` with version `2.1.195`.

The Bead is high quality for a P1 bug. It includes a reproduction path, target repo, design direction, evidence path, and acceptance criteria that require a real restricted-PATH regression test. The main caution is procedural: the workflow gate explicitly requires two read-only reviews, synthesis, and Jack approval before modification. Treat it as ready for gated investigation, not ready for immediate edit-without-approval execution.

Recommended next action: perform the two read-only reviews and produce the approval-boundary plan. After approval, implement the executable-discovery fix test-first.

### `hermes-9ad`

The staged evidence consistently identifies `hermes-9ad` as a P1 epic for the Sol / Fable 5 / Ringer / Paperclip orchestration architecture. The detail file confirms it is an epic and lists seven children, with one complete and one in progress.

The parent Bead is valid as a coordination container, but it is not a good immediate execution unit. It has clear architectural decisions and child decomposition, but the staged evidence does not include explicit parent acceptance criteria. Work should proceed through the child Beads, especially P1 children, rather than treating the parent as a single ready implementation task.

Recommended next action: inspect `hermes-9ad.1` and the referenced design doc/branch, confirm contract/schema acceptance criteria, and execute the next child Bead rather than the parent epic directly.

### `hermes-bcg`

The staged evidence identifies `hermes-bcg` as a P2 task for gating active-window qwen preload. It is open and has an explicit dependency record. `ready.json` lists a dependency on `hermes-csy`; `hermes-bcg.txt` shows `hermes-csy` with a completed marker. That means the dependency should be verified carefully, but even if that dependency is resolved, `hermes-bcg` remains conditional because the activation gate itself requires telemetry proof not included in the staged evidence.

This Bead must not be represented as immediately executable. The notes and comment say active-window preload remains disabled, the telemetry sampler runs every 1200 seconds, and activation requires a full day of safe dry-run samples plus an explicit execute-sample phase proving reduced cold starts without eviction churn. The staged evidence does not include the telemetry JSONL analysis, execute-sample output, or proof that server ownership/env and embedding-lane concerns are resolved.

Recommended next action: keep the preload disabled, collect and analyze the telemetry log after a full day, run the explicit execute-sample phase, and only then decide whether the activation criteria are satisfied.

## Overall Conclusion

`hermes-wvl` is the strongest immediate candidate for gated P1 bug work once the review/approval condition is satisfied. `hermes-9ad` is a valid P1 epic but should be routed through its child Beads, not executed directly from the parent. `hermes-bcg` should be treated as blocked/conditional despite appearing in `ready.json`; the staged evidence does not prove the telemetry activation gate is satisfied, so enabling qwen preload now would be premature.
