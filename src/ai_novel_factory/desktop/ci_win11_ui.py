"""Windows 11-specific packaged EXE Qt navigation under a virtual offscreen QPA.

This is genuine Qt widget creation, Qt click events and rendered GUI screenshots
on Windows 11. It does NOT claim physical desktop/human visual acceptance.
No files belonging to users, accounts, credentials, models or manuscripts used.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys


def run(output_dir: str) -> int:
    report = dict(real_windows11=os.name == 'nt', frozen=bool(getattr(sys, 'frozen', False)),
                  qt_rendering='OFFSCREEN_NOT_PHYSICAL_DESKTOP',
                  human_visual_review='UNVERIFIED',
                  steps=[], whole_windows11_qt_journey='FAIL')
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    def check(step: str, cond: bool):
        report['steps'].append(dict(step=step, result='PASS' if cond else 'FAIL'))
        if not cond:
            raise AssertionError(step)
    window = None
    try:
        check('windows11_packaged_exe', os.name == 'nt' and bool(getattr(sys, 'frozen', False)))
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtWidgets import QApplication, QLabel, QPushButton
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from .navigation import SECTIONS
        from .app import MainWindow
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.show()
        app.processEvents()
        check('real_qt_window_visible_in_virtual_display', window.isVisible()
              and window.width() >= 760 and window.height() >= 500)
        check('all_twelve_navigation_entries', window.sidebar.count() == 12
              and len(SECTIONS) == 12)
        for idx, item in enumerate(SECTIONS):
            sidebar = window.sidebar.item(idx)
            QTest.mouseClick(window.sidebar.viewport(), Qt.MouseButton.LeftButton,
                             pos=window.sidebar.visualItemRect(sidebar).center())
            app.processEvents()
            page = window.pages.currentWidget()
            check('sidebar_' + item.key,
                  window.pages.currentIndex() == idx
                  and page.findChild(QLabel, 'pending_' + item.key) is None)
            snap = window.grab()
            image = output / ('ui_%02d_%s.png' % (idx + 1, item.key))
            check('render_' + item.key, snap.width() > 600
                  and snap.height() > 400
                  and snap.save(str(image), 'PNG')
                  and image.stat().st_size > 1024)
        check('authoring_batch_control_accessible', window.authoring.auto_panel.start_button.isEnabled())
        check('publication_upload_disabled', not hasattr(window, 'publish_button'))
        report['whole_windows11_qt_journey'] = 'PASS'
    except BaseException as exc:
        report['blocker_type'] = type(exc).__name__
        report['blocker_step'] = report['steps'][-1]['step'] if report['steps'] else 'initialization'
    finally:
        if window is not None:
            window.close()
        (output / 'windows11_qt_report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if report['whole_windows11_qt_journey'] == 'PASS' else 1
