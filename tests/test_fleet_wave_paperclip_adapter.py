from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/fleet_wave_paperclip_adapter.py"
SPEC = importlib.util.spec_from_file_location("fleet_wave_paperclip_adapter", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class PaperclipAdapterTransportTests(unittest.TestCase):
    def test_v2_envelope_roundtrips_literal_backslash_n_without_transport_ambiguity(self):
        payload = '{"setup":"printf \'corrupt bundle\\\\n\' > candidate.bundle"}'
        marker, body, payload_sha, stable_key = ADAPTER.comment_transport(payload, "receipt:terminal")
        self.assertTrue(marker.startswith("[fleet-wave-v2:"))
        self.assertNotIn("\\n", body)
        self.assertEqual(payload, ADAPTER.decode_comment_body(body, marker))
        self.assertEqual("receipt:terminal", stable_key)
        self.assertEqual(64, len(payload_sha))

    def test_comment_posts_once_and_requires_exact_decoded_readback(self):
        payload = '{"setup":"line one\\\\nline two"}'
        stored: list[dict[str, object]] = []

        def fake_request(method: str, path: str, body: object | None = None) -> object:
            if method == "POST":
                assert isinstance(body, dict)
                stored.append({"id": "comment-1", "body": body["body"]})
                return stored[-1]
            raise AssertionError((method, path))

        with (
            mock.patch.object(ADAPTER, "issue", return_value={"id": "canonical", "identifier": "JAC-3584"}),
            mock.patch.object(ADAPTER, "comments", side_effect=lambda _canonical: list(stored)),
            mock.patch.object(ADAPTER, "request", side_effect=fake_request),
        ):
            first = ADAPTER.command_comment(["JAC-3584", payload, "--idempotency-key", "receipt:terminal", "--json"])
            second = ADAPTER.command_comment(["JAC-3584", payload, "--idempotency-key", "receipt:terminal", "--json"])

        self.assertEqual(1, len(stored))
        self.assertTrue(first["exact_readback"])
        self.assertEqual("fleet-wave-comment.v2", first["transport_version"])
        self.assertEqual(first, second)
        self.assertEqual(payload, ADAPTER.decode_comment_body(str(stored[0]["body"]), "[fleet-wave-v2:receipt:terminal]"))

    def test_decode_rejects_payload_hash_mismatch(self):
        payload = '{"result":"PASS"}'
        marker, body, _payload_sha, _stable_key = ADAPTER.comment_transport(payload, "receipt:terminal")
        tampered = body.replace("PASS", "FAIL")
        if tampered == body:
            # The payload is base64, so mutate one base64 character while retaining valid JSON.
            tampered = body.replace("Q", "R", 1)
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.decode_comment_body(tampered, marker)


if __name__ == "__main__":
    unittest.main()
