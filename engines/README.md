# Ringer engine wrappers

These shell scripts adapt third-party agent CLIs to Ringer's engine contract:

```text
<bin> <taskdir> <access_args> ... <spec>
```

Ringer spawns the engine as a subprocess, passes the task directory as the first
argument, injects any per-engine environment variables configured in
`[engines.<name>.env]`, and verifies the resulting artifact with the task's
check command.

## Per-engine environment variables

Ringer now supports an `env` table under each engine in `config.toml`:

```toml
[engines.omnigent]
bin = "/absolute/path/to/ringer/engines/omnigent-sandboxed.sh"
args_template = ["{taskdir}", "{access_args}", "-z", "{spec}", "-m", "{model}", "{engine_args}"]

[engines.omnigent.env]
OMNIGENT_SERVER = "http://127.0.0.1:6767"
OMNIGENT_AGENT_ID = "your-agent-id-here"
```

Values in `[engines.<name>.env]` override inherited process environment
variables for that engine's worker subprocess only. Shell-level environment
variables can still be used, which is useful for local overrides and CI secrets.

## Wrappers

### `hermes-sandboxed.sh`

Runs the Hermes agent one-shot under macOS Seatbelt. Supports `--no-sandbox`
as the second argument for full-access runs.

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `HERMES_HOME` | `~/.hermes` | Hermes config/credential tree |
| `HERMES_STATE` | `~/.local/state/hermes` | Hermes state directory |
| `PAPERCLIP_OLLAMA_CLOUD_ADMISSION_BIN` | (none) | Path to `ollama_cloud_admission.py` |
| `PAPERCLIP_OLLAMA_CLOUD_ADMISSION_POLICY` | (none) | Path to `cloud-admission-policy.v1.json` |
| `PAPERCLIP_OLLAMA_CLOUD_ADMISSION_STATE_DIR` | (none) | Admission state directory |

Cloud admission is **only** required when a task pins an `ollama-cloud` route
(model starts with `ollama-cloud:` or `--provider ollama-cloud` is used). If a
cloud route is pinned and the admission variables are not configured or the
binary/state dir is missing, the wrapper exits with code 74 and a clear error.
Non-cloud routes ignore admission entirely.

### `omnigent-sandboxed.sh`

Drives Omnigent's session API headlessly.

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `OMNIGENT_SERVER` | `http://127.0.0.1:6767` | Omnigent session API endpoint |
| `OMNIGENT_AGENT_ID` | (required) | Agent ID used to create sessions |
| `OMNIGENT_DEFAULT_MODEL` | `ollama-cloud/deepseek-v4-pro` | Fallback model when `-m` is not supplied |

If `OMNIGENT_AGENT_ID` is empty, the wrapper exits with code 2.

## Adding a new wrapper

1. Make the script executable (`chmod +x engines/<name>-sandboxed.sh`).
2. Avoid hardcoding installation-specific paths or IDs.
3. Read configuration from `[engines.<name>.env]` via environment variables.
4. Fail closed with a clear error when required configuration is missing.
5. Add an example block to `config.sample.toml`.
6. Document the env vars in this file.

## Cursor local and cloud engines

Install the independently licensed `cursor-execution-adapter` and enable the
`cursor-local` / `cursor-cloud` blocks in `config.sample.toml`. Set
`CURSOR_EXECUTION_ADAPTER_BIN` to an executable path when it is not on PATH.
Credentials belong in the adapter's supported secret environment, never manifests.
These wrappers are explicit trusted Cursor routes for account-visible models;
OpenRouter selectors remain restricted to their existing wrapper. Model IDs are
required and checked by the adapter. Cursor harness metadata does not attest to
an underlying model identity.

For a task, set `engine` to either engine, `model` to an ID returned by Cursor,
`timeout_s` to 900, `expect_files` to the expected relative output paths and
`engine_args` to `["--request", "/absolute/path/to/request.json"]`.
Both modes require this request so expected artifacts are explicit:

```json
{
  "repo": "https://github.com/OWNER/APPROVED-REPO",
  "ref": "REPLACE_WITH_IMMUTABLE_40_HEX_COMMIT",
  "expectFiles": ["report.json"],
  "inputFiles": ["evidence.json"],
  "timeoutSeconds": 840
}
```

Replace the repository/ref before use. Inputs are relative to the task directory
and must be approved, secret-free files. Local requests omit repo/ref. Keep
`expectFiles` aligned with Ringer `expect_files`; Ringer still executes its local
`check` and never treats remote completion as a verification pass. Choose an
adapter timeout below Ringer's timeout to leave time for cleanup. The wrapper
always supplies Ringer's task timeout minus 30 seconds as the adapter deadline;
Cursor task timeouts must exceed 30 seconds.

Ringer supplies `RINGER_CURSOR_STATE_DIR` as
`<state_dir>/cursor/<run_id>/<task_key>`, outside disposable worktrees, plus run,
task, and attempt IDs. Neither engine automatically retries failed model runs.
To resume an interrupted run, use the adapter directly with the original state
directory, task directory, request, model and spec. A new Ringer invocation has a
new run ID and is **not** a recovery command: reconcile ambiguous launches or
unconfirmed cancellation first. Timeout sends SIGTERM and allows 30 seconds for
adapter cancellation before forced termination; inspect the durable receipt after
forced termination. Full-access tasks and arbitrary adapter flags are rejected.

Pilot with one worker, then at most three reviewers. Do not change billing settings
or enable overages. Cloud analysis cannot prove access through another agent's
native runtime. The adapter is independent MIT code; these bridge changes retain
Ringer's existing license. No installed launcher is replaced by this integration.
