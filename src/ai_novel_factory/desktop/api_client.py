"""Opt-in local health check. Never contacts a server during import/startup."""
from __future__ import annotations
from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

from ai_novel_factory.settings import AppSettings

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class HealthCheckResult:
    connected: bool
    message: str


def local_health_url(settings: AppSettings) -> str:
    """Reject non-loopback hosts before opening any network connection."""
    if settings.api_host not in _LOOPBACK:
        raise ValueError("외부 API 연결은 승인 전 허용하지 않습니다.")
    host = "[::1]" if settings.api_host == "::1" else settings.api_host
    return f"http://{host}:{settings.api_port}/health"


def check_local_health(settings: AppSettings, *, timeout: float = 1.5) -> HealthCheckResult:
    """Explicit, bounded request; never return exception contents or remote payload."""
    try:
        url = local_health_url(settings)
    except ValueError:
        return HealthCheckResult(False, "로컬 API만 연결할 수 있습니다")
    try:
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        # Deliberately disable environment-provided proxy handlers for loopback.
        from urllib.request import build_opener, ProxyHandler
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return HealthCheckResult(False, "API 연결 실패 (상태 코드 오류)")
            payload = json.loads(response.read(4096).decode("utf-8"))
        if not isinstance(payload, dict) or (
            payload.get("status") != "ok"
            or payload.get("service") != "ai-novel-factory"
            or payload.get("api_version") != "v1"
        ):
            return HealthCheckResult(False, "API 응답 형식 불일치")
        return HealthCheckResult(True, "로컬 API 연결됨")
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return HealthCheckResult(False, "API 응답 형식 불일치")
    except (HTTPError, URLError, TimeoutError, OSError):
        return HealthCheckResult(False, "로컬 API 연결 실패")
