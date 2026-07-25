import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error


SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "audit_surfaces.py")


def load_audit_module():
    if not os.path.exists(SCRIPT_PATH):
        raise AssertionError("audit_surfaces.py must exist")

    spec = importlib.util.spec_from_file_location("audit_surfaces", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass


class AuditSurfacesTests(unittest.TestCase):
    def test_script_module_exists(self):
        self.assertTrue(os.path.exists(SCRIPT_PATH), "audit_surfaces.py must exist")

    def test_extracts_normalizes_and_deduplicates_loopback_urls(self):
        audit = load_audit_module()
        markdown = """
        http://127.0.0.1:3100/api
        http://127.0.0.1:3100/api
        http://localhost:8083/dashboard?mode=fleet
        127.0.0.1:5434
        https://aegis.tailc2f398.ts.net:3012
        """

        self.assertEqual(
            audit.extract_local_urls(markdown),
            [
                "http://127.0.0.1:3100/api",
                "http://localhost:8083/dashboard?mode=fleet",
                "http://127.0.0.1:5434",
            ],
        )

    def test_http_get_records_success_status_and_timing(self):
        audit = load_audit_module()
        opened = []

        def opener(request, timeout):
            opened.append((request.full_url, request.get_method(), timeout))
            return FakeResponse(204)

        result = audit.check_http(
            "http://127.0.0.1:8787/health",
            timeout=1,
            opener=opener,
        )

        self.assertEqual(result["status_code"], 204)
        self.assertTrue(result["reachable"])
        self.assertIsInstance(result["response_time_ms"], (int, float))
        self.assertGreaterEqual(result["response_time_ms"], 0)
        self.assertIsNone(result["error"])
        self.assertEqual(opened, [("http://127.0.0.1:8787/health", "GET", 1)])

    def test_http_error_status_is_still_reachable(self):
        audit = load_audit_module()

        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                {},
                None,
            )

        result = audit.check_http(
            "http://127.0.0.1:8787/missing",
            timeout=1,
            opener=opener,
        )

        self.assertEqual(result["status_code"], 404)
        self.assertTrue(result["reachable"])
        self.assertIsNone(result["error"])

    def test_http_connection_refusal_is_unreachable(self):
        audit = load_audit_module()

        def opener(request, timeout):
            raise urllib.error.URLError(ConnectionRefusedError("connection refused"))

        result = audit.check_http(
            "http://127.0.0.1:1",
            timeout=0.2,
            opener=opener,
        )

        self.assertIsNone(result["status_code"])
        self.assertFalse(result["reachable"])
        self.assertTrue(result["error"])

    def test_tcp_check_reports_an_accepting_port_without_http(self):
        audit = load_audit_module()
        connections = []

        def connector(address, timeout):
            connections.append((address, timeout))
            return FakeConnection()

        result = audit.check_tcp(
            "http://127.0.0.1:8005/ignored",
            timeout=1,
            connector=connector,
        )

        self.assertIsNone(result["status_code"])
        self.assertTrue(result["reachable"])
        self.assertIsNone(result["error"])
        self.assertEqual(connections, [(('127.0.0.1', 8005), 1)])

    def test_tcp_check_reports_connection_refusal(self):
        audit = load_audit_module()

        def connector(address, timeout):
            raise ConnectionRefusedError("connection refused")

        result = audit.check_tcp(
            "http://127.0.0.1:8005/ignored",
            timeout=1,
            connector=connector,
        )

        self.assertIsNone(result["status_code"])
        self.assertFalse(result["reachable"])
        self.assertIn("connection refused", result["error"])

    def test_port_8005_is_dispatched_to_tcp_check(self):
        audit = load_audit_module()
        calls = []

        def http_checker(url, timeout):
            calls.append(("http", url, timeout))
            return {}

        def tcp_checker(url, timeout):
            calls.append(("tcp", url, timeout))
            return {}

        audit.audit_url(
            "http://127.0.0.1:8005/v3/workspaces/list",
            timeout=1.5,
            http_checker=http_checker,
            tcp_checker=tcp_checker,
        )

        self.assertEqual(
            calls,
            [("tcp", "http://127.0.0.1:8005/v3/workspaces/list", 1.5)],
        )

    def test_report_and_summary_use_required_fields(self):
        audit = load_audit_module()
        results = [
            {
                "url": "http://127.0.0.1:3100/api",
                "status_code": 200,
                "reachable": True,
                "response_time_ms": 12.34,
                "error": None,
            }
        ]

        with tempfile.TemporaryDirectory() as directory:
            report_path = os.path.join(directory, "report.json")
            audit.write_report(results, report_path)
            with open(report_path, encoding="utf-8") as handle:
                persisted = json.load(handle)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            audit.print_summary(results)

        self.assertEqual(persisted, results)
        self.assertIn("URL", stdout.getvalue())
        self.assertIn("http://127.0.0.1:3100/api", stdout.getvalue())
        self.assertIn("200", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
