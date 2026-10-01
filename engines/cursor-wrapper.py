#!/usr/bin/env python3
"""Strict Ringer-to-Cursor CLI bridge; never interprets a shell command."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('local', 'cloud'))
    parser.add_argument('taskdir')
    parser.add_argument('-m', '--model', required=True)
    parser.add_argument('--request', required=True)
    parser.add_argument('spec')
    args = parser.parse_args()
    if not args.model.strip() or 'openrouter/' in args.model.lower():
        parser.error('an explicit Cursor model ID is required; OpenRouter routes are unsupported')
    state_value = os.environ.get('RINGER_CURSOR_STATE_DIR')
    if not state_value:
        parser.error('RINGER_CURSOR_STATE_DIR must name durable state outside the task directory')
    taskdir = Path(args.taskdir).resolve()
    state = Path(state_value).expanduser().resolve()
    if state == taskdir or taskdir in state.parents:
        parser.error('Cursor state must be outside the task directory')
    command = [os.environ.get('CURSOR_EXECUTION_ADAPTER_BIN', 'cursor-execution-adapter'),
               'run', '--mode', args.mode, '--task-dir', str(taskdir),
               '--model', args.model, '--spec', args.spec, '--state-dir', str(state)]
    timeout = int(os.environ.get('RINGER_CURSOR_TIMEOUT_SECONDS', '840'))
    command.extend(['--timeout-seconds', str(timeout)])
    if args.request:
        command.extend(['--request', str(Path(args.request).expanduser().resolve())])
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
