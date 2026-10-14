"""TEST-BRANCH ONLY: drive real Qt widgets inside the compiled Windows EXE.

Synthetic original inputs only. This is binary-internal Qt click automation, NOT
external Windows UIAutomation and NOT a human-PC visual acceptance test.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys

def run(args):
    report = {'compiled_exe_qt_clicks': True, 'windows': os.name == 'nt',
              'test_data': 'synthetic_original', 'model': 'local_cpu_weights',
              'publishing': False, 'user_account': False, 'steps': [],
              'whole_user_journey': 'FAIL', 'human_visual_review': 'UNVERIFIED'}
    output = Path(args[3]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    def check(name, condition):
        report['steps'].append({'step': name, 'result': 'PASS' if condition else 'FAIL'})
        if not condition:
            raise AssertionError(name)
    try:
        check('real_windows_exe', os.name == 'nt' and getattr(sys, 'frozen', False))
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.database.episodes import EpisodeStore
        from ai_novel_factory.desktop.app import MainWindow
        from ai_novel_factory.epub3 import verify_epub
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.show()
        app.processEvents()
        check('gui_window_created', window.isVisible())
        item = window.sidebar.item(0)
        QTest.mouseClick(window.sidebar.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.sidebar.visualItemRect(item).center())
        check('novels_navigation', window.pages.currentIndex() == 0)
        ui = window.authoring
        db_path = output / 'synthetic_novel.db'
        ui._set('db', str(db_path))
        ui._set('title', '가상 등불 여행')
        ui._set('author', '합성 테스트 작가')
        ui._set('premise', '완전히 가상의 산악 마을에서 등불을 찾는 이야기')
        QTest.mouseClick(ui.buttons['create'], Qt.MouseButton.LeftButton)
        check('create_project_via_compiled_gui', db_path.is_file() and ui.session.project_id is not None)
        pid = ui.session.project_id
        ui._set('bible', '가상 마을의 길은 밤에만 열린다')
        QTest.mouseClick(ui.buttons['save_bible'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_path) as db:
            check('bible_persisted', db.get_rule(pid, 'premise').value == '가상 마을의 길은 밤에만 열린다')
        ui._set('plot', '여행자가 북쪽 문을 발견하고 등불을 찾아 떠난다')
        ui.number.setValue(1)
        QTest.mouseClick(ui.buttons['create_episode'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_path) as db:
            check('episode_persisted', db.get_episode(pid, 1).plot.startswith('여행자가'))
        QTest.mouseClick(ui.buttons['add_scene'], Qt.MouseButton.LeftButton)
        ui._set('scene', '가상 산길에서 안개와 마주한다')
        QTest.mouseClick(ui.buttons['save_scene'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_path) as db:
            scenes = db.list_scenes(pid, 1)
            check('scene_persisted', len(scenes) == 1 and scenes[0].text.startswith('가상 산길'))
        ui._set('executable', str(Path(args[0]).resolve()))
        ui._set('arguments', '"' + str(Path(args[2]).resolve()) + '" --child "' + str(Path(args[1]).resolve()) + '"')
        ui._set('goal', '등불 찾기')
        ui._set('conflict', '문이 잠겨 있다')
        ui._set('location', '가상의 산길')
        ui._set('characters', '여행자')
        ui.approved.setChecked(True)
        QTest.mouseClick(ui.buttons['generate'], Qt.MouseButton.LeftButton)
        draft = ui._text('draft')
        check('local_cpu_model_via_gui', bool(draft.strip()) and ui.session.pending_draft == draft)
        with EpisodeStore(db_path) as db:
            check('preview_not_implicitly_saved', db.get_episode(pid, 1).draft == '')
        QTest.mouseClick(ui.buttons['save_draft'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_path) as db:
            check('generated_draft_saved', db.get_episode(pid, 1).draft == draft)
        ui._set('export_dir', str(output))
        ui._set('price', '0')
        QTest.mouseClick(ui.buttons['export'], Qt.MouseButton.LeftButton)
        txt, epub = output / 'draft.txt', output / 'book.epub'
        check('txt_export_content', txt.is_file() and draft in txt.read_text(encoding='utf-8'))
        check('epub_export_verified', epub.is_file() and verify_epub(epub, expected_chapters=1).valid)
        check('no_publication', not hasattr(ui, 'publish_button'))
        report['draft_sha256'] = hashlib.sha256(draft.encode('utf-8')).hexdigest()
        report['whole_user_journey'] = 'PASS'
        window.close()
    except BaseException as exc:
        report['blocker_type'] = type(exc).__name__
        report['blocker_step'] = report['steps'][-1]['step'] if report['steps'] else 'initialization'
    finally:
        (output / 'compiled_exe_user_journey.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if report['whole_user_journey'] == 'PASS' else 1
