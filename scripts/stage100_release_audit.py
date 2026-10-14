"""Stage 100 release-documentation acceptance audit (offline, read-only inputs).

Not an authorization or publisher: no build, network, installation, upload or user
approval. Even with all supporting reports, only human review can authorize a
release. Input reports can be edited; their provenance needs human verification.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = {
    '95_official_api': ('docs/stage95_continuation_test_results.json',
                        ('official_api_spec_verified', 'official_sandbox_upload_verified')),
    '96_platform_rules': ('docs/stage96_test_results.json',
                          ('official_platform_specification_verified', 'official_platform_upload_tested')),
    '97_windows_exe': ('docs/stage97_test_results.json',
                       ('windows_exe_built', 'windows_exe_executed')),
    '98_install_guide': ('docs/stage98_test_results.json',
                         ('acceptance_documentation_and_diagnostic',)),
    '99_windows_acceptance': ('docs/stage99_test_results.json',
                              ('windows_acceptance_met', 'windows_exe_actual_runtime',
                               'windows_real_comprehensive_regression', 'physical_gui')),
}
REQUIRED_DOCUMENTS = (
    'docs/requirements.md', 'docs/stage98_installation_and_connection_guide.md',
    'docs/stage99_windows_integrated_regression.md',
    'docs/stage100_user_manual.md', 'docs/stage100_release_and_acceptance.md',
)
RELEASE_COMPONENTS = (
    'README.md', 'pyproject.toml', '.env.example', '.gitignore',
    'scripts/build_windows_exe.py', 'scripts/stage99_windows_acceptance.py',
    'scripts/stage100_release_audit.py', 'docs/requirements.md',
    'docs/stage100_user_manual.md', 'docs/stage100_release_and_acceptance.md',
    'docs/stage95_continuation_test_results.json', 'docs/stage96_test_results.json',
    'docs/stage97_test_results.json', 'docs/stage98_test_results.json',
    'docs/stage99_test_results.json',
)


def _json_file(root: Path, relative: str) -> dict | None:
    target = root / relative
    try:
        if target.is_symlink() or not target.is_file() or target.stat().st_size > 2_000_000:
            return None
        obj = json.loads(target.read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def assess_evidence(reports: dict[str, dict | None], *, os_name: str) -> dict:
    """Only assesses recorded claims, never certifies authenticity or user sign-off."""
    checks: dict[str, dict] = {}
    for name in EVIDENCE:
        data = reports.get(name)
        if not isinstance(data, dict):
            checks[name] = {'status': 'UNVERIFIED', 'reason': 'missing_or_invalid_evidence'}
            continue
        if name == '95_official_api':
            valid = data.get('official_api_spec_verified') is True and data.get('official_sandbox_upload_verified') is True
        elif name == '96_platform_rules':
            valid = data.get('official_platform_specification_verified') is True and data.get('official_platform_upload_tested') is True
        elif name == '97_windows_exe':
            valid = data.get('windows_exe_built') is True and data.get('windows_exe_executed') is True
        elif name == '98_install_guide':
            valid = data.get('acceptance_documentation_and_diagnostic') == 'IMPLEMENTED_LOCAL_ONLY'
        else:
            valid = (data.get('windows_acceptance_met') is True
                     and data.get('windows_exe_actual_runtime') == 'PASS'
                     and data.get('windows_real_comprehensive_regression') == 'PASS'
                     and data.get('physical_gui') == 'PASS')
        if name in ('97_windows_exe', '99_windows_acceptance') and os_name != 'nt':
            valid = False  # Never certify Windows checks from a Linux run.
        checks[name] = {'status': 'REPORTED_PASS' if valid else 'UNVERIFIED',
                        'reason': 'self_report_untrusted_until_review' if valid else 'acceptance_evidence_incomplete'}
    return checks


def inventory(root: Path) -> dict:
    """Content digests of a stable subset; not a signature or self-hashing ZIP."""
    items: dict[str, dict] = {}
    for relative in RELEASE_COMPONENTS:
        target = root / relative
        if target.is_symlink() or not target.is_file():
            items[relative] = {'present': False}
            continue
        data = target.read_bytes()
        items[relative] = {'present': True, 'bytes': len(data), 'sha256': sha256(data).hexdigest()}
    return {'format': 1, 'scope': 'selected_source_components_not_a_zip_signature',
            'files': items, 'all_present': all(x.get('present') for x in items.values())}


def audit(root: Path = ROOT, *, os_name: str | None = None) -> dict:
    root = Path(root)
    host = os.name if os_name is None else os_name
    reports = {key: _json_file(root, relative) for key, (relative, _) in EVIDENCE.items()}
    checks = assess_evidence(reports, os_name=host)
    docs = {name: (root / name).is_file() and not (root / name).is_symlink()
            for name in REQUIRED_DOCUMENTS}
    source_inventory = inventory(root)
    blockers = [name for name, value in checks.items() if value['status'] != 'REPORTED_PASS']
    blockers += ['missing_document:' + name for name, present in docs.items() if not present]
    if not source_inventory['all_present']:
        blockers.append('missing_release_component')
    if host != 'nt':
        blockers.append('host_not_windows')
    return {
        'stage': 100, 'requirement': 'ANF-REQ-072',
        'scope': 'release_documentation_and_acceptance_criteria',
        'original_plan_txt_verified': False,
        'host': 'Windows' if host == 'nt' else 'non-Windows',
        'documentation_checks': docs, 'evidence_checks': checks,
        'release_inventory': source_inventory,
        'blocking_items': blockers,
        'release_status': 'BLOCKED' if blockers else 'PENDING_MANUAL_SIGNOFF',
        'ready_for_public_release': False,  # never grant acceptance automatically
        'user_acceptance_automatically_granted': False,
        'official_platform_upload_performed': False,
        'actual_windows_build_performed_by_audit': False,
        'network_or_installation_performed': False,
        'important_note': 'Previous reports are self-reported data. Review on actual Windows and obtain human sign-off; this is NOT a release approval.',
    }


def write_report(path: Path, content: dict) -> None:
    """Fail closed; never overwrite an existing report or follow a symlink."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    with path.open('xb') as fp:
        fp.write(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline source release evidence audit (never authorizes release)')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    result = audit(args.root)
    if args.report is not None:
        try:
            write_report(args.report, result)
        except FileExistsError:
            print('Refusing to overwrite existing report', file=sys.stderr)
            return 2
    print(json.dumps({key: val for key, val in result.items() if key != 'release_inventory'},
                     ensure_ascii=False, sort_keys=True))
    return 0 if result['release_status'] == 'PENDING_MANUAL_SIGNOFF' else 2


if __name__ == '__main__':
    raise SystemExit(main())
