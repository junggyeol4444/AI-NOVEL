"""Run complete disjoint unittest partitions and save verifiable results.

Use PYTHONPATH=src:tests. No external/network operations.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
modules = sorted(p.stem for p in (root / 'tests').glob('test_*.py'))
assert len(modules) == len(set(modules))
# Partition deterministically. Avoid monolithic timeout and keep stderr evidence.
prior = json.loads((root / 'docs/stage77_worktree_groups.json').read_text(encoding='utf-8'))
groups = [list(group['files']) for group in prior]
for extra in ('test_stage78_reference_similarity_checker', 'test_stage78_reference_similarity_records'):
    groups[7].append(extra)
assert set().union(*(set(g) for g in groups)) == set(modules)
assert sum(map(len, groups)) == len(modules)
results = []
for i, group in enumerate(groups, 1):
    selected = os.environ.get('STAGE78_ONLY_GROUP')
    if selected and i not in {int(x) for x in selected.split(',')}:
        continue
    command = [sys.executable, '-m', 'unittest', *group, '-q']
    env = dict(os.environ, PYTHONPATH=str(root / 'src') + os.pathsep + str(root / 'tests'))
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=root, env=env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=150)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout or ''
        stderr = (exc.stderr or b'').decode(errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr or ''
        stderr += '\nTIMEOUT\n'
        exit_code = 124
    (root / f'docs/stage78_{os.environ.get("STAGE78_PHASE", "worktree")}_group{i}_stdout.txt').write_text(stdout, encoding='utf-8')
    stderr_file = f'docs/stage78_{os.environ.get("STAGE78_PHASE", "worktree")}_group{i}_stderr.txt'
    (root / stderr_file).write_text(stderr, encoding='utf-8')
    found = re.search(r'Ran (\d+) tests?', stderr)
    skip = re.search(r'skipped=(\d+)', stderr)
    failures = re.search(r'failures=(\d+)', stderr)
    errors = re.search(r'errors=(\d+)', stderr)
    item = dict(group=i, modules=group, command=' '.join(command),
                elapsed_seconds=round(time.monotonic() - started, 2),
                exit_code=exit_code, total=int(found.group(1)) if found else None,
                skipped=int(skip.group(1)) if skip else 0,
                failures=int(failures.group(1)) if failures else 0,
                errors=int(errors.group(1)) if errors else 0,
                stderr_file=stderr_file)
    results.append(item)
    print(f'group {i}/8: {item["total"]} tests, {item["skipped"]} skipped, exit={exit_code}', flush=True)
phase = os.environ.get('STAGE78_PHASE', 'worktree')
(root / ('docs/stage78_' + phase + '_groups' + ('' if not os.environ.get('STAGE78_ONLY_GROUP') else '_' + os.environ['STAGE78_ONLY_GROUP'].replace(',', '_')) + '.json')).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
if not all(r['exit_code'] == 0 and r['total'] is not None for r in results):
    sys.exit(1)
print('PARTIAL' if os.environ.get('STAGE78_ONLY_GROUP') else 'SUMMARY', json.dumps(dict(total=sum(r['total'] for r in results),
                                 skipped=sum(r['skipped'] for r in results),
                                 passed=sum(r['total'] - r['skipped'] for r in results),
                                 modules=len(modules) if not os.environ.get('STAGE78_ONLY_GROUP') else sum(len(r['modules']) for r in results), groups=len(results))), flush=True)
