"""Stage 98: read-only local setup readiness. No downloads, installs, secrets or sockets.

A report describes THIS interpreter, not the user's Windows computer.
This script does not load .env files or inspect the ambient ANF_ environment.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from ai_novel_factory.settings import load_settings, ConfigurationError

MODULES = ('PySide6', 'PyInstaller', 'PIL')


def assess(platform_name: str, py: tuple[int, int], installed: Mapping[str, bool],
           *, claimed_user_approval: bool = False) -> dict:
    """Pure capability *evidence*: approval claims cannot grant publishing rights."""
    win = platform_name == 'Windows'
    py312 = py == (3, 12)
    gui = bool(installed.get('PySide6', False))
    build_tool = bool(installed.get('PyInstaller', False))
    graphics = bool(installed.get('PIL', False))
    return {
        'stage': 98,
        'scope': 'local_read_only_setup_diagnostics',
        'observed_environment': 'Windows' if win else 'non-Windows',
        'source_python_3_12_compatible_target': py312,
        'windows_target_present': win,
        'local_gui_module_available': gui,
        'windows_build_tool_available': build_tool,
        'optional_graphics_module_available': graphics,
        'windows_build_preflight_possible': bool(win and py312 and gui and build_tool),
        'installed_windows_exe_verified': False,
        'gui_runtime_verified': False,
        'user_pc_inspected': False,
        'local_model_inference_verified': False,
        'postgres_pgvector_runtime_verified': False,
        'redis_celery_runtime_verified': False,
        'external_service_connection': 'DISABLED',
        'cloud_ai_connection': 'DISABLED',
        'official_platform_upload_verified': False,
        'platform_publishing_executed': False,
        'installer_executed': False,
        'network_used': False,
        'user_approval_authenticated': False,
        'stage95_official_api_acceptance_met': False,
        'stage96_official_upload_compatibility_verified': False,
        'stage97_windows_exe_acceptance_met': False,
    }


def check_config(values: Mapping[str, str] | None = None) -> dict:
    """Only validate explicitly provided values; NEVER echo them or error text."""
    try:
        status = load_settings(environ={} if values is None else values).safe_status()
    except (ConfigurationError, ValueError, TypeError):
        return {'valid': False, 'reason': 'invalid_or_disallowed_offline_settings'}
    return {
        'valid': True,
        'api_loopback_only': status['api_host'] in {'127.0.0.1', 'localhost', '::1'},
        'remote_services_configured': False,
        'cloud_provider_configured': False,
    }


def current_report() -> dict:
    modules = {name: importlib.util.find_spec(name) is not None for name in MODULES}
    report = assess('Windows' if os.name == 'nt' else 'non-Windows',
                    sys.version_info[:2], modules)
    report['default_configuration'] = check_config()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only local setup guide diagnostic; no installation')
    parser.add_argument('--report', type=Path, help='Save sanitized JSON only if destination does not exist')
    args = parser.parse_args(argv)
    report = current_report()
    if args.report:
        # No secrets or full paths are contained in the report. Never overwrite user files.
        try:
            with args.report.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        except (OSError, ValueError):
            print('FAIL: report_destination_unavailable', file=sys.stderr)
            return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
