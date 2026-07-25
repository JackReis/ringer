# Verdict

REVISE — independent verify.py failed before proving live Talaris evidence

Fresh mandatory command result:

```text
$ python3 /Users/hermes/ringer/jobs/degraded-ledger-resolution/verify.py
Traceback (most recent call last):
  File "/Users/hermes/ringer/jobs/degraded-ledger-resolution/verify.py", line 91, in <module>
    main()
  File "/Users/hermes/ringer/jobs/degraded-ledger-resolution/verify.py", line 39, in main
    remote_hash_output = run([
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "talaris",
        "shasum", "-a", "256", REMOTE_VERIFIER,
    ])
  File "/Users/hermes/ringer/jobs/degraded-ledger-resolution/verify.py", line 25, in run
    raise AssertionError(...)
AssertionError: command failed (255): ssh -o BatchMode=yes -o ConnectTimeout=10 talaris shasum -a 256 /Users/jack.reis/tracking/archive/legacy-commit-log-20260714T001444Z/verify_resolution.py
stdout:

stderr:
ssh: connect to host 100.97.178.76 port 22: Operation not permitted
```

Fresh package checksum result:

```text
$ cd /Users/hermes/ringer/jobs/degraded-ledger-resolution && shasum -a 256 -c SHA256SUMS
manifest.json: OK
archive-manifest.json: OK
talaris-verifier.py: OK
verify.py: OK
bifrost-receipt.json: OK
pre-repair-red.md: OK
```

# Correlation

The immutable package at `/Users/hermes/ringer/jobs/degraded-ledger-resolution` is internally checksum-consistent. `SHA256SUMS` validates:

- `manifest.json` = `10b6a3e8f5da1cac10e97583067c0075570b5f5540496b13923610d5e1ae7d42`
- `archive-manifest.json` = `9a985c5ec4e834ea29a01bda3f3cd729ad24e1ad573253505f4fcfbbd52b6374`
- `talaris-verifier.py` = `9350660a5f5054d4f185bd889d420ed398fdfd3bd6b1caee54cc02022890179e`
- `verify.py` = `04456a564fe1a6a57d47093e7e7dee896106b4b6bddd4fc4a0c526ee8ed23368`
- `bifrost-receipt.json` = `049780972e9610f6d09dba0566d76514183572608caaa0b538a5db3ebffd7f1c`
- `pre-repair-red.md` = `9c1733b34e72ac347c71eee30eff07b01fab5751df1606ef6fe507bfc56d3e3a`

Static package metadata cross-links Bead `notes-4bwsk`, Paperclip parent `JAC-3383`, typist `JAC-3384`, judge `JAC-3385`, candidate commit `ed159a393b8594587bfce53d59b5a47303498294`, and Bifrost success log `cd0389e9-1fba-4919-805f-a296730ad249`.

# Canonical usage ledger

Not independently proven live in this judge run.

Static package evidence claims canonical machine AI usage accounting remains the sole directory `/Users/jack.reis/.hermes/ledger`, with `overall_status=ok`, `ledger_status=ok`, `ledger_rows=3045`, `ledger_missing_sources=none`, and one writer job `6c168fc9f871` enabled, scheduled, and `last_status=ok`.

The required verifier did not reach the Talaris-side checks in `/Users/jack.reis/tracking/archive/legacy-commit-log-20260714T001444Z/verify_resolution.py`, so the live directory enumeration, health script output, and writer-job assertion were not independently proven by this judge run.

# Legacy projection

Not independently proven live in this judge run.

Static package evidence claims active projection `/Users/jack.reis/tracking/commit-log.md` has SHA-256 `dec964d98330c56c4d44865d53b6a9c478a5214066525eb2b8e0758102a29db9`, is explicitly marked `Status: retired historical compatibility projection`, preserves `1347` section identities and `1352` commit-field rows, keeps multi-commit manual sections, and has `0` excess duplicate sections.

The mandatory verifier failed before computing the live active projection hash or section metrics on Talaris.

# Writer retirement

Not independently proven live in this judge run.

Static package evidence claims retired legacy writer job `62f9a439503b` / `hermes-ledger` is removed, disabled, has no replacement job, and executable consumer matches are `0`.

The mandatory verifier failed before reading `/Users/jack.reis/.hermes/cron/jobs.json` and before scanning the executable consumer roots on Talaris, so absence of the obsolete writer and consumers is not independently proven here.

# Idempotency code and tests

Not independently proven live in this judge run.

Static package evidence claims branch `fix/ledger-idempotency-parent` has pushed candidate commit `ed159a393b8594587bfce53d59b5a47303498294`, base commit `0f89282dab7039027afdd1f69c68b53b05977322`, installed source hash `/Users/jack.reis/Documents/=notes/claude/scripts/ledger.py` = `0efefe2f9012b030fa569a00afbf8c1b1dd929bd055064ef7a9815d7277fdf4c`, installed test hash `/Users/jack.reis/Documents/=notes/claude/scripts/test_ledger.py` = `5edc5b7739531a7d7158a230edefee4bfd2ae4f580fbfd72021e36c77868ae92`, focused tests `4 passed`, full suite `76 passed`, and isolated repeated append output `new=7 skipped=13 total=20` followed by `new=0 skipped=20 total=20` with no duplicate growth.

The mandatory verifier failed before running the live-path pytest command, `git rev-parse HEAD`, `git ls-remote git@gitlab.com:jackrei/neural-garden-v2.git refs/heads/fix/ledger-idempotency-parent`, installed source hash checks, or isolated idempotency smoke.

# Beads/Paperclip

Not independently proven live in this judge run.

Static package evidence cross-links Bead `notes-4bwsk`, Paperclip `JAC-3383`, `JAC-3384`, `JAC-3385`, raw rollback hash `240e3143520994c7299d20cdcce7358982b8d6c23e1910056eaec143c73876df`, code hashes `0efefe2f9012b030fa569a00afbf8c1b1dd929bd055064ef7a9815d7277fdf4c` and `5edc5b7739531a7d7158a230edefee4bfd2ae4f580fbfd72021e36c77868ae92`, candidate commit `ed159a393b8594587bfce53d59b5a47303498294`, and Bifrost success log `cd0389e9-1fba-4919-805f-a296730ad249`.

The mandatory verifier failed before reaching its Paperclip API checks at `http://127.0.0.1:3110/api/issues/...` and before executing `bd show notes-4bwsk --json` with `BEADS_DIR=/Users/jack.reis/Documents/=notes/.beads`.

# Bifrost

Not independently proven live through the mandatory verifier in this judge run.

Checksum-proven static `bifrost-receipt.json` records deployment `degraded-ledger-resolution-20260714`, OpenAI attempt `e650aebf-ec0b-43b7-8ae5-7b6fad7d2dc3` with `status=error`, `http_status=429`, `error_type=insufficient_quota`, and later Mistral success `cd0389e9-1fba-4919-805f-a296730ad249`, provider `mistral`, model `mistral-small-latest`, response `8d4dc001f1784b1382b89a92779238e5`, `status=success`, verdict `SOUND`.

The mandatory verifier failed before reaching its Bifrost API assertion against `http://127.0.0.1:8078/api/logs?limit=100`, so the live Bifrost log state is not independently proven here.

# Rollback

Not independently proven live in this judge run.

Static package evidence claims byte-identical raw rollback at `/Users/jack.reis/tracking/archive/legacy-commit-log-20260714T001444Z/commit-log.raw.md` with SHA-256 `240e3143520994c7299d20cdcce7358982b8d6c23e1910056eaec143c73876df`, `872724` bytes, `28475` `wc` lines, mode `0444`, and `byte_identity_check=PASS`.

The package checksum command proves the local package files are intact, but the live raw rollback file was not independently hashed because `verify.py` failed before Talaris-side execution.

# Publication authorization

Publication is not authorized. Main must remain untouched.

The requested PASS gate requires every claim to be proven. Fresh execution of `python3 /Users/hermes/ringer/jobs/degraded-ledger-resolution/verify.py` exited `1` before remote verifier hash validation, remote verifier execution, live Talaris evidence collection, Paperclip/Beads checks, or Bifrost API checks. This receipt therefore cannot authorize pushing `ed159a393b8594587bfce53d59b5a47303498294` to main.

# Caveats

This REVISE is caused by the judge environment blocking SSH to `talaris`, not by a disproven repair claim. The exact blocking evidence is `ssh: connect to host 100.97.178.76 port 22: Operation not permitted`.

The known out-of-scope repo-wide task-queue guard observation about `.show-and-tell/.../queue-hygiene-audit.md` was not treated as evidence against the machine AI usage-ledger uniqueness claim. The machine AI usage-ledger uniqueness claim remains unproven in this judge run solely because the mandatory verifier did not reach its exact directory and writer-job enumeration.
