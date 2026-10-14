"""Stage 95 reproducible offline unittest groups, independently resumable.

Examples:
  python scripts/stage95_partitioned_regression.py --prefix docs/stage95_candidate --start 1 --end 4
  python scripts/stage95_partitioned_regression.py --prefix docs/stage95_candidate --start 5 --end 8
  python scripts/stage95_partitioned_regression.py --prefix docs/stage95_candidate --aggregate
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--prefix', required=True)
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--end', type=int, default=8)
    p.add_argument('--aggregate', action='store_true')
    a = p.parse_args()
    root = Path(__file__).resolve().parent.parent
    prefix = Path(a.prefix)
    if not prefix.is_absolute():
        prefix = root / prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    files = sorted((root / 'tests').glob('test_*.py'))
    groups = [files[i::8] for i in range(8)]
    if not files or not (1 <= a.start <= a.end <= 8):
        raise SystemExit('invalid test partition')
    assert len(files) == len(set(files)) == sum(map(len, groups))
    results = []
    for i, group in enumerate(groups, 1):
        if not a.aggregate and not a.start <= i <= a.end:
            continue
        out = Path(f'{prefix}_group{i}_stdout.txt')
        err = Path(f'{prefix}_group{i}_stderr.txt')
        if not a.aggregate:
            env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root / 'src'), str(root / 'tests'))))
            cmd = [sys.executable, '-m', 'unittest', '-q', *(f.stem for f in group)]
            try:
                completed = subprocess.run(cmd, cwd=root, env=env, capture_output=True,
                                           text=True, errors='replace', timeout=180)
                stdout, stderr, status = completed.stdout, completed.stderr, completed.returncode
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode(errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout or ''
                stderr = exc.stderr.decode(errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr or ''
                stderr += '\nTIMEOUT\n'
                status = 124
            out.write_text(stdout, encoding='utf-8')
            err.write_text(stderr, encoding='utf-8')
            Path(f'{prefix}_group{i}_exit.txt').write_text(str(status)+'\n', encoding='utf-8')
        if not err.exists() or not Path(f'{prefix}_group{i}_exit.txt').exists():
            raise SystemExit(f'group {i} logs/exit code missing')
        stderr = err.read_text(encoding='utf-8')
        code = int(Path(f'{prefix}_group{i}_exit.txt').read_text().strip())
        match = re.search(r'Ran (\d+) tests?', stderr)
        skip = re.search(r'skipped=(\d+)', stderr)
        total = int(match.group(1)) if match else 0
        skipped = int(skip.group(1)) if skip else 0
        ok = code == 0 and bool(match and re.search(r'\bOK\b', stderr)) and 'FAILED (' not in stderr
        item = dict(group=i, modules=[f.stem for f in group],
                    command=[sys.executable, '-m', 'unittest', '-q', *(f.stem for f in group)],
                    total=total, passed=total-skipped if ok else None, skipped=skipped,
                    exit_code=code, success=ok, stdout_file=str(out), stderr_file=str(err))
        results.append(item)
        print(f'group {i}: total={total}, skipped={skipped}, exit={code}, ok={ok}', flush=True)
        if not ok:
            return 1
    if a.aggregate:
        if len(results) != 8 or sum(len(r['modules']) for r in results) != len(files):
            return 1
        report = dict(stage=95, requirement='ANF-REQ-066', module_count=len(files),
                      group_count=8, module_coverage_exact=True,
                      total=sum(r['total'] for r in results),
                      passed=sum(r['passed'] for r in results),
                      skipped=sum(r['skipped'] for r in results), failures=0, errors=0,
                      all_exit_codes_zero=True, groups_detail=results)
        Path(f'{prefix}_groups.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('TOTAL', report['total'], 'PASSED', report['passed'], 'SKIPPED', report['skipped'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
