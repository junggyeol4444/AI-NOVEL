"""Stage 6: configuration precedence, validation, and redaction tests."""
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_novel_factory.settings import AppSettings, ConfigurationError, load_settings, parse_env_file


class SettingsTests(unittest.TestCase):
    def test_defaults_do_not_connect(self):
        settings = load_settings({})
        self.assertEqual(settings.environment, "development")
        self.assertEqual(settings.ai_provider, "disabled")
        self.assertIsNone(settings.database_url)
        self.assertIsNone(settings.redis_url)
        self.assertFalse(settings.safe_status()["ai_key_configured"])

    def test_env_precedence_over_explicit_file(self):
        with tempfile.TemporaryDirectory() as temp:
            envfile = Path(temp) / ".env"
            envfile.write_text("ANF_API_PORT=8001\nANF_ENV=test\n", encoding="utf-8")
            settings = load_settings({"ANF_API_PORT": "9000"}, env_file=envfile)
            self.assertEqual(settings.api_port, 9000)
            self.assertEqual(settings.environment, "test")

    def test_secrets_never_appear_in_repr_or_safe_status(self):
        secret = "a-test-secret-not-for-logs"
        # Legacy objects still redact secrets; runtime settings reject service URLs.
        settings = AppSettings(
            ai_provider="mock", ai_api_key=secret,
            database_url=f"postgresql://user:{secret}@localhost:5432/novels",
            redis_url=f"redis://:{secret}@localhost:6379/0",
        )
        output = repr(settings) + repr(settings.safe_status())
        self.assertNotIn(secret, output)
        self.assertTrue(settings.safe_status()["database_configured"])

    def test_error_does_not_echo_secret(self):
        secret = "private-invalid-connection"
        with self.assertRaises(ConfigurationError) as raised:
            load_settings({"ANF_DATABASE_URL": secret})
        self.assertNotIn(secret, str(raised.exception))

    def test_invalid_port(self):
        for port in ("0", "65536", "not-a-port"):
            with self.subTest(port=port), self.assertRaises(ConfigurationError):
                load_settings({"ANF_API_PORT": port})

    def test_provider_requires_key(self):
        with self.assertRaises(ConfigurationError):
            load_settings({"ANF_AI_PROVIDER": "provider_name"})

    def test_reject_unknown_or_duplicate_env_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ".env"
            path.write_text("NOT_AN_APP_KEY=anything\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                parse_env_file(path)
            path.write_text("ANF_ENV=test\nANF_ENV=production\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                parse_env_file(path)

    def test_example_contains_no_secret_values(self):
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in ("ANF_AI_API_KEY", "ANF_DATABASE_URL", "ANF_REDIS_URL"):
            self.assertIn(f"{key}=\n", example)

    def test_gitignore_keeps_env_private(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env.*", gitignore)
        self.assertIn("!.env.example", gitignore)

    def test_settings_are_immutable(self):
        settings = load_settings({})
        with self.assertRaises(AttributeError):
            settings.api_port = 9001


if __name__ == "__main__":
    unittest.main()
