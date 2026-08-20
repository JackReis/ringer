---
workstream: [ringer-ringside-harnessie]
tagged_by: worker-hermes-20260814
---

# Agentic OS Project Guidance: gemini-31-ringer-integration

This is a reversible, non-destructive scaffold for the Agentic OS hierarchy.

## Operating Rules

- Do not move, rename, delete, or rewrite existing project content as part of scaffold maintenance.
- Keep project context in `context/` and project-local reusable instructions in `skills/`.
- Keep secrets out of this project. The project only declares configuration expectations in `.agentic-os/preflight.env.example`.
- Launch Hermes through the canonical root flow rather than from a project-local environment.
- Preserve routing, budget, isolated-workspace, approval, and secret-handling safeguards.
- Shape prompts and plans before dispatch; use Kimi K3 for light work and DeepSeek V4 Flash only when the heavier route is justified.

## Canonical Hermes Flow

- Canonical launcher reference: `/Users/hermes/Projects/agentic-os/scripts/smoke-hermes-paperclip.cjs`
- Hermes executable reference: `/Users/hermes/.local/bin/hermes-agent`
- The launcher resolves `HERMES_HOME`, `HERMES_CONFIG_PATH`, model/provider settings, and safe environment bindings from the root environment.
- Run `.agentic-os/preflight.sh` from this project before dispatch. It exits non-zero with a clear message when the root environment is unavailable.

## Local Layout

- `context/`: durable project context, decisions, and references; keep placeholders until content is intentionally migrated.
- `skills/`: project-specific skill entry points; do not duplicate global skills without a deliberate ownership decision.
- `.agentic-os/`: scaffold metadata and validation only.
- This file is the project-level Agentic OS guidance entry point.

## Migration Status

- Existing content has not been migrated or reorganized.
- This scaffold is safe to remove as a unit after the hierarchy pilot or to replace with a fuller project contract.
