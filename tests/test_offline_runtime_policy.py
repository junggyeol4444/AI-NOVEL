"""Local-only runtime is a required architecture constraint, not an option."""
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_novel_factory.settings import ConfigurationError, load_settings
from ai_novel_factory.architecture import load_contract, validate_contract


class OfflineRuntimePolicyTests(unittest.TestCase):
    def test_default_configuration_has_no_external_endpoints(self):
        settings = load_settings({})
        self.assertEqual(settings.api_host, "127.0.0.1")
        self.assertEqual(settings.ai_provider, "disabled")
        self.assertIsNone(settings.ai_api_key)
        self.assertIsNone(settings.database_url)
        self.assertIsNone(settings.redis_url)

    def test_local_model_can_be_selected_without_api_key(self):
        self.assertEqual(load_settings({"ANF_AI_PROVIDER": "local"}).ai_provider, "local")

    def test_external_api_host_rejected(self):
        for host in ("0.0.0.0", "example.com", "192.168.0.10"):
            with self.subTest(host=host), self.assertRaises(ConfigurationError):
                load_settings({"ANF_API_HOST": host})

    def test_loopback_hosts_allowed(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            with self.subTest(host=host):
                self.assertEqual(load_settings({"ANF_API_HOST": host}).api_host, host)

    def test_database_and_redis_service_urls_rejected(self):
        for key, address in (
            ("ANF_DATABASE_URL", "postgresql://u:p@localhost/db"),
            ("ANF_DATABASE_URL", "postgresql://u:p@example.com/db"),
            ("ANF_REDIS_URL", "redis://localhost:6379/0"),
            ("ANF_REDIS_URL", "redis://example.com:6379/0"),
        ):
            with self.subTest(key=key, address=address), self.assertRaises(ConfigurationError):
                load_settings({key: address})

    def test_cloud_provider_rejected_even_with_key(self):
        for name in ("openai", "anthropic", "cloud", "remote"):
            with self.subTest(provider=name), self.assertRaises(ConfigurationError):
                load_settings({"ANF_AI_PROVIDER": name, "ANF_AI_API_KEY": "unused-demo"})

    def test_local_provider_rejects_cloud_key(self):
        with self.assertRaises(ConfigurationError):
            load_settings({"ANF_AI_PROVIDER": "local", "ANF_AI_API_KEY": "unused-demo"})

    def test_design_contract_requires_offline_execution(self):
        self.assertEqual(validate_contract(load_contract(ROOT / "docs/architecture_decisions.json")), [])

    def test_design_contract_rejects_remote_service(self):
        contract = load_contract(ROOT / "docs/architecture_decisions.json")
        contract["deployment"]["postgresql_host"] = "cloud-server.example"
        self.assertTrue(validate_contract(contract))

    def test_design_contract_rejects_remote_ai(self):
        contract = load_contract(ROOT / "docs/architecture_decisions.json")
        for item in contract["components"]:
            if item["id"] == "provider":
                item["zone"] = "external"
        self.assertTrue(validate_contract(contract))

    def test_actual_reference_import_works_with_sockets_disabled(self):
        from ai_novel_factory.database import ReferenceCatalog
        from ai_novel_factory.references import import_reference_file
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "novel.txt"
            source.write_text("제1화\n\n첫 장면입니다.\n\n제2화\n\n다음 장면입니다.", encoding="utf-8")
            with patch("socket.socket", side_effect=AssertionError("network is forbidden")):
                with ReferenceCatalog(Path(tmp) / "catalog.sqlite3") as catalog:
                    result = import_reference_file(source, catalog=catalog)
                    self.assertEqual(result.statistics.episode_count, 2)
                    self.assertEqual(result.reference.status, "analyzed")
                    self.assertEqual(catalog.count(), 1)

    def test_packaged_source_has_no_github_workflow(self):
        self.assertFalse((ROOT / ".github").exists())
        self.assertFalse((ROOT / ".git").exists())


if __name__ == "__main__":
    unittest.main()
