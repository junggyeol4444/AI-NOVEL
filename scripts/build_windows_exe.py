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


def _run_logged(cmd: list[str], *, cwd: Path, env: dict[str, str],
                stdout_path: Path, stderr_path: Path, timeout: int | float) -> int:
    """Capture subprocess output in unique files instead of inherited pipes.

    A one-file Windows GUI EXE starts a bootloader child. If the parent times
    out, that child can retain inherited stdout/stderr pipe handles and make
    subprocess.run(capture_output=True) block indefinitely during cleanup.
    File redirection has no pipe EOF wait; no existing log is overwritten.
    """
    with stdout_path.open('xb') as out, stderr_path.open('xb') as err:
        return subprocess.run(
            cmd, cwd=cwd, env=env, stdout=out, stderr=err, timeout=timeout,
        ).returncode


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
    # Report a bounded failure instead of hanging forever behind a one-file
    # PyInstaller bootloader descendant holding a capture pipe open.
    work.mkdir(parents=True, exist_ok=True)
    print('ANF_WINDOWS_BUILD_STEP pyinstaller_start', flush=True)
    try:
        build_code = _run_logged(
            cmd, cwd=ROOT, env=_sanitized_environment(),
            stdout_path=work / 'build_stdout.txt',
            stderr_path=work / 'build_stderr.txt', timeout=900)
    except subprocess.TimeoutExpired:
        result = make_report(BuildPreflight(('pyinstaller_timed_out',), False))
        if report_path:
            _write_json(report_path, result)
        print('ANF_WINDOWS_BUILD_STEP pyinstaller_timeout', flush=True)
        return 1, result
    print('ANF_WINDOWS_BUILD_STEP pyinstaller_finished', flush=True)
    if build_code or not is_pe_executable(exe):
        result = make_report(BuildPreflight(('pyinstaller_build_or_pe_check_failed',), False))
        if report_path:
            _write_json(report_path, result)
        return 1, result
    checks = {}
    for mode, expected in (('--check', 'UI section contract OK: 12 sections'),
                           ('--gui-smoke', 'ANF GUI smoke OK: 12 sections')):
        stdout_path = work / ('smoke_' + mode[2:] + '_stdout.txt')
        stderr_path = work / ('smoke_' + mode[2:] + '_stderr.txt')
        print('ANF_WINDOWS_BUILD_STEP smoke_' + mode[2:] + '_start', flush=True)
        try:
            smoke_code = _run_logged(
                [str(exe), mode], cwd=ROOT, env=_sanitized_environment(),
                stdout_path=stdout_path, stderr_path=stderr_path, timeout=30)
            smoke_output = stdout_path.read_text(encoding='utf-8', errors='replace')
            checks[mode] = smoke_code == 0 and expected in smoke_output
        except (OSError, subprocess.TimeoutExpired):
            checks[mode] = False
        print('ANF_WINDOWS_BUILD_STEP smoke_' + mode[2:] + '_finished', flush=True)
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
