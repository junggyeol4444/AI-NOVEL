"""Offline Windows-only PyInstaller build with fail-closed preflight and smoke tests.

Never fetches, installs, uploads, publishes, accesses GitHub, or launches remote AI.
All build outputs stay under project-local ignored build/ and dist/ folders.
The generated EXE is not distributable as 'tested' until genuine Windows checks pass.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'packaging' / 'windows' / 'AI_Novel_Factory.spec'
EXE_NAME = 'AI_Novel_Factory.exe'
REQUIRED_MODULES = frozenset({'PyInstaller', 'PySide6'})


@dataclass(frozen=True)
class BuildPreflight:
    blockers: tuple[str, ...]
    permitted: bool


def evaluate_preflight(os_name: str, python_version: tuple[int, int],
                       available_modules: frozenset[str]) -> BuildPreflight:
    """Pure contract to exercise all gating branches without pretending to build."""
    issues = []
    if os_name != 'nt':
        issues.append('not_windows')
    if python_version != (3, 12):
        issues.append('python_not_3_12')
    for module in sorted(REQUIRED_MODULES - available_modules):
        issues.append('missing_' + module.lower())
    return BuildPreflight(tuple(issues), not issues)


def current_preflight() -> BuildPreflight:
    available = frozenset(name for name in REQUIRED_MODULES
                          if importlib.util.find_spec(name) is not None)
    return evaluate_preflight(os.name, sys.version_info[:2], available)


def is_pe_executable(path: Path) -> bool:
    """Small PE header sanity check only; it does NOT verify runtime compatibility."""
    try:
        if not path.is_file() or path.stat().st_size < 64:
            return False
        with path.open('rb') as stream:
            header = stream.read(64)
            if header[:2] != b'MZ':
                return False
            offset = int.from_bytes(header[0x3c:0x40], 'little')
            if not 64 <= offset <= 2 * 1024 * 1024:
                return False
            stream.seek(offset)
            return stream.read(4) == b'PE\x00\x00'
    except OSError:
        return False


def _sanitized_environment() -> dict[str, str]:
    env = {key: val for key, val in os.environ.items()
           if not key.startswith('ANF_') and key not in {'PYTHONPATH', 'PYTHONHOME'}}
    env['ANF_AI_PROVIDER'] = 'disabled'
    env['ANF_ENV'] = 'test'
    return env


def make_report(preflight: BuildPreflight, *, built: bool = False,
                checks: dict | None = None, sha256: str | None = None) -> dict:
    return {
        'stage': 97,
        'platform': 'Windows' if os.name == 'nt' else 'non-Windows',
        'required_python': '3.12',
        'preflight_permitted': preflight.permitted,
        'blockers': list(preflight.blockers),
        'windows_exe_built': built,
        'windows_runtime_verified': bool(built and checks and all(checks.values())),
        'checks': checks or {},
        'exe_sha256': sha256,
        'network_required': False,
        'publish_executed': False,
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build(*, report_path: Path | None = None) -> tuple[int, dict]:
    preflight = current_preflight()
    if not preflight.permitted:
        result = make_report(preflight)
        if report_path:
            _write_json(report_path, result)
        return 2, result
    output = ROOT / 'dist' / 'stage97'
    work = ROOT / 'build' / 'stage97'
    exe = output / EXE_NAME
    if output.exists() or work.exists() or not SPEC.is_file():
        result = make_report(BuildPreflight(('unsafe_existing_output_or_missing_spec',), False))
        if report_path:
            _write_json(report_path, result)
        return 2, result
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(output),
           '--workpath', str(work), str(SPEC)]
    # No shell invocation, pip, external process service or network API.
    attempt = subprocess.run(cmd, cwd=ROOT, env=_sanitized_environment(),
                             capture_output=True, text=True, errors='replace', timeout=900)
    work.mkdir(parents=True, exist_ok=True)
    (work / 'build_stdout.txt').write_text(attempt.stdout, encoding='utf-8')
    (work / 'build_stderr.txt').write_text(attempt.stderr, encoding='utf-8')
    if attempt.returncode or not is_pe_executable(exe):
        result = make_report(BuildPreflight(('pyinstaller_build_or_pe_check_failed',), False))
        if report_path:
            _write_json(report_path, result)
        return 1, result
    checks = {}
    for mode, expected in (('--check', 'UI section contract OK: 12 sections'),
                           ('--gui-smoke', 'ANF GUI smoke OK: 12 sections')):
        try:
            check = subprocess.run([str(exe), mode], cwd=ROOT, env=_sanitized_environment(),
                                   capture_output=True, text=True, errors='replace', timeout=30)
            checks[mode] = check.returncode == 0 and expected in check.stdout
            (work / ('smoke_' + mode[2:] + '_stdout.txt')).write_text(check.stdout, encoding='utf-8')
            (work / ('smoke_' + mode[2:] + '_stderr.txt')).write_text(check.stderr, encoding='utf-8')
        except (OSError, subprocess.TimeoutExpired):
            checks[mode] = False
    with exe.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    result = make_report(preflight, built=True, checks=checks, sha256=digest)
    if report_path:
        _write_json(report_path, result)
    return (0 if result['windows_runtime_verified'] else 1), result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline Windows EXE build, no external connections')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args(argv)
    if args.preflight_only:
        preflight = current_preflight()
        result = make_report(preflight)
        code = 0 if preflight.permitted else 2
        if args.report:
            _write_json(args.report, result)
    else:
        code, result = build(report_path=args.report)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
