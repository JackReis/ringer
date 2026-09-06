# Ankit-fork examples (sanitized)

These files are representative samples copied from the Ankit fork's personal
work directories. They illustrate patterns and approaches, not operational
constants. Every installation-specific value has been replaced with a
placeholder and tagged with `# ai2do` so you can adapt them to your actual setup.

## Placeholder conventions

| Placeholder | Meaning |
|---|---|
| `<RINGER_REPO_PATH>` | Absolute path to your local Ringer clone |
| `<TARGET_REPO_PATH>` | Absolute path to the repo a manifest is allowed to edit |
| `<PRACTICEOS_SNAPSHOT_PATH>` | Path to your PracticeOS snapshot input |
| `<SEND_QUEUE_OUT_DIR>` | Directory where the sales-ops send queue should be written |
| `<OPERATOR_NAME>` | Human-readable owner of the policy/operator |
| `<PIPELINE_ID>` | Your HubSpot pipeline ID |
| `<EMAIL>` | Redacted email address |
| `<PHONE_NUMBER>` | Redacted phone number |

## Files

- `local-probes/` — how to prove a worker lane is configured and functional.
- `local-sales-ops/` — a Level-1 sales-ops operator kit with an approval-pilot
  policy.
- `my-manifests/` — manifest organization and a simple OpenCode/OpenRouter probe.
- `work/` — a checked cross-harness skill-implant workflow manifest and review
  checker.

## Before using

Replace every `# ai2do` placeholder with a real value for your machine, then
`ringer.py lint` the manifest before running it.
