"""Run with: python -m ai_novel_factory.desktop [--check]."""
from __future__ import annotations
import sys
from .navigation import SECTIONS

def main() -> int:
    if sys.argv[1:] == ['--check']:
        print(f'UI section contract OK: {len(SECTIONS)} sections')
        return 0
    if len(sys.argv) > 1:
        print('Usage: python -m ai_novel_factory.desktop [--check]', file=sys.stderr)
        return 2
    try:
        from .app import run
    except ImportError as exc:
        if exc.name and (exc.name == 'PySide6' or exc.name.startswith('PySide6.')):
            print('PySide6가 설치되지 않았습니다. desktop 선택 의존성이 필요합니다.', file=sys.stderr)
            return 3
        raise
    return run()

if __name__ == '__main__':
    raise SystemExit(main())
