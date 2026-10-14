"""Stage 10: non-destructive startup smoke checks for AI Novel Factory.

Default mode is offline and requires only Python standard library.
Opt-in --with-http starts a temporary *loopback-only* FastAPI process.
Opt-in --with-gui creates an offscreen Qt window without entering the event loop.
No database, Redis, AI provider or publisher is contacted.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_novel_factory.api.health import health_payload
from ai_novel_factory.desktop.api_client import check_local_health
from ai_novel_factory.desktop.navigation import SECTIONS
from ai_novel_factory.settings import AppSettings, load_settings


@dataclass(frozen=True)
class Result:
    check: str
    status: str  # PASS, FAIL, SKIP, WARN
    detail: str


def _safe_environment() -> dict[str, str]:
    """Avoid inherited project secrets/settings in child processes."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANF_")}
    env["PYTHONPATH"] = str(SRC)
    env["ANF_ENV"] = "test"
    env["ANF_AI_PROVIDER"] = "disabled"
    return env


def _command_check(module: str, expected: str) -> Result:
    name = module.rsplit(".", 1)[-1] + "_cli"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", module, "--check"],
            cwd=ROOT, env=_safe_environment(), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        if completed.returncode != 0 or expected not in completed.stdout:
            return Result(name, "FAIL", "실행 진입점 또는 출력 계약 불일치")
        return Result(name, "PASS", "실행 진입점 정상")
    except (OSError, subprocess.TimeoutExpired):
        return Result(name, "FAIL", "실행 진입점 시작 실패 또는 시간 초과")


def offline_checks() -> list[Result]:
    results: list[Result] = []
    settings = load_settings(environ={})
    safe = settings.safe_status()
    if (settings.ai_provider == "disabled" and settings.ai_api_key is None
            and settings.database_url is None and settings.redis_url is None
            and safe["ai_key_configured"] is False):
        results.append(Result("safe_defaults", "PASS", "외부 서비스·AI 기본 비활성"))
    else:
        results.append(Result("safe_defaults", "FAIL", "기본 비활성 정책 위반"))

    expected = {"status": "ok", "service": "ai-novel-factory", "api_version": "v1"}
    results.append(Result("health_contract", "PASS" if health_payload() == expected else "FAIL",
                          "비밀정보 없는 상태 응답 계약"))
    keys = [section.key for section in SECTIONS]
    results.append(Result("desktop_navigation", "PASS" if len(keys) == 12 and len(set(keys)) == 12 else "FAIL",
                          "12개 화면 및 메뉴 키 중복 검사"))

    with patch("urllib.request.build_opener") as opener:
        blocked = check_local_health(AppSettings(api_host="example.com"))
        no_connection = not blocked.connected and not opener.called
    results.append(Result("loopback_guard", "PASS" if no_connection else "FAIL",
                          "외부 호스트 접속 차단"))
    results.append(_command_check("ai_novel_factory.api", "ai-novel-factory"))
    results.append(_command_check("ai_novel_factory.desktop", "12 sections"))

    if sys.version_info[:2] != (3, 12):
        results.append(Result("python_version", "WARN", "개발 기준 Python 3.12와 다른 실행 환경"))
    else:
        results.append(Result("python_version", "PASS", "개발 기준 Python 3.12 확인"))
    return results


def _has_modules(*names: str) -> bool:
    return all(importlib.util.find_spec(name) is not None for name in names)


def http_check() -> Result:
    """Start and stop a child API process bound to 127.0.0.1 only."""
    if not _has_modules("fastapi", "uvicorn"):
        return Result("http_roundtrip", "SKIP", "FastAPI 또는 uvicorn 미설치")
    # Allocate a temporary port, then release it before uvicorn binds it.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
    except OSError:
        return Result("http_roundtrip", "FAIL", "루프백 포트 확보 실패")
    env = _safe_environment()
    env["ANF_API_HOST"] = "127.0.0.1"
    env["ANF_API_PORT"] = str(port)
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "ai_novel_factory.api"],
            cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return Result("http_roundtrip", "FAIL", "API 프로세스 조기 종료")
            try:
                with opener.open(Request(f"http://127.0.0.1:{port}/health"), timeout=0.4) as resp:
                    if resp.status == 200 and json.loads(resp.read(4096)) == health_payload():
                        return Result("http_roundtrip", "PASS", "루프백 HTTP 요청·응답 정상")
                    return Result("http_roundtrip", "FAIL", "HTTP 상태 또는 응답 계약 불일치")
            except (URLError, TimeoutError, OSError):
                time.sleep(0.1)
        return Result("http_roundtrip", "FAIL", "API 응답 대기 시간 초과")
    except OSError:
        return Result("http_roundtrip", "FAIL", "API 프로세스 실행 실패")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


def gui_check() -> Result:
    if not _has_modules("PySide6"):
        return Result("gui_offscreen", "SKIP", "PySide6 미설치")
    code = (
        "from PySide6.QtWidgets import QApplication; "
        "from ai_novel_factory.desktop.app import MainWindow; "
        "a=QApplication([]); w=MainWindow(); "
        "assert w.sidebar.count()==12; "
        "assert 'API 미연결' in w.statusBar().currentMessage(); "
        "w.close()"
    )
    env = _safe_environment()
    env["QT_QPA_PLATFORM"] = "offscreen"
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        )
        return Result("gui_offscreen", "PASS" if completed.returncode == 0 else "FAIL",
                      "Qt 오프스크린 창 생성·닫기" if completed.returncode == 0 else "Qt 오프스크린 실행 실패")
    except (OSError, subprocess.TimeoutExpired):
        return Result("gui_offscreen", "FAIL", "Qt 프로세스 시작 실패 또는 시간 초과")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Novel Factory 10단계 초기 스모크 테스트")
    parser.add_argument("--json", action="store_true", help="JSON 형식 결과 출력")
    parser.add_argument("--with-http", action="store_true", help="임시 로컬 API 서버 실행 (명시적 선택)")
    parser.add_argument("--with-gui", action="store_true", help="Qt 오프스크린 UI 실행 (명시적 선택)")
    args = parser.parse_args(argv)
    try:
        results = offline_checks()
    except Exception:
        # Do not echo exception values: they might contain secret-bearing input.
        results = [Result("offline_checks", "FAIL", "오프라인 검사 중 오류")]
    if args.with_http:
        results.append(http_check())
    if args.with_gui:
        results.append(gui_check())
    failed = any(result.status == "FAIL" for result in results)
    if args.json:
        print(json.dumps({"stage": 10, "passed": not failed,
                          "results": [asdict(r) for r in results]}, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"[{result.status}] {result.check}: {result.detail}")
        print("스모크 테스트:", "실패" if failed else "필수 항목 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
