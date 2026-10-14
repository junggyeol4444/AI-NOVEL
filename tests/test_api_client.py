"""Stage 9: check only loopback and never leak raw HTTP payloads."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_novel_factory.desktop.api_client import (
    HealthCheckResult, check_local_health, local_health_url
)
from ai_novel_factory.settings import AppSettings


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200):
        self.data, self.status = data, status

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, n): return self.data[:n]


class ClientTests(unittest.TestCase):
    def test_url_localhost(self):
        self.assertEqual(local_health_url(AppSettings()), "http://127.0.0.1:8000/health")

    def test_ipv6_loopback(self):
        self.assertEqual(local_health_url(AppSettings(api_host="::1")), "http://[::1]:8000/health")

    def test_nonlocal_refused(self):
        with self.assertRaises(ValueError):
            local_health_url(AppSettings(api_host="example.com"))

    def test_nonlocal_never_opens_connection(self):
        with patch("urllib.request.build_opener") as opener:
            result = check_local_health(AppSettings(api_host="example.com"))
            self.assertFalse(result.connected)
            opener.assert_not_called()

    def test_success(self):
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(
                b'{"status":"ok","service":"ai-novel-factory","api_version":"v1"}'
            )
            result = check_local_health(AppSettings())
        self.assertEqual(result, HealthCheckResult(True, "로컬 API 연결됨"))

    def test_wrong_contract(self):
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(b'{"status":"ok"}')
            result = check_local_health(AppSettings())
        self.assertFalse(result.connected)

    def test_malformed_response_not_echoed(self):
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(b'SECRET-TOKEN')
            result = check_local_health(AppSettings())
        self.assertFalse(result.connected)
        self.assertNotIn("SECRET-TOKEN", result.message)
        self.assertEqual(result.message, "API 응답 형식 불일치")

    def test_bad_status(self):
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse(b'{}', status=503)
            result = check_local_health(AppSettings())
        self.assertFalse(result.connected)


if __name__ == "__main__":
    unittest.main()
