# Run receipts: `which_host`

Every new Ringer run snapshot (`<state_dir>/runs/<run_id>.json`, default `~/.ringer/runs/<run_id>.json`) carries `which_host`. The field is fail-closed. Multica cannot mark a card done, and Kata cannot close, on a receipt that does not name one of the three hosts below.

`which_host` is not the orchestrator identity and not the machine hostname. Identity answers who ran the swarm. `which_host` answers which machine class the receipt belongs to. Ringer does not infer it from `socket.gethostname()`, from a notes directory, or from an alias.

## Locked enum

| Value | Meaning |
|---|---|
| `talaris` | Vault SSOT host (`/Users/jack.reis/Documents/=notes`) |
| `aegis` | Runtime / mirror host (`/Users/hermes/=notes`, `~/.hermes`) |
| `box` | Grok Bot / agent Scratch computer. Scratch stays Scratch. It is never a vault and never a host fork of talaris or aegis. |

Any other value is rejected: missing, empty, whitespace, a different capitalisation, an alias (`scratch`, `vault`, `hermes`, `grok`), or a hostname string.

## How a run gets the pin

First source that is explicitly set wins. An invalid value does not fall through to the next source.

1. `--which-host` on `run`, `ask`, and `demo`
2. `RINGER_WHICH_HOST`
3. `which_host` in config (`~/.config/ringer/config.toml`)

If none of those is set, `run` / `ask` / `demo` exit 2 and do not write a receipt. `ask --dry-run` and `run --dry-run` check the pin before they report a plan. `run --baseline` checks it too, even though baseline writes no worker receipt.

```bash
./ringer.py run manifest.json --which-host aegis
./ringer.py ask "where is the pin documented?" --source docs/RECEIPTS.md --which-host box
```

## Multica stamp bar

Before a Multica card is marked done, the comment includes the Ringer pointer and the host. Optional prover tip is a single token (a commit SHA is the usual tip). Shape, from `format_multica_stamp`:

```text
runs/<run_id> which_host=<aegis|talaris|box> lane=<registered-machine-shell|scratch> prover=<tip>
```

`prover=` is omitted when there is no tip.

Shell lanes:

- Host-craft receipts (`aegis`, `talaris`) cite `lane=registered-machine-shell`. That is the registered-machine Shell lane.
- `box` cites `lane=scratch`. Scratch stays scratch in the stamp. Do not rewrite a box receipt as talaris or aegis, and do not cite it as registered-machine Shell.

Example comments:

```text
runs/helix-trust-20260928T000000Z-p123 which_host=aegis lane=registered-machine-shell prover=abc123
runs/scratch-note-20260928T000000Z-p456 which_host=box lane=scratch
```

The pointer `runs/<run_id>` is the snapshot file under the state dir. The id is the `run_id` field in that JSON.

## Caller pin (prover / typed-verify)

This note is documentation only. Ringer does not call the prover.

If prover or typed-verify runs inference, that inference is Aegis fleet only. A Scratch (`box`) receipt stays Scratch: do not retarget it at Aegis or Talaris. Typed-verify orphan handling and Proof CI bans are out of scope.

## Historical snapshots

Receipts written before this field existed may omit `which_host`. Policy:

- **New writes** must include a valid value. `StateWriter` refuses to flush a snapshot without one, and refuses a value outside the enum before it creates the file.
- **Grandfather** missing fields on old files. Do not guess a host from the hostname or the path and rewrite them.
- **Invalid values are never grandfathered**, including on old files.

`./ringer.py check-receipts` scans `<state_dir>/runs/*.json`:

- missing `which_host` → `WARN`, exit 0
- missing `which_host` with `--strict` → `ERROR`, exit 1 (the new-write gate)
- any other value → `ERROR`, exit 1, with or without `--strict`

The command only prints findings. It does not migrate files.

## Fail-closed check

A bad pin exits 2 and leaves no new file under `runs/`:

```bash
./ringer.py run manifest.json --which-host hostname
```

Expect stderr to contain `which_host must be exactly one of: aegis, talaris, box` and `got 'hostname'`. Confirm `~/.ringer/runs/` gained no snapshot for that attempt.
