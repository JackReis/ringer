#!/usr/bin/env python3
"""Ringer engine wrapper: run the Antigravity CLI (`agy`) as an INTERACTIVE
CLI judge, driven through the iTerm2 Python API, on model "Gemini 3.1 Pro (High)".

Why interactive (not `agy --print`): agy's headless `--print` mode drops the
prompt whenever `--model` is supplied (it responds with a model-selection
greeting instead of answering — verified 2026-07-24). The interactive TUI honors
both the model flag and the prompt, and the live iTerm2 session doubles as the
intended "masked" on-screen surface.

Ringer contract (verified against ringer.py):
  * ringer runs this bin with cwd = the task dir, stdin closed (/dev/null),
    stdout+stderr captured to the task's worker.log.
  * Placeholders are substituted by ringer into argv; {spec} always arrives as a
    single argv element (no shell splitting), so we accept it after a `--`.
  * The deliverable is a FILE this wrapper leaves in the task dir; the manifest's
    `check` shell command (run in the task dir) decides pass/fail. We instruct
    agy to write its full report to that file, echo the file to stdout, and also
    save a raw on-screen transcript for evidence.

Completion detection: poll the session's screen every POLL_S seconds. agy shows a
busy indicator ("Generating", "esc to cancel", "Thinking", "Running", ...) while
working. Completion = a busy indicator was observed at least once and is then
absent for IDLE_POLLS consecutive polls (a stable-idle prompt), OR the
deliverable file exists and its size is stable while idle. A hard --timeout
bounds the whole run. Limits: if agy answered faster than the first poll the busy
latch may not trip -- mitigated by the file-stable-while-idle path and a minimum
settle. Busy-token wording is version-dependent; several tokens plus the file
signal make it resilient.

Secrets: none are read or emitted. agy manages its own auth via the OS keyring /
browser sign-in; nothing sensitive is passed on argv or printed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import signal
import sys
import time
from pathlib import Path

POLL_S = 2.0
IDLE_POLLS = 3            # consecutive idle polls after busy => done
FILE_STABLE_POLLS = 5     # stable non-empty deliverable => done
READY_TIMEOUT_S = 90     # wait for the agy TUI banner
READY_TOKENS = ("? for shortcuts", "Antigravity CLI")
TRUST_PROMPT = "Do you trust the contents of this project?"
BUSY_TOKENS = (
    "Generating",
    "esc to cancel",
    "Thinking",
    "Running",
    "Working",
    "Executing",
    "Prioritizing",
)
DEFAULT_MODEL = "Gemini 3.1 Pro (High)"
DEFAULT_DELIVERABLE = "agy-judge-report.md"
TRANSCRIPT_NAME = "agy-iterm2-transcript.txt"


def log(msg: str) -> None:
    print(f"[agy-iterm2-judge] {msg}", file=sys.stderr, flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--taskdir", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--deliverable", default=DEFAULT_DELIVERABLE)
    p.add_argument("--timeout", type=int, default=600)
    # {access_args}/{engine_args} may inject extra tokens; tolerate them.
    p.add_argument("--no-sandbox", action="store_true")
    # Everything after `--` is the spec (a single argv element from ringer).
    p.add_argument("spec", nargs=argparse.REMAINDER)
    ns, unknown = p.parse_known_args(argv)
    if unknown:
        log(f"ignoring unrecognized engine args: {unknown}")
    spec_parts = list(ns.spec)
    while spec_parts and spec_parts[0] == "--":
        spec_parts = spec_parts[1:]
    ns.spec_text = "\n".join(spec_parts).strip() if spec_parts else ""
    return ns


async def screen_text(session) -> str:
    contents = await session.async_get_screen_contents()
    return "\n".join(
        contents.line(i).string for i in range(contents.number_of_lines)
    )


def is_busy(text: str) -> bool:
    return any(tok in text for tok in BUSY_TOKENS)


def run(ns: argparse.Namespace) -> int:
    """Synchronous entry: file setup, then drive agy via the iTerm2 API.

    iterm2.run_until_complete owns its own event loop, so this function must NOT
    run inside another asyncio loop.
    """
    import iterm2

    taskdir = Path(ns.taskdir).resolve()
    if not taskdir.is_dir():
        log(f"taskdir does not exist: {taskdir}")
        return 3
    if not ns.spec_text:
        log("empty spec; nothing to judge")
        return 4

    deliv = taskdir / ns.deliverable
    transcript = taskdir / TRANSCRIPT_NAME
    prompt_file = taskdir / ".agy-task-prompt.md"
    prompt_file.write_text(ns.spec_text, encoding="utf-8")

    # Short typed bootstrap: keep on-screen input tiny and deterministic; the
    # real task text lives in the file agy reads. Forcing a file deliverable
    # keeps harvesting clean regardless of TUI rendering.
    bootstrap = (
        f"Read the file {shlex.quote(prompt_file.name)} in the current working "
        f"directory and carry out the task it describes completely. Write your "
        f"full, final response to the file {shlex.quote(ns.deliverable)} in the "
        f"current working directory using your file tools. Do not ask for "
        f"confirmation; complete the whole task in this turn."
    )

    deadline = time.monotonic() + ns.timeout
    result = {"rc": 1}
    agy_pid: int | None = None

    async def _dump(session) -> None:
        try:
            transcript.write_text(await screen_text(session), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log(f"transcript capture failed: {exc.__class__.__name__}")

    async def main(connection):
        nonlocal agy_pid
        win = await iterm2.Window.async_create(connection)
        session = win.tabs[0].sessions[0]
        try:
            await session.async_send_text(f"cd {shlex.quote(str(taskdir))}\n")
            await asyncio.sleep(1.0)
            await session.async_send_text(
                f"agy --model {shlex.quote(ns.model)} "
                f"--dangerously-skip-permissions\n"
            )

            ready = False
            trust_confirmed = False
            ready_deadline = min(deadline, time.monotonic() + READY_TIMEOUT_S)
            while time.monotonic() < ready_deadline:
                await asyncio.sleep(1.0)
                sc = await screen_text(session)
                if TRUST_PROMPT in sc and not trust_confirmed:
                    log("confirming Antigravity access to the bounded task directory")
                    await session.async_send_text("\r")
                    trust_confirmed = True
                    continue
                if all(token in sc for token in READY_TOKENS):
                    ready = True
                    raw_pid = await session.async_get_variable("jobPid")
                    try:
                        agy_pid = int(raw_pid)
                    except (TypeError, ValueError):
                        agy_pid = None
                    break
            if not ready:
                log("agy TUI did not reach a ready state before timeout")
                await _dump(session)
                result["rc"] = 5
                return
            await asyncio.sleep(2.0)  # let the input settle

            await session.async_send_text(bootstrap + "\n")
            await asyncio.sleep(1.0)
            submitted_screen = await screen_text(session)
            if bootstrap[:40] not in submitted_screen and not is_busy(submitted_screen):
                log("prompt was not accepted on first send; retrying")
                await session.async_send_text(bootstrap + "\n")
                await asyncio.sleep(1.0)
            log("prompt submitted; awaiting completion")

            started = False
            idle = 0
            last_size = -1
            stable = 0
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_S)
                sc = await screen_text(session)
                busy = is_busy(sc)
                if busy:
                    started = True
                    idle = 0
                else:
                    idle += 1
                if deliv.exists():
                    sz = deliv.stat().st_size
                    stable = stable + 1 if sz == last_size else 0
                    last_size = sz
                else:
                    stable = 0
                    last_size = -1
                done_idle = started and idle >= IDLE_POLLS
                done_file = (
                    deliv.exists()
                    and last_size > 0
                    and stable >= FILE_STABLE_POLLS
                )
                if done_idle or done_file:
                    log(
                        f"complete: started={started} idle={idle} "
                        f"file={deliv.exists()} stable={stable}"
                    )
                    result["rc"] = 0
                    break
            else:
                log(f"timed out after {ns.timeout}s")
                await session.async_send_text("\x03")  # ctrl-c: stop the TUI
                await asyncio.sleep(0.5)
                result["rc"] = 6

            await _dump(session)
            for _ in range(2):
                await session.async_send_text("\x03")
                await asyncio.sleep(0.3)
        finally:
            if agy_pid is not None:
                try:
                    os.kill(agy_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                await win.async_close(force=True)
            except Exception as exc:  # noqa: BLE001
                log(f"window close failed (non-fatal): {exc.__class__.__name__}")

    try:
        iterm2.run_until_complete(main, retry=False)
    except Exception as exc:  # noqa: BLE001
        log(f"iTerm2 API failure: {exc.__class__.__name__}: {exc}")
        return 7

    rc = result["rc"]
    if rc != 0:
        log(f"run did not complete cleanly (rc={rc})")
        return rc

    if deliv.exists() and deliv.stat().st_size > 0:
        content = deliv.read_text(encoding="utf-8", errors="replace")
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        log(f"deliverable written: {deliv} ({deliv.stat().st_size} bytes)")
        return 0

    log(f"deliverable missing or empty: {deliv}")
    if transcript.exists():
        log(f"see transcript for on-screen evidence: {transcript}")
    return 8


def main() -> int:
    return run(parse_args(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
