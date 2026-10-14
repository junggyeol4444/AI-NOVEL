"""Stage 99: local Windows execution + comprehensive regression evidence.

No network, cloud, app installation, account connection, publication or user-PC
access. Source-only execution on Linux must NEVER count as a Windows test.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / 'dist' / 'stage97' / 'AI_Novel_Factory.exe'
GROUP_DRIVER = ROOT / 'scripts' / 'stage99_partitioned_regression.py'
CHECKS = {'--check': 'UI section contract OK: 12 sections',
          '--gui-smoke': 'ANF GUI smoke OK: 12 sections'}


def is_pe_file(path: Path) -> bool:
    """Quick header sanity check, not a substitute for execution on Windows."""
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size < 64:
            return False
        with path.open('rb') as stream:
            head = stream.read(64)
            if head[:2] != b'MZ':
                return False
            offset = int.from_bytes(head[60:64], 'little')
            if offset < 64 or offset > 2_097_152:
                return False
            stream.seek(offset)
            return stream.read(4) == b'PE\x00\x00'
    except (OSError, ValueError):
        return False


def assess(*, os_name: str, python_version: tuple[int, int], exe_exists: bool,
           pe_valid: bool, smoke: dict | None = None,
           regression: dict | None = None) -> dict:
    """Pure, conservative assessment of *recorded* checks, never fabricated runs.

    No `force_pass`, platform override CLI, or user-provided fake result accepted.
    This pure function is for unit tests; CLI obtains facts directly from the OS.
    """
    windows = os_name == 'nt'
    python_ok = python_version == (3, 12)
    ready = windows and python_ok and exe_exists and pe_valid
    checks = smoke or {}
    exe_ok = ready and all(checks.get(k) is True for k in CHECKS)
    details = regression or {}
    regression_ok = (ready and details.get('module_coverage_exact') is True
                     and details.get('all_exit_codes_zero') is True
                     and type(details.get('total')) is int and details['total'] > 0
                     and type(details.get('passed')) is int
                     and type(details.get('skipped')) is int
                     and details['total'] == details['passed'] + details['skipped']
                     and details.get('failures') == 0 and details.get('errors') == 0
                     and details.get('group_count') == 8)
    # Do not allow a failed/short/unknown smoke or missing report to become a pass.
    windows_regression = 'PASS' if regression_ok else ('FAIL' if windows and regression else 'UNVERIFIED')
    runtime = 'PASS' if exe_ok else ('FAIL' if ready and smoke else 'UNVERIFIED')
    return {
        'stage': 99,
        'requirement': 'ANF-REQ-071',
        'environment': 'Windows' if windows else 'non-Windows',
        'python_312': python_ok,
        'windows_exe_present': bool(exe_exists),
        'pe_header_valid': bool(pe_valid),
        'windows_exe_runtime': runtime,
        'windows_comprehensive_regression': windows_regression,
        'windows_acceptance_met': bool(exe_ok and regression_ok),
        'physical_display_user_review': 'UNVERIFIED',
        'local_llm_inference': 'UNVERIFIED',
        'postgres_pgvector_and_redis_celery': 'UNVERIFIED',
        'official_platform_api_upload': 'UNVERIFIED',
        'network_used': False,
        'publication_executed': False,
        'user_pc_accessed': False,
        'report_is_not_a_release_approval': True,
    }


def safe_write_report(path: Path, report: dict) -> None:
    # Files must be intentionally directed to existing local folders.
    if path.is_symlink() or path.exists() or not path.parent.is_dir() or path.suffix.lower() != '.json':
        raise ValueError('report_path_unsafe_or_exists')
    data = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    with path.open('x', encoding='utf-8') as out:
        out.write(data)


def safe_environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('ANF_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
    env['ANF_AI_PROVIDER'] = 'disabled'
    env['ANF_ENV'] = 'test'
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src'), str(ROOT / 'tests')))
    return env


def execute_check(command: list[str], *, timeout: int) -> tuple[bool, int | str, str, str]:
    try:
        completed = subprocess.run(command, cwd=ROOT, env=safe_environment(),
                                   capture_output=True, text=True, errors='replace', timeout=timeout)
        # Keep output transient; reports contain only booleans/exit codes, no manuscript.
        return completed.returncode == 0, completed.returncode, completed.stdout, completed.stderr
    except (OSError, subprocess.TimeoutExpired):
        return False, 'ERROR_OR_TIMEOUT', '', ''


def run(*, preflight_only: bool = False) -> tuple[int, dict]:
    os_name, version = os.name, sys.version_info[:2]
    exists = EXE.is_file() and not EXE.is_symlink()
    valid = is_pe_file(EXE) if exists else False
    smoke: dict[str, bool] = {}
    regression: dict | None = None
    exits: dict[str, int | str] = {}
    prerequisites = os_name == 'nt' and version == (3, 12) and exists and valid
    if prerequisites and not preflight_only:
        digest = sha256(EXE.read_bytes()).hexdigest()
        for mode, token in CHECKS.items():
            ok, code, out, _ = execute_check([str(EXE), mode], timeout=45)
            smoke[mode] = bool(ok and token in out)
            exits[mode] = code
        if all(smoke.values()):
            out_base = ROOT / 'build' / 'stage99'
            # Do not replace evidence from a previous execution.
            if not out_base.exists():
                out_base.mkdir(parents=True)
                prefix = out_base / 'windows_regression'
                ok, code, _, _ = execute_check([sys.executable, str(GROUP_DRIVER),
                                                  '--prefix', str(prefix)], timeout=1800)
                exits['regression_driver'] = code
                if ok:
                    aggregated, agg_code, _, _ = execute_check([sys.executable, str(GROUP_DRIVER),
                        '--prefix', str(prefix), '--aggregate'], timeout=30)
                    exits['regression_aggregate'] = agg_code
                    p = out_base / 'windows_regression_groups.json'
                    if aggregated and p.is_file():
                        try:
                            regression = json.loads(p.read_text('utf-8'))
                        except (OSError, ValueError):
                            pass
            else:
                exits['regression_driver'] = 'EXISTING_REPORT_DIRECTORY'
    report = assess(os_name=os_name, python_version=version,
                    exe_exists=exists, pe_valid=valid, smoke=smoke, regression=regression)
    report['mode'] = 'preflight_only' if preflight_only else 'automated_windows_checks'
    report['os_release'] = platform.system()  # no user paths or device IDs
    report['python_version'] = '.'.join(map(str, version))
    report['exe_sha256'] = digest if prerequisites and not preflight_only else None
    report['command_exit_codes'] = exits
    report['smoke_checks'] = smoke
    if regression:
        report['regression_summary'] = {k: regression.get(k) for k in
            ('module_count','group_count','module_coverage_exact','total','passed',
             'skipped','failures','errors','all_exit_codes_zero')}
    if not prerequisites:
        report['blockers'] = ([s for condition, s in ((os_name != 'nt', 'not_windows'),
                                 (version != (3,12),'python_not_3_12'),
                                 (not exists, 'exe_missing'),
                                 (exists and not valid, 'pe_invalid')) if condition])
    else:
        report['blockers'] = []
    return (0 if report['windows_acceptance_met'] else 2), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline stage99 real Windows evidence only')
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    code, report = run(preflight_only=args.preflight_only)
    if args.report:
        try:
            safe_write_report(args.report, report)
        except (ValueError, OSError):
            print('report_not_written', file=sys.stderr)
            return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
