"""Stage 9: local API contract and non-sensitive responses."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_novel_factory.api.health import health_payload
from ai_novel_factory.api.__main__ import main


class ApiHealthTests(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(health_payload(), {
            "status": "ok", "service": "ai-novel-factory", "api_version": "v1"
        })

    def test_no_secrets_or_external_calls(self):
        self.assertEqual(set(health_payload()), {"status", "service", "api_version"})

    def test_check_mode_without_optional_dependencies(self):
        self.assertEqual(main(["--check"]), 0)

    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "FastAPI not installed")
    def test_fastapi_health_endpoint(self):
        from fastapi.testclient import TestClient
        from ai_novel_factory.api.health import create_app
        client = TestClient(create_app())
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), health_payload())


if __name__ == "__main__":
    unittest.main()
