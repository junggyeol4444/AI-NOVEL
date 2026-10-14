"""Reproducible stage-80 full-suite regression with disjoint unittest modules.

Usage: python scripts/stage80_partitioned_regression.py --prefix docs/stage80_worktree
Each group has a separate subprocess and writes its exact stdout/stderr.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--groups', type=int, default=8)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    prefix = Path(args.prefix)
    if not prefix.is_absolute():
        prefix = root / prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    files = sorted((root / 'tests').glob('test_*.py'))
    if not files or args.groups < 1 or args.groups > len(files):
        raise SystemExit('invalid module partition')
    groups = [files[i::args.groups] for i in range(args.groups)]
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join([str(root / 'src'), str(root / 'tests')])
    results = []
    for number, group in enumerate(groups, 1):
        modules = [p.stem for p in group]
        command = [sys.executable, '-m', 'unittest', *modules, '-q']
        run = subprocess.run(command, cwd=root, env=env, capture_output=True,
                             text=True, errors='replace', timeout=180)
        out_file = Path(f'{prefix}_group{number}_stdout.txt')
        err_file = Path(f'{prefix}_group{number}_stderr.txt')
        out_file.write_text(run.stdout, encoding='utf-8')
        err_file.write_text(run.stderr, encoding='utf-8')
        found = re.search(r'Ran (\d+) tests? in ', run.stderr)
        skipped = re.search(r'skipped=(\d+)', run.stderr)
        total = int(found.group(1)) if found else 0
        skipped_count = int(skipped.group(1)) if skipped else 0
        success = run.returncode == 0 and found is not None and re.search(r'\bOK\b', run.stderr) is not None
        entry = {
            'group': number, 'modules': modules, 'command': command,
            'total': total, 'passed': total - skipped_count if success else None,
            'skipped': skipped_count, 'exit_code': run.returncode,
            'success': bool(success),
            'stdout_file': str(out_file.relative_to(root)) if out_file.is_relative_to(root) else str(out_file),
            'stderr_file': str(err_file.relative_to(root)) if err_file.is_relative_to(root) else str(err_file),
        }
        results.append(entry)
        print(f'group {number}/{len(groups)}: tests={total}, skipped={skipped_count}, ok={success}', flush=True)
        if not success:
            break
    report = {
        'modules': len(files), 'covered_modules': sum(len(g['modules']) for g in results),
        'groups': len(results), 'total': sum(g['total'] for g in results),
        'passed': sum(g['passed'] or 0 for g in results),
        'skipped': sum(g['skipped'] for g in results),
        'all_success': len(results) == len(groups) and all(g['success'] for g in results),
        'group_results': results,
    }
    Path(f'{prefix}_groups.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'group_results'}, ensure_ascii=False), flush=True)
    return 0 if report['all_success'] and report['covered_modules'] == len(files) else 1


if __name__ == '__main__':
    raise SystemExit(main())
