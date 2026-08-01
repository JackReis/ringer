# Paperclip-first fleet coordination contract (Phase 0/1)

> Ringer receipt for **JAC-3787** · Parent: JAC-3643 (done)  
> Status: coordination anchor · Non-authoritative · Phase 0/1 only

This document records the Phase 0/1 coordination contract agreed in JAC-3787. It is a durable, human-readable workspace receipt. It does **not** modify Beads records, goal mappings, Family Bulletin data, agent settings, or lifecycle authority.

## Surface roles

| Surface | Role in Phase 0/1 |
|---|---|
| **Paperclip** | Primary active coordination surface for assignments, decisions, blockers, run links, and work-product references. |
| **Beads** | Authoritative resolver for lifecycle and work state when surfaces disagree. |
| **Vault** | Preserved, append-only human-readable mirror and history; existing artifacts remain in place. |
| **Ringer** | Execution evidence and check-gate layer; receipts link back to JAC-3787 when available. |

## Single-owner dual-surface approach

- Publish active coordination in Paperclip.
- Mirror summaries and references into the Vault, but do **not** enable unrestricted status dual-write.
- Any automation is read-only / projection-first, idempotent, and reconciliation-gated.
- Configuration changes remain approval-gated.

## Existing references

The following Vault artifacts inform the broader coordination migration. They are referenced by path only; their contents are authoritative in their respective domains:

- `/Users/jack.reis/Vault/coordination/coordination-migration-plan/output/reports/coordination-migration-plan/coordination-inventory-and-migration-plan.md`
- `/Users/jack.reis/Vault/coordination/coordination-migration-plan/output/reports/coordination-migration-plan/source-notes.md`
- `/Users/jack.reis/Vault/coordination/plan-runner-run-analysis/output/reports/plan-runner-f394729e/plan-runner-optimization-report.md`
- `/Users/jack.reis/Vault/coordination/open-fleet-coordination/open-fleet-execution-method.md`
- Related triage declaration: `Fleet Goal Vault Beads and Paperclip Triage` (reviewed 2026-07-23). Its authoritative next steps remain approval-gated: restore the Aegis Beads baseline, correct 49 Paperclip goal mappings, and reconcile Family Bulletin.

## Run-efficiency guardrails

1. Trim startup context to the minimum evidence required for the assignment.
2. Prefer references and scoped extracts over full transcripts or broad memory dumps.
3. Run a preflight before dispatch covering: authority boundary, target IDs, host reachability, credentials, duplicate check, write scope, stop conditions, and expected verification.
4. Stop before any Beads write, goal-mapping correction, Family Bulletin change, or authority/configuration change.

## Approval-gated follow-ups

The items below require explicit approval before proceeding. They are **not** in scope for Phase 0/1.

1. Approve the stable project/issue routing convention for future coordination.
2. Approve a read-only projection/mirroring pilot and reconciliation report.
3. Approve any dual-write configuration only after the pilot proves idempotence and rollback.
4. Separately approve Beads baseline restoration, the 49 goal-mapping corrections, and Family Bulletin reconciliation.

## Receipt

- **Issue:** JAC-3787
- **Agent ID:** 3f1712eb-7b43-40fa-b893-f36e92bb9ac3
- **Company ID:** 87c32b8e-f131-4df8-ad8e-963d01b458e7
- **Run IDs:**
  - Created by: `c4ac167a-a830-4031-87b3-439b89b661dd`
  - Verified/refreshed by: `fd804488-6caa-4d90-bf90-b118ed2c02f9`
- **Workspace:** `/Users/hermes/Projects/wt-ringer-byom-ideal-20260715`
- **Action taken:** Created and verified this non-authoritative coordination receipt; no Beads, Vault, Bulletin, mapping, or configuration writes performed.
