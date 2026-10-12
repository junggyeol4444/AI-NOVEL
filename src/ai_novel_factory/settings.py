"""Stage 6: side-effect-free application configuration (Python stdlib only).

No network, filesystem or OS modifications occur when this module is imported.
Secrets are neither printed nor included in repr() or validation errors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
import os
import re
from urllib.parse import urlsplit

_ALLOWED = frozenset({
    "ANF_ENV", "ANF_API_HOST", "ANF_API_PORT", "ANF_LOG_LEVEL",
    "ANF_AI_PROVIDER", "ANF_AI_API_KEY", "ANF_DATABASE_URL", "ANF_REDIS_URL",
})
_SECRET_KEYS = frozenset({"ANF_AI_API_KEY", "ANF_DATABASE_URL", "ANF_REDIS_URL"})
_KEY_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


class ConfigurationError(ValueError):
    """Configuration is invalid. Messages never contain supplied values."""


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a simple explicit development file; never evaluate or interpolate text."""
    parsed: dict[str, str] = {}
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _KEY_PATTERN.fullmatch(line)
        if not match:
            raise ConfigurationError(f"Malformed configuration at line {number}")
        key, value = match.groups()
        if key not in _ALLOWED:
            raise ConfigurationError(f"Unknown configuration key at line {number}")
        if key in parsed:
            raise ConfigurationError(f"Duplicate configuration key at line {number}")
        # Optional single/double quotes, no shell expansion, no inline comments.
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigurationError(f"Malformed quoted value at line {number}")
            value = value[1:-1]
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ConfigurationError(f"Invalid control character at line {number}")
        parsed[key] = value
    return parsed


def _port(value: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("ANF_API_PORT must be a number") from None
    if not 1 <= port <= 65535:
        raise ConfigurationError("ANF_API_PORT is outside the valid range")
    return port


def _service_url(value: str, key: str, schemes: set[str]) -> str | None:
    if not value:
        return None
    try:
        parts = urlsplit(value)
        valid = parts.scheme in schemes and bool(parts.hostname)
        # Do not allow query or fragments, which could accidentally expose tokens.
        valid = valid and not parts.query and not parts.fragment
        _ = parts.port  # Forces validation of malformed port numbers.
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(f"{key} has an invalid connection URL")
    return value


@dataclass(frozen=True, slots=True)
class AppSettings:
    environment: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"
    ai_provider: str = "disabled"
    ai_api_key: str | None = field(default=None, repr=False)
    database_url: str | None = field(default=None, repr=False)
    redis_url: str | None = field(default=None, repr=False)

    def safe_status(self) -> dict[str, str | int | bool]:
        """Suitable for diagnostics: only presence flags for secret-bearing fields."""
        return {
            "environment": self.environment,
            "api_host": self.api_host,
            "api_port": self.api_port,
            "log_level": self.log_level,
            "ai_provider": self.ai_provider,
            "ai_key_configured": bool(self.ai_api_key),
            "database_configured": bool(self.database_url),
            "redis_configured": bool(self.redis_url),
        }


def load_settings(
    environ: Mapping[str, str] | None = None,
    *,
    env_file: str | Path | None = None,
) -> AppSettings:
    """Explicit env_file is opt-in; process environment takes precedence."""
    values = parse_env_file(env_file) if env_file is not None else {}
    values.update(dict(os.environ if environ is None else environ))

    environment = values.get("ANF_ENV", "development").strip().lower()
    if environment not in {"development", "test", "production"}:
        raise ConfigurationError("ANF_ENV must be development, test, or production")
    api_host = values.get("ANF_API_HOST", "127.0.0.1").strip()
    if not api_host or any(c.isspace() for c in api_host) or "/" in api_host:
        raise ConfigurationError("ANF_API_HOST is invalid")
    log_level = values.get("ANF_LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError("ANF_LOG_LEVEL is invalid")
    provider = values.get("ANF_AI_PROVIDER", "disabled").strip().lower()
    if not provider or not re.fullmatch(r"[a-z0-9_-]{1,40}", provider):
        raise ConfigurationError("ANF_AI_PROVIDER is invalid")
    ai_key = values.get("ANF_AI_API_KEY", "").strip() or None
    if ai_key is not None and ai_key.lower() in {"your-key", "changeme", "example", "placeholder"}:
        raise ConfigurationError("ANF_AI_API_KEY is a placeholder")
    if provider != "disabled" and not ai_key:
        raise ConfigurationError("ANF_AI_API_KEY is required for an enabled provider")

    return AppSettings(
        environment=environment,
        api_host=api_host,
        api_port=_port(values.get("ANF_API_PORT", "8000")),
        log_level=log_level,
        ai_provider=provider,
        ai_api_key=ai_key,
        database_url=_service_url(values.get("ANF_DATABASE_URL", "").strip(),
                                  "ANF_DATABASE_URL", {"postgresql", "postgresql+psycopg"}),
        redis_url=_service_url(values.get("ANF_REDIS_URL", "").strip(),
                               "ANF_REDIS_URL", {"redis", "rediss"}),
    )


if __name__ == "__main__":
    # Only safe_status is emitted; never print AppSettings or process environment.
    print(load_settings().safe_status())