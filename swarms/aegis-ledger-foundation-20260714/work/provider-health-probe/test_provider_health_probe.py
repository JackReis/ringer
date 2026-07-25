"""Tests for the provider health probe CLI and core functions."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

sys.dont_write_bytecode = True


def cleanup_pycache() -> None:
    """Remove bytecode cache artifacts created by normal unittest discovery."""

    shutil.rmtree(Path(__file__).resolve().parent / "__pycache__", ignore_errors=True)


atexit.register(cleanup_pycache)

from provider_health_probe import (  # noqa: E402
    ERROR_CREDENTIAL_HEADER,
    ERROR_HTTP,
    STATUS_DOWN,
    STATUS_RATE_LIMITED,
    STATUS_UP,
    probe_provider,
    write_json_atomic,
)


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "provider_health_probe.py"
SECRET_MARKER = "fixture-secret-marker"


@dataclass(frozen=True)
class CliRun:
    """Captured CLI subprocess result and output artifact."""

    returncode: int
    stdout: str
    stderr: str
    output_text: str
    payload: Optional[Dict[str, Any]]
    output_exists: bool


@contextmanager
def local_server(
    routes: Mapping[str, int],
) -> Iterator[Tuple[str, List[str]]]:
    """Run a loopback ThreadingHTTPServer with fixed route statuses."""

    requests: List[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length:
                self.rfile.read(length)
            self._handle()

        def _handle(self) -> None:
            requests.append(self.path)
            status = routes.get(self.path, 404)
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"server body {SECRET_MARKER}".encode("utf-8"))

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.block_on_close = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class ProviderHealthProbeTests(unittest.TestCase):
    """Behavioral coverage for provider health probing."""

    def run_cli(
        self,
        config: Optional[Mapping[str, Any]] = None,
        raw_config: Optional[str] = None,
        output_name: str = "results/result.json",
    ) -> CliRun:
        """Run the probe CLI in a subprocess with temporary files."""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_path = temp_path / "config.json"
            output_path = temp_path / output_name

            if raw_config is not None:
                config_path.write_text(raw_config, encoding="utf-8")
            else:
                config_path.write_text(
                    json.dumps(config if config is not None else {}),
                    encoding="utf-8",
                )

            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config_path),
                    "--output",
                    str(output_path),
                ],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            output_exists = output_path.exists()
            output_text = (
                output_path.read_text(encoding="utf-8") if output_exists else ""
            )
            payload = json.loads(output_text) if output_text else None
            return CliRun(
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                output_text=output_text,
                payload=payload,
                output_exists=output_exists,
            )

    def test_cli_200_is_up_and_exits_zero(self) -> None:
        """A 200 response is up and makes the CLI exit 0."""

        with local_server({"/ok": 200}) as (base_url, _requests):
            result = self.run_cli(
                {
                    "providers": [
                        {
                            "name": "ok-provider",
                            "url": f"{base_url}/ok",
                            "method": "GET",
                            "timeout_s": 2,
                        }
                    ]
                }
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.output_exists)
        self.assertIsNotNone(result.payload)
        record = result.payload["providers"][0]  # type: ignore[index]
        self.assertEqual(record["provider"], "ok-provider")
        self.assertEqual(record["status"], STATUS_UP)
        self.assertEqual(record["http_status"], 200)
        self.assertIsNone(record["error_category"])
        self.assertIsInstance(record["latency_ms"], int)
        self.assertGreaterEqual(record["latency_ms"], 0)
        self.assertTrue(record["timestamp"].endswith("Z"))
        self.assertNotIn(SECRET_MARKER, result.output_text)

    def test_cli_429_is_rate_limited_and_exits_one(self) -> None:
        """A 429 response is rate-limited and makes the CLI exit 1."""

        with local_server({"/limit": 429}) as (base_url, _requests):
            result = self.run_cli(
                {
                    "providers": [
                        {
                            "name": "limited-provider",
                            "url": f"{base_url}/limit",
                            "method": "GET",
                            "timeout_s": 2,
                        }
                    ]
                }
            )

        self.assertEqual(result.returncode, 1)
        record = result.payload["providers"][0]  # type: ignore[index]
        self.assertEqual(record["status"], STATUS_RATE_LIMITED)
        self.assertEqual(record["http_status"], 429)
        self.assertEqual(record["error_category"], STATUS_RATE_LIMITED)

    def test_core_500_is_down(self) -> None:
        """A 500 response is down in the core probe function."""

        with local_server({"/err": 500}) as (base_url, _requests):
            record = probe_provider(
                {
                    "name": "error-provider",
                    "url": f"{base_url}/err",
                    "method": "GET",
                    "timeout_s": 2,
                }
            )

        self.assertEqual(record["status"], STATUS_DOWN)
        self.assertEqual(record["http_status"], 500)
        self.assertEqual(record["error_category"], ERROR_HTTP)
        self.assertNotIn(SECRET_MARKER, json.dumps(record))

    def test_unreachable_endpoint_is_down_without_leaked_url(self) -> None:
        """A refused loopback port is down without URL or exception leakage."""

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        secret_path = f"/{SECRET_MARKER}/unreachable"
        url = f"http://127.0.0.1:{port}{secret_path}"
        result = self.run_cli(
            {
                "providers": [
                    {
                        "name": "unreachable-provider",
                        "url": url,
                        "method": "GET",
                        "timeout_s": 0.2,
                    }
                ]
            }
        )

        self.assertEqual(result.returncode, 1)
        record = result.payload["providers"][0]  # type: ignore[index]
        self.assertEqual(record["status"], STATUS_DOWN)
        self.assertIsNone(record["http_status"])
        self.assertNotIn(url, result.output_text)
        self.assertNotIn(secret_path, result.output_text)
        self.assertNotIn("Connection refused", result.output_text)

    def test_malformed_config_has_clean_nonzero_error(self) -> None:
        """Malformed top-level JSON exits nonzero without a traceback."""

        result = self.run_cli(raw_config="{")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.strip(), "malformed-config")
        self.assertNotIn("Traceback", result.stderr + result.stdout)
        self.assertTrue(result.output_exists)
        self.assertEqual(result.payload["providers"], [])  # type: ignore[index]

    def test_credential_like_header_is_rejected(self) -> None:
        """Credential-like header names are rejected before probing."""

        with local_server({"/ok": 200}) as (base_url, requests):
            result = self.run_cli(
                {
                    "providers": [
                        {
                            "name": "unsafe-provider",
                            "url": f"{base_url}/ok",
                            "method": "GET",
                            "timeout_s": 2,
                            "headers": {"X-API-Key": SECRET_MARKER},
                        }
                    ]
                }
            )

        self.assertEqual(requests, [])
        self.assertEqual(result.returncode, 1)
        record = result.payload["providers"][0]  # type: ignore[index]
        self.assertEqual(record["status"], STATUS_DOWN)
        self.assertIsNone(record["http_status"])
        self.assertEqual(record["error_category"], ERROR_CREDENTIAL_HEADER)
        self.assertNotIn(SECRET_MARKER, result.output_text + result.stdout + result.stderr)
        self.assertNotIn("X-API-Key", result.output_text)

    def test_provider_order_matches_config_order(self) -> None:
        """Results preserve deterministic provider order from config."""

        with local_server({"/one": 200, "/two": 500, "/three": 429}) as (
            base_url,
            _requests,
        ):
            result = self.run_cli(
                {
                    "providers": [
                        {
                            "name": "third",
                            "url": f"{base_url}/three",
                            "method": "GET",
                            "timeout_s": 2,
                        },
                        {
                            "name": "first",
                            "url": f"{base_url}/one",
                            "method": "GET",
                            "timeout_s": 2,
                        },
                        {
                            "name": "second",
                            "url": f"{base_url}/two",
                            "method": "GET",
                            "timeout_s": 2,
                        },
                    ]
                }
            )

        names = [record["provider"] for record in result.payload["providers"]]  # type: ignore[index]
        self.assertEqual(names, ["third", "first", "second"])

    def test_atomic_output_creation(self) -> None:
        """Atomic writer creates parents and leaves a complete JSON file."""

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "nested" / "result.json"
            payload = {"generated_at": "2026-07-14T00:00:00.000Z", "providers": []}

            write_json_atomic(output_path, payload)

            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), payload)
            self.assertEqual(
                sorted(path.name for path in output_path.parent.iterdir()),
                ["result.json"],
            )

    def test_output_omits_fixture_secret_marker(self) -> None:
        """Output omits secrets from body, headers, and response body."""

        with local_server({"/fail": 500}) as (base_url, _requests):
            result = self.run_cli(
                {
                    "providers": [
                        {
                            "name": "secret-fixture",
                            "url": f"{base_url}/fail",
                            "method": "POST",
                            "timeout_s": 2,
                            "headers": {"X-Trace": SECRET_MARKER},
                            "body": {"secret": SECRET_MARKER},
                        }
                    ]
                }
            )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn(SECRET_MARKER, result.output_text + result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
