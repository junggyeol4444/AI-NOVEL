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
        QTest.mouseClick(window.advanced_nav_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        check('advanced_tools_expanded_explicitly', window.sidebar.isVisible())
        window.novel_tabs.setCurrentIndex(1)  # explicit existing tools in the new studio
        app.processEvents()
        ui = window.authoring
        db_path = output / 'synthetic_novel.db'
        ui._set('db', str(db_path))
        ui._set('title', '가상 등불 여행')
        ui._set('author', '합성 테스트 작가')
        ui._set('premise', '완전히 가상의 산악 마을에서 등불을 찾는 이야기')
        for key, value in (
                ('genre', 'fantasy'), ('subject', 'original lantern adventure'),
                ('target_episodes', '250'), ('characters_per_episode', '5000'),
                ('mood', 'suspense')):
            ui._set(key, value)
        QTest.mouseClick(ui.buttons['create'], Qt.MouseButton.LeftButton)
        check('create_project_via_compiled_gui', db_path.is_file() and ui.session.project_id is not None)
        pid = ui.session.project_id
        with EpisodeStore(db_path) as db:
            metadata = {r.key: r.value for r in db.list_rules(pid)}
            check('original_planning_inputs_saved',
                  all(metadata.get(k) == v for k, v in (
                      ('genre', 'fantasy'), ('subject', 'original lantern adventure'),
                      ('target_episodes', '250'), ('characters_per_episode', '5000'),
                      ('mood', 'suspense'))))
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
        ui._set('final_text', draft + '\n[사용자 검수 완료: 합성 테스트 원고]')
        QTest.mouseClick(ui.buttons['save_final'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_path) as db:
            check('reviewed_final_requires_explicit_user_acknowledgements',
                  db.get_episode(pid, 1).final_text == '')
        ui.final_reviewed.setChecked(True)
        ui.final_quality_ack.setChecked(True)
        QTest.mouseClick(ui.buttons['save_final'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_path) as db:
            check('human_reviewed_final_written_via_gui_not_auto_approved',
                  db.get_episode(pid, 1).final_text.endswith('합성 테스트 원고]')
                  and not ui.final_reviewed.isChecked()
                  and not ui.final_quality_ack.isChecked())
        ui._set('export_dir', str(output))
        ui._set('price', '0')
        QTest.mouseClick(ui.buttons['export'], Qt.MouseButton.LeftButton)
        txt, epub = output / 'draft.txt', output / 'book.epub'
        check('txt_export_content', txt.is_file() and draft in txt.read_text(encoding='utf-8'))
        check('epub_export_verified', epub.is_file() and verify_epub(epub, expected_chapters=1).valid)
        # Use the six real sidebar editors, not direct backend CRUD calls.
        from ai_novel_factory.desktop.navigation import SECTIONS
        from ai_novel_factory.database.characters import CharacterStore
        from ai_novel_factory.database.world_canon import WorldCanonStore
        from ai_novel_factory.database.event_timeline import EventTimelineStore
        from ai_novel_factory.database.relationships import RelationshipStore
        from ai_novel_factory.database.foreshadow import ForeshadowStore

        def menu(key):
            index = next(i for i, section in enumerate(SECTIONS)
                         if section.key == key)
            item = window.sidebar.item(index)
            QTest.mouseClick(window.sidebar.viewport(), Qt.MouseButton.LeftButton,
                             pos=window.sidebar.visualItemRect(item).center())
            app.processEvents()
            return window.canon_panels[key]

        def submit(panel, fields):
            for key, value in fields.items():
                panel._fill(key, value)
            QTest.mouseClick(panel.save_button, Qt.MouseButton.LeftButton)
            app.processEvents()
            if panel.status.text() != '현재 작품의 로컬 SQLite에 저장했습니다.':
                raise AssertionError('GUI data entry rejected: ' + panel.section)

        panel = menu('bible')
        submit(panel, {'key': 'genre', 'value': 'original fantasy'})
        with EpisodeStore(db_path) as db:
            check('bible_sidebar_gui_saved',
                  db.get_rule(pid, 'genre').value == 'original fantasy')

        panel = menu('characters')
        submit(panel, {'name': 'Traveler One', 'personality': 'curious',
                       'goal': 'find lantern', 'speech_style': 'short'})
        panel._reset()
        submit(panel, {'name': 'Traveler Two', 'personality': 'cautious',
                       'goal': 'guard village', 'speech_style': 'calm'})
        with CharacterStore(db_path) as db:
            people = db.list_characters(pid)
            check('character_sidebar_gui_saved',
                  len(people) == 2 and {p.name for p in people}
                  == {'Traveler One', 'Traveler Two'})

        panel = menu('world')
        submit(panel, {'category': 'region', 'name': 'Fictional Pass',
                       'description': 'Invented mountains'})
        with WorldCanonStore(db_path) as db:
            check('world_sidebar_gui_saved',
                  len(db.list_entries(pid)) == 1 and
                  db.list_entries(pid)[0].name == 'Fictional Pass')

        panel = menu('timeline')
        submit(panel, {'title': 'Lantern Journey',
                       'when': '2026-01-02'})
        with EventTimelineStore(db_path) as db:
            check('timeline_sidebar_gui_saved',
                  len(db.list_events(pid)) == 1 and
                  db.list_events(pid)[0].when == '2026-01-02')

        panel = menu('relationships')
        panel.fields['first'].setCurrentIndex(0)
        panel.fields['second'].setCurrentIndex(1)
        submit(panel, {'relationship': 'friends', 'notes': 'met on road'})
        with RelationshipStore(db_path) as db:
            check('relationships_sidebar_gui_saved',
                  len(db.list_at(pid, 1)) == 1 and
                  db.list_at(pid, 1)[0].relationship == 'friends')

        panel = menu('foreshadowing')
        submit(panel, {'title': 'Lantern secret',
                       'note': 'introduced in chapter one'})
        with ForeshadowStore(db_path) as db:
            threads = db.list_threads(pid)
            check('foreshadow_sidebar_gui_saved',
                  len(threads) == 1 and threads[0].title == 'Lantern secret')

        # Real existing-feature screens: pattern read, bounded manual comparison,
        # and user-clicked private TXT/EPUB export. No platform upload occurs.
        def extra_menu(key):
            index = next(i for i, section in enumerate(SECTIONS)
                         if section.key == key)
            item = window.sidebar.item(index)
            QTest.mouseClick(window.sidebar.viewport(), Qt.MouseButton.LeftButton,
                             pos=window.sidebar.visualItemRect(item).center())
            app.processEvents()
            return window.additional_panels[key]

        patterns = extra_menu('patterns')
        QTest.mouseClick(patterns.refresh_button, Qt.MouseButton.LeftButton)
        check('pattern_sidebar_real_local_library',
              '저장된 패턴' in patterns.report.toPlainText())

        similarity = extra_menu('similarity')
        similarity.reference_text.setPlainText(draft)
        QTest.mouseClick(similarity.compare_button, Qt.MouseButton.LeftButton)
        check('similarity_sidebar_real_engine',
              similarity.status.toPlainText().startswith('로컬 비교 결과: ')
              and '참고작 전수 검사' in similarity.status.toPlainText())

        publication = extra_menu('publication')
        private_path = output / 'private_publication_preview'
        private_path.mkdir()
        publication.directory.setText(str(private_path))
        publication.price.setText('0')
        check('reviewed_final_appears_in_publication_without_network',
              publication.wp_episodes.findData(1) >= 0
              and not publication.wp_owner_consent.isChecked())
        QTest.mouseClick(publication.final_export_button, Qt.MouseButton.LeftButton)
        reviewed = private_path / 'reviewed_final'
        check('final_txt_epub_export_via_real_publication_gui',
              (reviewed / 'final.txt').is_file()
              and (reviewed / 'book.epub').is_file()
              and '합성 테스트 원고]' in (reviewed / 'final.txt').read_text(encoding='utf-8')
              and verify_epub(reviewed / 'book.epub', expected_chapters=1).valid)
        QTest.mouseClick(publication.export_button, Qt.MouseButton.LeftButton)
        check('publication_sidebar_private_export',
              '로컬 파일 생성 완료' in publication.status.text()
              and (private_path / 'draft.txt').is_file()
              and (private_path / 'book.epub').is_file()
              and verify_epub(private_path / 'book.epub', expected_chapters=1).valid)

        # Audit while the main window is actually visible, not after closing it.
        from PySide6.QtWidgets import QLabel
        unconnected = []
        for index, section in enumerate(SECTIONS):
            item = window.sidebar.item(index)
            QTest.mouseClick(window.sidebar.viewport(), Qt.MouseButton.LeftButton,
                             pos=window.sidebar.visualItemRect(item).center())
            app.processEvents()
            page = window.pages.currentWidget()
            if page.findChild(QLabel, 'pending_' + section.key) is not None:
                unconnected.append(section.key)
        report['unconnected_user_menus'] = unconnected
        # Real local CPU model extended path: batch-create episode 2, quality
        # evidence, checkpoint then re-run without overwriting original draft.
        from ai_novel_factory.story_arcs import plan_story_arcs, validate_arc_coverage
        from ai_novel_factory.episode_planner import plan_episodes, validate_episode_plans
        from ai_novel_factory.planning import PlanningInput
        spec = PlanningInput('fantasy', 'original lantern adventure', 250, 'suspense')
        arcs = plan_story_arcs(spec)
        slots = plan_episodes(arcs)
        check('250_episode_arc_slot_coverage_only',
              validate_arc_coverage(arcs)
              and validate_episode_plans(arcs, slots)
              and len(slots) == 250)

        panel = ui.auto_panel
        panel.through.setValue(2)
        panel.target_chars.setValue(80)
        panel.scenes.setValue(1)
        panel.consent.setChecked(True)
        from time import monotonic, sleep
        QTest.mouseClick(panel.start_button, Qt.MouseButton.LeftButton)
        deadline = monotonic() + 175
        while panel.is_running() and monotonic() < deadline:
            app.processEvents()
            sleep(0.15)
        app.processEvents()
        with EpisodeStore(db_path) as db:
            episodes = db.list_episodes(pid)
            original = db.get_episode(pid, 1)
            newly = db.get_episode(pid, 2) if len(episodes) == 2 else None
            checks = db.list_checks(pid, 2) if newly else ()
            check('real_model_multi_episode_via_gui',
                  newly is not None and newly.draft.strip()
                  and original.draft == draft
                  and panel.status.text().startswith('작업 완료:'))
            check('real_local_ai_whole_story_preview_saved',
                  bool(db.get_rule(pid, 'ai_story_outline_preview').value.strip()))
            check('new_episode_persistent_qc_and_review',
                  len(checks) >= 6
                  and any(c.category == 'reference_similarity'
                          and c.outcome == 'NOT_RUN' for c in checks)
                  and newly.final_text == '')
        panel.consent.setChecked(True)
        QTest.mouseClick(panel.start_button, Qt.MouseButton.LeftButton)
        deadline = monotonic() + 30
        while panel.is_running() and monotonic() < deadline:
            app.processEvents()
            sleep(0.1)
        app.processEvents()
        with EpisodeStore(db_path) as db:
            check('batch_resume_never_overwrites_existing_episode',
                  panel.status.text().startswith('작업 완료:')
                  and '로컬 AI 실행 0회' in panel.status.text()
                  and db.get_episode(pid, 1).draft == draft
                  and db.get_episode(pid, 2).draft == newly.draft)

        check('no_publication', not hasattr(ui, 'publish_button'))
        draft_hash = hashlib.sha256(draft.encode('utf-8')).hexdigest()
        report['draft_sha256'] = draft_hash
        window.close()
        app.processEvents()
        import subprocess
        reopened_path = output / 'reopened_project_metadata.json'
        child = subprocess.run(
            [sys.executable, '--ci-reopen-project', str(db_path),
             str(pid), draft_hash, str(reopened_path)],
            timeout=90, capture_output=True, text=True, env=os.environ.copy())
        reopened = (json.loads(reopened_path.read_text(encoding='utf-8'))
                    if reopened_path.is_file() else {})
        check('independent_exe_restart',
              child.returncode == 0 and reopened.get('window_reopened') is True
              and reopened.get('process_id') != os.getpid())
        check('gui_reloaded_saved_project_and_exports',
              reopened.get('whole_reopen_journey') == 'PASS'
              and len(reopened.get('steps', [])) >= 6
              and all(s.get('result') == 'PASS' for s in reopened.get('steps', [])))
        report['reopen_steps'] = reopened['steps']
        check('all_twelve_user_menus_implemented', not unconnected)
        report['whole_user_journey'] = 'PASS'
    except BaseException as exc:
        report['blocker_type'] = type(exc).__name__
        report['blocker_step'] = report['steps'][-1]['step'] if report['steps'] else 'initialization'
    finally:
        (output / 'compiled_exe_user_journey.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if report['whole_user_journey'] == 'PASS' else 1


def run_reopen(args):
    """Validation-only: launch the compiled EXE as a fresh process and reopen saved work."""
    db_path, expected_id, expected_draft_sha, result_file = args
    result_path = Path(result_file).resolve()
    status = {'process_id': os.getpid(), 'window_reopened': False,
              'steps': [], 'whole_reopen_journey': 'FAIL'}
    def check(name, ok):
        status['steps'].append({'step': name, 'result': 'PASS' if ok else 'FAIL'})
        if not ok:
            raise AssertionError(name)
    window = None
    try:
        check('independent_compiled_windows_process',
              os.name == 'nt' and bool(getattr(sys, 'frozen', False)))
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.desktop.app import MainWindow
        from ai_novel_factory.epub3 import verify_epub
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.show()
        app.processEvents()
        status['window_reopened'] = window.isVisible()
        check('new_exe_gui_window_visible', status['window_reopened'])
        ui = window.authoring
        ui._set('db', str(Path(db_path).resolve()))
        QTest.mouseClick(ui.buttons['open'], Qt.MouseButton.LeftButton)
        app.processEvents()
        check('reopen_project_via_gui',
              ui.session.store is not None
              and str(ui.session.project_id) == str(expected_id)
              and ui._text('title') == '가상 등불 여행')
        check('saved_bible_after_restart',
              ui._text('bible') == '가상 마을의 길은 밤에만 열린다')
        check('saved_episode_and_scene_after_restart',
              ui.session.episode_number == 1
              and ui._text('plot').startswith('여행자가')
              and ui._text('scene').startswith('가상 산길'))
        saved_draft = ui._text('draft')
        check('real_model_draft_after_restart',
              bool(saved_draft.strip())
              and hashlib.sha256(saved_draft.encode('utf-8')).hexdigest() == expected_draft_sha)
        check('reviewed_final_persisted_after_independent_exe_restart',
              ui._text('final_text').endswith('합성 테스트 원고]'))
        txt = result_path.parent / 'draft.txt'
        epub = result_path.parent / 'book.epub'
        check('reopen_exported_txt',
              txt.is_file() and saved_draft in txt.read_text(encoding='utf-8'))
        check('reopen_exported_epub',
              epub.is_file() and verify_epub(epub, expected_chapters=1).valid)
        status['whole_reopen_journey'] = 'PASS'
    except BaseException as exc:
        status['blocker_type'] = type(exc).__name__
        status['blocker_step'] = status['steps'][-1]['step'] if status['steps'] else 'initialization'
    finally:
        if window is not None:
            window.close()
        result_path.write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if status['whole_reopen_journey'] == 'PASS' else 1
