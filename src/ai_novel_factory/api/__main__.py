"""Run local API after installing optional `api` dependencies.

python -m ai_novel_factory.api [--check]
"""
from __future__ import annotations
import sys

from ai_novel_factory.settings import load_settings
from ai_novel_factory.api.health import health_payload

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["--check"]:
        print(health_payload())
        return 0
    if args:
        print("Usage: python -m ai_novel_factory.api [--check]", file=sys.stderr)
        return 2
    settings = load_settings()
    if settings.api_host not in _LOOPBACK:
        print("승인되지 않은 외부 바인딩은 허용하지 않습니다.", file=sys.stderr)
        return 4
    try:
        import uvicorn
        from .health import create_app
        app = create_app()
    except ImportError:
        print("FastAPI/uvicorn 미설치: api 선택 의존성이 필요합니다.", file=sys.stderr)
        return 3
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
