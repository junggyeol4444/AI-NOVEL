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
        from PySide6.QtCore import Qt, QStandardPaths
        from PySide6.QtTest import QTest
        from .navigation import SECTIONS
        from .app import MainWindow
        app = QApplication.instance() or QApplication([])
        QStandardPaths.setTestModeEnabled(True)
        window = MainWindow()
        window.show()
        app.processEvents()
        check('korean_font_has_real_glyphs_not_boxes', window.korean_font_supported)
        check('real_qt_window_visible_in_virtual_display', window.isVisible()
              and window.width() >= 760 and window.height() >= 500)
        check('primary_workflow_visible_and_legacy_tools_collapsed',
              window.findChild(QPushButton, 'primaryHomeButton') is not None
              and not window.sidebar.isVisible())
        first_run = output / 'ui_00_primary_home.png'
        check('render_primary_first_run_home',
              window.grab().save(str(first_run), 'PNG')
              and first_run.stat().st_size > 1024)
        check('all_twelve_navigation_entries', window.sidebar.count() == 12
              and len(SECTIONS) == 12)
        QTest.mouseClick(window.advanced_nav_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        check('user_can_expand_all_legacy_tools', window.sidebar.isVisible())
        for idx, item in enumerate(SECTIONS):
            sidebar = window.sidebar.item(idx)
            window.sidebar.scrollToItem(sidebar)
            app.processEvents()
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

        # Test the primary entry point as the actual user sees it, with
        # twelve specialist tools collapsed again.
        QTest.mouseClick(window.advanced_nav_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        check('advanced_sidebar_collapses_again', not window.sidebar.isVisible())
        # Exercise the new first-run UI on synthetic local data, not just its widget tree.
        window.sidebar.setCurrentRow(0)
        window.novel_tabs.setCurrentIndex(0)
        studio = window.studio
        check('studio_first_run_home_visible',
              studio.isVisible() and studio.pages.currentIndex() == 0
              and studio.findChild(QPushButton, 'studioNewButton') is not None)
        QTest.mouseClick(studio.findChild(QPushButton, 'studioNewButton'),
                         Qt.MouseButton.LeftButton)
        studio.new_title.setText('테스트 빛의 도시')
        studio.new_author.setText('합성 원고')
        studio.new_genre.setText('판타지')
        studio.new_subject.setPlainText('가상 도시에 들어오는 여행자')
        studio.new_premise.setPlainText('오직 새로 만든 설정만 사용')
        QTest.mouseClick(studio.findChild(QPushButton, 'studioCreateProjectButton'),
                         Qt.MouseButton.LeftButton)
        app.processEvents()
        session = window.authoring.session
        check('studio_create_click_persisted_private_sqlite',
              bool(session.project_id) and session.path.is_file()
              and studio.pages.currentIndex() == 2)
        # A user starts the first chapter with a visible GUI button, without
        # programmatic EpisodeStore writes or dialogs.
        QTest.mouseClick(studio.findChild(QPushButton, 'studioFirstEpisodeButton'),
                         Qt.MouseButton.LeftButton)
        app.processEvents()
        check('studio_click_started_first_chapter',
              session.episode_number == 1 and studio.episode_list.count() == 1
              and studio.editor.isEnabled())
        studio.editor.setPlainText('창작 원고 — 기존 작품을 복사하지 않은 합성 테스트')
        QTest.mouseClick(studio.findChild(QPushButton, 'studioSaveManuscript'),
                         Qt.MouseButton.LeftButton)
        app.processEvents()
        from ai_novel_factory.database.episodes import EpisodeStore
        from ai_novel_factory.manuscript_versions import ManuscriptVersionStore
        with EpisodeStore(session.path) as store:
            check('studio_manual_draft_saved_in_real_db',
                  store.get_episode(session.project_id, 1).draft.startswith('창작 원고'))
        with ManuscriptVersionStore(session.path) as versions:
            check('studio_append_only_manuscript_version_created',
                  len(versions.list_versions(session.project_id, 1)) == 1)
        # Exercise the actual persisted SQLite draft through the new
        # read-only Qt reader inside the compiled Windows GUI. This is
        # a stored synthetic test manuscript, NOT AI literary acceptance.
        window.novel_tabs.setCurrentIndex(2)
        app.processEvents()
        reader = window.reader
        check('private_reader_saved_sqlite_exact_draft',
              reader.body.isReadOnly()
              and reader.body.toPlainText() == '창작 원고 — 기존 작품을 복사하지 않은 합성 테스트'
              and '미승인 초고' in reader.status.text())
        old_size = reader.body.font().pointSize()
        reader.font_size.setValue(19)
        check('private_reader_user_font_size_is_view_only',
              reader.body.font().pointSize() == 19
              and old_size != reader.body.font().pointSize())
        reader.font_size.setValue(16)
        window.novel_tabs.setCurrentIndex(0)
        app.processEvents()
        snapshot = output / 'studio_real_writer_qt.png'
        check('studio_visible_writer_screenshot_captured_offscreen',
              window.grab().save(str(snapshot), 'PNG') and snapshot.stat().st_size > 1024)
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
