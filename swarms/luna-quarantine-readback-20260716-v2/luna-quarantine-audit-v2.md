# Luna Quarantine Audit v2

## Snapshot Provenance

- Source: Paperclip live API on Aegis; sanitized fields only.
- Captured at UTC: 2026-07-16T21:34:57.934063+00:00.
- Predecessor failed run: luna-quarantine-readback-20260716-20260716T213002Z-p28304.
- Audit scope: read-only governance evaluation of captured snapshot fields only.
- Task PASS, if granted, is evidence production only. It is never implementation authorization, never policy/auth authorization, and never permission to mutate Paperclip, Beads, git, services, credentials, OAuth state, Herdr, listeners, or host configuration.

## Predecessor Failure

The predecessor failure is preserved as captured, without relabeling:

- Failure: manifest check encoded a pre-capture JAC-3622=todo assumption, while captured state correctly had JAC-3622=blocked.
- Correct captured JAC-3622 state: status=blocked, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:28:27.682Z.

This means the predecessor failed because its manifest assumption was stale relative to the captured state. The captured state itself records JAC-3622 as blocked, not todo.

## Invariant Matrix

| Invariant | Captured Evidence | Result |
|---|---|---|
| Luna High Planner adapterConfig.provider must equal copilot | agent=Luna High Planner, adapterType=hermes_local, status=error, adapterConfig.provider=copilot, updatedAt=2026-07-16T21:20:57.263Z | PASS |
| Luna High Planner adapterConfig.model must equal gpt-5.6-luna | agent=Luna High Planner, adapterConfig.model=gpt-5.6-luna, adapterConfig.effort=high, adapterConfig.modelReasoningEffort=high, timeoutSec=900 | PASS |
| JAC-3592 must be blocked, unassigned, executionRunId=null | status=blocked, assigneeAgentId=null, executionRunId=null, updatedAt=2026-07-16T21:17:46.818Z | PASS |
| JAC-3593 must be blocked, unassigned, executionRunId=null | status=blocked, assigneeAgentId=null, executionRunId=null, updatedAt=2026-07-16T21:17:47.540Z | PASS |
| JAC-3594 must be blocked, unassigned, executionRunId=null | status=blocked, assigneeAgentId=null, executionRunId=null, updatedAt=2026-07-16T21:17:48.160Z | PASS |
| JAC-3595 must be blocked, unassigned, executionRunId=null | status=blocked, assigneeAgentId=null, executionRunId=null, updatedAt=2026-07-16T21:17:48.541Z | PASS |
| JAC-3622 must be blocked/done/cancelled with executionRunId=null | status=blocked, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:28:27.682Z | PASS |
| JAC-3608 must be blocked/done/cancelled with executionRunId=null | status=blocked, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:28:28.520Z | PASS |
| JAC-3617 must be blocked/done/cancelled with executionRunId=null | status=blocked, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:28:29.390Z | PASS |
| JAC-3603 must be blocked/done/cancelled with executionRunId=null | status=blocked, assigneeAgentId=f83be6e5-ccc8-4689-a4a8-ec1dcef9b667, executionRunId=null, updatedAt=2026-07-16T21:29:51.400Z | PASS |
| JAC-3626 must be done with executionRunId=null | status=done, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:32:18.382Z | PASS |

No evaluated quarantine invariant failed. Therefore UNSAFE is not required by the invariant matrix.

## Stale Lane Analysis

The captured stale or legacy quarantine lanes are blocked or done with no active execution run:

- JAC-3592: blocked, unassigned, executionRunId=null, updatedAt=2026-07-16T21:17:46.818Z.
- JAC-3593: blocked, unassigned, executionRunId=null, updatedAt=2026-07-16T21:17:47.540Z.
- JAC-3594: blocked, unassigned, executionRunId=null, updatedAt=2026-07-16T21:17:48.160Z.
- JAC-3595: blocked, unassigned, executionRunId=null, updatedAt=2026-07-16T21:17:48.541Z.
- JAC-3622: blocked, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:28:27.682Z.
- JAC-3608: blocked, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:28:28.520Z.
- JAC-3617: blocked, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:28:29.390Z.
- JAC-3603: blocked, assigneeAgentId=f83be6e5-ccc8-4689-a4a8-ec1dcef9b667, executionRunId=null, updatedAt=2026-07-16T21:29:51.400Z.
- JAC-3626: done, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:32:18.382Z.

These fields support quarantine containment for the stale lanes. They do not authorize implementation because containment evidence is not an execution approval.

## Active Run Analysis

The snapshot captures an active policy/auth gate:

- JAC-3609: status=in_progress, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=09c85b42-8619-4dbb-a3aa-c11996e061c3, updatedAt=2026-07-16T21:34:06.517Z.
- JAC-3609 title: Restore Luna Copilot identity entitlement without model-policy drift.
- JAC-3626: status=done, assigneeAgentId=80284e06-41ab-415a-ba1c-6c3121debd0d, executionRunId=null, updatedAt=2026-07-16T21:32:18.382Z.

Because JAC-3609 is in_progress and has a non-null executionRunId, the required verdict is SAFE_HOLD. This is independent of the stale-lane quarantine matrix passing.

## Fail-Closed Decision

Verdict: SAFE_HOLD.

Reason: JAC-3609 is captured as status=in_progress with executionRunId=09c85b42-8619-4dbb-a3aa-c11996e061c3. Under the audit rule, if JAC-3609 or JAC-3626 is in_progress or has a non-null executionRunId, verdict must be SAFE_HOLD because an authorized policy/auth gate is still active.

The quarantine-only invariants pass, and no invariant requires UNSAFE. However, TERMINAL_PASS is not available while JAC-3609 remains active. Any task PASS here is evidence production only and does not authorize implementation.

## Exact Next Gate

The next gate is a fresh read-only snapshot after the authorized policy/auth lane is no longer active. The required captured state for considering TERMINAL_PASS for quarantine only is:

- JAC-3609 is not in_progress.
- JAC-3609 executionRunId=null.
- JAC-3626 remains not in_progress.
- JAC-3626 executionRunId=null.
- Luna High Planner adapterConfig.provider remains copilot.
- Luna High Planner adapterConfig.model remains gpt-5.6-luna.
- JAC-3592, JAC-3593, JAC-3594, and JAC-3595 remain blocked, unassigned, and executionRunId=null.
- JAC-3622, JAC-3608, JAC-3617, and JAC-3603 remain blocked/done/cancelled with executionRunId=null.
- JAC-3626 remains done with executionRunId=null.

READ_ONLY
