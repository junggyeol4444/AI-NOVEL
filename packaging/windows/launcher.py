"""PyInstaller entry point: localhost-only GUI, no implicit publishing or model calls.

Run source checks using PYTHONPATH=src python packaging/windows/launcher.py --check.
"""
from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 5 and args[0] == '--ci-authoring-journey':
        from ai_novel_factory.desktop.ci_user_journey import run
        return run(args[1:])
    if len(args) == 5 and args[0] == '--ci-reopen-project':
        from ai_novel_factory.desktop.ci_user_journey import run_reopen
        return run_reopen(args[1:])
    if len(args) == 2 and args[0] == '--ci-win11-qt-ui':
        from ai_novel_factory.desktop.ci_win11_ui import run as run_win11
        return run_win11(args[1])
    if args == ['--gui-smoke']:
        # Window creation smoke test; no event loop or external request.
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.app import MainWindow
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        try:
            assert window.sidebar.count() == 12
            assert 'API 미연결' in window.statusBar().currentMessage()
            print('ANF GUI smoke OK: 12 sections')
        finally:
            window.close()
        return 0
    from ai_novel_factory.desktop.__main__ import main as desktop_main
    original_args = sys.argv
    try:
        sys.argv = [original_args[0], *args]
        return desktop_main()
    finally:
        sys.argv = original_args


if __name__ == '__main__':
    raise SystemExit(main())
