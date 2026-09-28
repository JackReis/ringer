#!/usr/bin/env python3
"""The Dune import-graph gate fails closed on the four Ringer edges."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "checks" / "dune_import_ban.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("dune_import_ban", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {CHECKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


HANDLER = """
.invoke_handler(tauri::generate_handler![
    hide_window,
    toggle_collapse,
    resize_main_window,
    read_artifact_library,
    read_artifact_html,
    read_worker_log,
    load_settings,
    save_settings
])
"""

CAPABILITIES = {
    "identifier": "default",
    "permissions": [
        "core:default",
        "core:window:allow-hide",
    ],
}

TAURI_CONF = {
    "app": {
        "security": {
            "assetProtocol": {
                "enable": True,
                "scope": ["$HOME/.ringer/artifacts/**"],
            }
        }
    }
}

UI_SHELL = """<script>
function tauriInvoke(command, args) {
  return TAURI_INVOKE(command, args);
}
</script>
"""


class DuneImportBanTests(unittest.TestCase):
    def test_repo_passes(self) -> None:
        result = CHECKER.scan_root(ROOT)
        rendered = "\n".join(finding.format() for finding in result.findings)
        self.assertEqual(result.findings, [], rendered)
        self.assertGreater(result.files_scanned, 0)
        self.assertEqual(len(result.edges), 4)

    def test_unprivileged_import_of_ringer_fails(self) -> None:
        with self._tree({"templates/banned.py": "import ringer\n"}) as root:
            result = CHECKER.scan_root(root)
        self.assertTrue(result.findings, "banned import must fail closed")
        finding = result.findings[0]
        self.assertEqual(finding.edge, "unprivileged_to_privileged")
        self.assertEqual(finding.path, "templates/banned.py")
        self.assertIn("privileged module 'ringer'", finding.detail)
        self.assertIn("import ringer", finding.format())

    def test_shortcut_ipc_command_fails(self) -> None:
        page = UI_SHELL + "\n<script>tauriInvoke(\"read_secrets\");</script>\n"
        with self._tree({"dashboard/ok.html": page}) as root:
            result = CHECKER.scan_root(root)
        edges = {finding.edge for finding in result.findings}
        self.assertIn("shortcut_ipc_skip", edges, self._render(result))
        self.assertTrue(
            any("read_secrets" in finding.detail for finding in result.findings),
            self._render(result),
        )

    def test_secret_reader_in_ui_fails(self) -> None:
        page = UI_SHELL + "\n<script>parse_env_file(\"/tmp/x\");</script>\n"
        with self._tree({"dashboard/ok.html": page}) as root:
            result = CHECKER.scan_root(root)
        self.assertTrue(
            any(finding.edge == "secret_readers_in_ui" for finding in result.findings),
            self._render(result),
        )

    def test_parallel_board_client_fails(self) -> None:
        with self._tree({"hud/frontend/hud.js": "const socket = new WebSocket(\"ws://127.0.0.1:9\");\n"}) as root:
            result = CHECKER.scan_root(root)
        edges = {finding.edge for finding in result.findings}
        self.assertIn("parallel_board_clients", edges, self._render(result))

    def test_stamp_suppresses_one_line_and_stale_stamp_fails(self) -> None:
        waiver = """
schema = "ringer.dune-import-exceptions/v1"

[[exceptions]]
edge = "unprivileged_to_privileged"
path = "templates/banned.py"
pattern = "import ringer"
stamp = "aegi-178-fixture-waiver"
reason = "Fixture waiver proving one stamped line can pass."
"""
        with self._tree(
            {"templates/banned.py": "import ringer\n"},
            exceptions=waiver,
        ) as root:
            stamped = CHECKER.scan_root(root)
        self.assertEqual(stamped.findings, [], self._render(stamped))

        with self._tree({}, exceptions=waiver) as root:
            stale = CHECKER.scan_root(root)
        self.assertTrue(
            any("stale stamp" in finding.detail for finding in stale.findings),
            self._render(stale),
        )

    def test_missing_edge_fails_closed(self) -> None:
        policy = (ROOT / "checks" / "dune_import_policy.toml").read_text(encoding="utf-8")
        policy = policy.replace("[edges.parallel_board_clients]", "[edges.not_a_dune_edge]")
        with self._tree({}, policy=policy) as root:
            result = CHECKER.scan_root(root)
        edges = {finding.edge for finding in result.findings}
        self.assertIn("parallel_board_clients", edges, self._render(result))
        self.assertTrue(
            any("does not declare this edge" in finding.detail for finding in result.findings),
            self._render(result),
        )

    def test_blank_stamp_fails_closed(self) -> None:
        waiver = """
schema = "ringer.dune-import-exceptions/v1"

[[exceptions]]
edge = "unprivileged_to_privileged"
path = "templates/banned.py"
pattern = "import ringer"
stamp = "short"
reason = "Stamp is too short to be a waiver id."
"""
        with self._tree({"templates/banned.py": "import ringer\n"}, exceptions=waiver) as root:
            result = CHECKER.scan_root(root)
        self.assertTrue(
            any("exception missing" in finding.detail and "stamp" in finding.detail for finding in result.findings),
            self._render(result),
        )
        self.assertTrue(
            any(finding.edge == "unprivileged_to_privileged" and finding.path == "templates/banned.py" for finding in result.findings),
            self._render(result),
        )

    def _tree(self, extra: dict[str, str], *, policy: str | None = None, exceptions: str | None = None):
        return _Tree(extra, policy=policy, exceptions=exceptions)

    @staticmethod
    def _render(result) -> str:
        return "\n".join(finding.format() for finding in result.findings) or "<no findings>"


class _Tree:
    def __init__(self, extra: dict[str, str], *, policy: str | None, exceptions: str | None) -> None:
        self.extra = extra
        self.policy = policy
        self.exceptions = exceptions
        self.temp = tempfile.TemporaryDirectory()

    def __enter__(self) -> Path:
        root = Path(self.temp.name)
        files = {
            "ringer.py": "# privileged host\n",
            "hud/src/main.rs": HANDLER,
            "hud/capabilities/default.json": json.dumps(CAPABILITIES),
            "hud/tauri.conf.json": json.dumps(TAURI_CONF),
            "scripts/host.py": "# host tool\n",
            "checks/engine-bin-probe.py": "# host probe\n",
            "dashboard/ok.html": UI_SHELL,
            "hud/frontend/hud.js": "const tauri = window.__TAURI__;\n",
            "templates/ok.py": "import sys\n",
            "engines/ok.py": "import sys\n",
            "hooks/ok.py": "import sys\n",
            "tests/ok.py": "import ringer\n",
        }
        files.update(self.extra)
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        policy_path = root / "checks" / "dune_import_policy.toml"
        if self.policy is None:
            shutil.copyfile(ROOT / "checks" / "dune_import_policy.toml", policy_path)
        else:
            policy_path.write_text(self.policy, encoding="utf-8")
        exceptions_path = root / "checks" / "dune_import_exceptions.toml"
        if self.exceptions is None:
            shutil.copyfile(ROOT / "checks" / "dune_import_exceptions.toml", exceptions_path)
        else:
            exceptions_path.write_text(self.exceptions, encoding="utf-8")
        return root

    def __exit__(self, exc_type, exc, tb) -> None:
        self.temp.cleanup()


if __name__ == "__main__":
    unittest.main()
