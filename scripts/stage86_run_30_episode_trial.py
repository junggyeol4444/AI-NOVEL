"""Offline stage 86 integration report: python scripts/stage86_run_30_episode_trial.py --output PATH"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from ai_novel_factory.thirty_episode_trial import run_30_episode_trial


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--blocked-episode', type=int, default=None,
                        help='Simulate a preliminary-check rejection (testing only)')
    args = parser.parse_args()
    output = Path(args.output)
    if output.is_symlink() or not output.parent.is_dir():
        parser.error('output must have an existing directory and must not be a symlink')
    report = run_30_episode_trial(blocked_episode=args.blocked_episode)
    data = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    temp = output.with_name(output.name + '.tmp')
    if temp.is_symlink():
        parser.error('unsafe temporary output path')
    try:
        with temp.open('x', encoding='utf-8') as handle:
            handle.write(data)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    print(f"stage86 attempted={report['attempted_episodes']} saved={report['successful_drafts']} "
          f"errors={report['error_count']} passed={report['passed']}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
