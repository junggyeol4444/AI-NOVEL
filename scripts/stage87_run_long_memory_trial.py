"""Stage 87: deterministic 120-episode offline memory stability report."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from ai_novel_factory.long_memory_stability_trial import run_120_episode_memory_trial


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--conflict-episode', type=int, default=None,
                   help='Inject synthetic conflicting canon assertion (test only)')
    a = p.parse_args()
    path = Path(a.output)
    if path.is_symlink() or not path.parent.is_dir() or path.is_dir():
        p.error('output must be a safe local file in an existing directory')
    result = run_120_episode_memory_trial(conflict_episode=a.conflict_episode)
    temp = path.with_name(path.name + '.tmp')
    if temp.is_symlink():
        p.error('unsafe temporary output path')
    try:
        with temp.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    print(f"stage87 attempted={result['attempted_episodes']} drafts={result['successful_drafts']} "
          f"canon_conflicts={result['explicit_canon_conflict_count']} "
          f"retrieval_failures={result['memory_retrieval_failures']} "
          f"passed={result['passed']}")
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
