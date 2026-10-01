"""Cursor routing and bridge tests; no credentials or paid execution."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ringer_cursor_test', ROOT / 'ringer.py')
ringer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ringer
spec.loader.exec_module(ringer)


class CursorTests(unittest.TestCase):
    def config(self, mode='local', binary=None):
        name = f'cursor-{mode}'
        engine = ringer.EngineConfig(name=name, bin=binary or str(ROOT / 'engines' / f'{name}.sh'),
            args_template=('{taskdir}', '-m', '{model}', '{engine_args}', '--', '{spec}'),
            sandbox_args=(), full_access_args=(), token_regex=None, auth_routing_trusted=True)
        return SimpleNamespace(engines={name: engine})

    def manifest(self, model, mode='local', full_access=False):
        task = ringer.TaskSpec(key='pilot', spec='fixture', check='true',
                              model=model, engine=f'cursor-{mode}', full_access=full_access)
        return ringer.Manifest(run_name='pilot', workdir=Path('/tmp/pilot'),
                               max_parallel=1, worktrees=False, repo=None, tasks=(task,))

    def test_cursor_routes_protected_families(self):
        for mode in ('local', 'cloud'):
            for model in ('gpt-5.6', 'claude-sonnet-4', 'gemini-3-pro', 'kimi-k2', 'glm-5'):
                with self.subTest(mode=mode, model=model):
                    ringer.validate_manifest_engines(self.manifest(model, mode), self.config(mode))

    def test_openrouter_restriction_preserved(self):
        with self.assertRaisesRegex(ValueError, 'pi-openrouter-ringer.sh'):
            ringer.validate_manifest_engines(self.manifest('openrouter/openai/gpt-5'), self.config())

    def test_wrapper_identity_and_full_access_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'trusted wrapper'):
            ringer.validate_manifest_engines(self.manifest('gpt-5'), self.config(binary='/tmp/cursor-local.sh'))
        with self.assertRaisesRegex(ValueError, 'full_access'):
            ringer.validate_manifest_engines(self.manifest('gpt-5', full_access=True), self.config())

    def test_unregistered_model_retains_cursor_harness(self):
        identity = ringer.load_model_identity_registry().resolve('cursor-cloud', 'unknown-model')
        self.assertEqual(identity.harness, 'Cursor SDK cloud')
        self.assertTrue(identity.unregistered)

    def test_failed_worker_is_not_retried_and_receives_durable_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / 'adapter'
            fake.write_text('#!/usr/bin/env python3\nimport os,json,pathlib,sys\np=pathlib.Path(os.environ["RINGER_CURSOR_STATE_DIR"])\np.mkdir(parents=True,exist_ok=True)\nwith (p/"calls.jsonl").open("a") as f: f.write(json.dumps({k:v for k,v in os.environ.items() if k.startswith("RINGER_")})+"\\n")\nsys.exit(1)\n')
            fake.chmod(0o755)
            config = root / 'config.toml'
            config.write_text(f"""state_dir = {json.dumps(str(root / 'state'))}
[eval]
backend = "jsonl"
jsonl_path = {json.dumps(str(root / 'eval.jsonl'))}
[engines.cursor-local]
bin = {json.dumps(str(ROOT / 'engines/cursor-local.sh'))}
args_template = ["{{taskdir}}", "-m", "{{model}}", "--request", "request.json", "--", "{{spec}}"]
auth_routing_trusted = true
""")
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(dict(run_name='cursor-fixture', workdir=str(root / 'work'),
                max_parallel=1, tasks=[dict(key='fixture', engine='cursor-local', model='fixture-model',
                spec='test', check='true', expect_files=['report.json'])])))
            env = dict(os.environ, CURSOR_EXECUTION_ADAPTER_BIN=str(fake),
                RINGER_NO_SELF_UPDATE='1', RINGER_MULTICA_RECEIPT='0')
            result = subprocess.run([sys.executable, str(ROOT / 'ringer.py'), '--config', str(config),
                'run', str(manifest), '--no-dashboard'], env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            logs = list((root / 'state' / 'cursor').glob('*/fixture/calls.jsonl'))
            self.assertEqual(len(logs), 1, result.stdout + result.stderr)
            calls = logs[0].read_text().splitlines()
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(calls[0])['RINGER_ATTEMPT'], '1')

    def test_bridge_forwarding_and_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = root / 'task'; task.mkdir()
            fake = root / 'adapter'
            fake.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o755)
            env = dict(os.environ, CURSOR_EXECUTION_ADAPTER_BIN=str(fake),
                       RINGER_CURSOR_STATE_DIR=str(root / 'state'))
            command = [str(ROOT / 'engines/cursor-local.sh'), str(task), '-m', 'example', '--request', 'request.json', '--', 'a prompt; $(never execute)']
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = json.loads(result.stdout)
            self.assertEqual(args[args.index('--spec') + 1], 'a prompt; $(never execute)')
            self.assertEqual(args[:3], ['run', '--mode', 'local'])
            env['RINGER_CURSOR_STATE_DIR'] = str(task / 'state')
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('outside', result.stderr)
            env['RINGER_CURSOR_STATE_DIR'] = str(root / 'state')
            command[0] = str(ROOT / 'engines/cursor-cloud.sh')
            del command[4:6]
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--request', result.stderr)


if __name__ == '__main__':
    unittest.main()
