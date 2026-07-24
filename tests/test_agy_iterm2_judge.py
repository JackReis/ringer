from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "engines" / "agy-iterm2-judge.py"
LAUNCHER_PATH = ROOT / "engines" / "agy-iterm2-judge.sh"


def load_engine_module():
    spec = importlib.util.spec_from_file_location("agy_iterm2_judge", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgyIterm2JudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = load_engine_module()

    def test_parse_args_preserves_ringer_spec(self) -> None:
        parsed = self.engine.parse_args(
            [
                "--taskdir",
                "/tmp/ringer-task",
                "--model",
                "Gemini 3.1 Pro (High)",
                "--",
                "Review the patch and write the verdict.",
            ]
        )

        self.assertEqual(parsed.taskdir, "/tmp/ringer-task")
        self.assertEqual(parsed.model, "Gemini 3.1 Pro (High)")
        self.assertEqual(parsed.spec_text, "Review the patch and write the verdict.")

    def test_busy_detection_matches_known_tui_states(self) -> None:
        self.assertTrue(self.engine.is_busy("Thinking about the request"))
        self.assertTrue(self.engine.is_busy("Generating · esc to cancel"))
        self.assertFalse(self.engine.is_busy("Antigravity CLI ready"))

    def test_ready_tokens_require_the_interactive_prompt(self) -> None:
        shell_command = "agy --model 'Gemini 3.1 Pro (High)'"
        ready_screen = "Antigravity CLI 1.1.5\n>\n? for shortcuts"

        self.assertFalse(
            all(token in shell_command for token in self.engine.READY_TOKENS)
        )
        self.assertTrue(
            all(token in ready_screen for token in self.engine.READY_TOKENS)
        )

    def test_workspace_trust_prompt_is_explicit(self) -> None:
        self.assertEqual(
            self.engine.TRUST_PROMPT,
            "Do you trust the contents of this project?",
        )

    def test_file_completion_requires_multiple_stable_polls(self) -> None:
        self.assertGreaterEqual(self.engine.FILE_STABLE_POLLS, 5)

    def test_launcher_uses_the_dedicated_iterm2_environment(self) -> None:
        launcher = LAUNCHER_PATH.read_text(encoding="utf-8")

        self.assertIn("agy-iterm2-venv/bin/python", launcher)
        self.assertIn('exec "$VENV_PY"', launcher)


if __name__ == "__main__":
    unittest.main()
