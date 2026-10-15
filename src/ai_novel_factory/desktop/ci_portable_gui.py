"""Windows compiled EXE full self-contained real-model GUI journey (synthetic).

Runs the GUI .exe from the SAME portable folder as an included GGUF model,
llama.cpp CPU runtime and ANF_Local_Model.exe. User clicks are Qt QTest
events on actual widgets, not internal mocked provider calls. No manuscripts,
credentials or public network requests. Logs only metadata and hashes.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys


def run(out: str) -> int:
    output = Path(out).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = dict(
        test='COMPILED_WIN_EXE_BUNDLED_GGUF_QT_GUI',
        frozen=bool(getattr(sys, 'frozen', False)),
        rendered_offscreen=True,
        human_visual_review='UNVERIFIED',
        model='bundled_smollm2_135m_gguf_cpu',
        public_publishing_performed=False,
        no_user_data=True,
        steps=[], result='FAIL')
    def check(name, cond):
        report['steps'].append(dict(step=name, result='PASS' if cond else 'FAIL'))
        if not cond:
            raise AssertionError(name)
    window = None
    try:
        check('native_windows_compiled_exe',
              os.name == 'nt' and bool(getattr(sys, 'frozen', False)))
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from ai_novel_factory.database.episodes import EpisodeStore
        from ai_novel_factory.epub3 import verify_epub
        from ai_novel_factory.desktop.app import MainWindow
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.show()
        app.processEvents()
        window.novel_tabs.setCurrentIndex(1)  # choose detailed authoring tools
        app.processEvents()
        ui = window.authoring
        bundle = Path(sys.executable).resolve().parent
        expected = bundle / 'ANF_Local_Model.exe'
        check('ui_detected_bundled_ai_executable_without_python',
              ui._text('executable') == str(expected)
              and ui._text('arguments') == ''
              and expected.is_file()
              and not ui.approved.isChecked())
        db_file = output / 'portable_synthetic.db'
        ui._set('db', str(db_file))
        ui._set('title', '가상 등불 여행')
        ui._set('author', '합성 테스트 작가')
        ui._set('premise', '완전히 가상의 산악 마을에서 등불을 찾는 이야기')
        for key, value in (('genre', 'fantasy'), ('subject', 'original lantern adventure'),
                           ('target_episodes', '2'), ('characters_per_episode', '80'),
                           ('mood', 'suspense')):
            ui._set(key, value)
        QTest.mouseClick(ui.buttons['create'], Qt.MouseButton.LeftButton)
        app.processEvents()
        check('portable_gui_created_local_novel_db',
              ui.session.project_id is not None and db_file.is_file())
        pid = ui.session.project_id
        ui._set('bible', '가상 마을의 길은 밤에만 열린다')
        QTest.mouseClick(ui.buttons['save_bible'], Qt.MouseButton.LeftButton)
        ui.number.setValue(1)
        ui._set('plot', '여행자가 북쪽 문을 발견하고 등불을 찾아 떠난다')
        QTest.mouseClick(ui.buttons['create_episode'], Qt.MouseButton.LeftButton)
        QTest.mouseClick(ui.buttons['add_scene'], Qt.MouseButton.LeftButton)
        ui._set('scene', '가상 산길에서 안개와 마주한다')
        QTest.mouseClick(ui.buttons['save_scene'], Qt.MouseButton.LeftButton)
        ui._set('goal', '등불 찾기')
        ui._set('conflict', '문이 잠겨 있다')
        ui._set('location', '가상의 산길')
        ui._set('characters', '여행자')
        check('explicit_model_approval_required', not ui.approved.isChecked())
        ui.approved.setChecked(True)
        QTest.mouseClick(ui.buttons['generate'], Qt.MouseButton.LeftButton)
        app.processEvents()
        draft = ui._text('draft')
        check('real_bundled_gguf_model_generated_prose_via_gui',
              bool(draft.strip())
              and ui.session.pending_draft == draft
              and not ui.approved.isChecked())
        with EpisodeStore(db_file) as db:
            check('draft_preview_not_implicitly_saved', not db.get_episode(pid, 1).draft)
        QTest.mouseClick(ui.buttons['save_draft'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_file) as db:
            check('model_draft_saved', db.get_episode(pid, 1).draft == draft)
        ui._set('final_text', draft + '\n[사용자 검수 완료: 합성 테스트 원고]')
        QTest.mouseClick(ui.buttons['save_final'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_file) as db:
            check('portable_gui_final_requires_explicit_human_review',
                  db.get_episode(pid, 1).final_text == '')
        ui.final_reviewed.setChecked(True)
        ui.final_quality_ack.setChecked(True)
        QTest.mouseClick(ui.buttons['save_final'], Qt.MouseButton.LeftButton)
        with EpisodeStore(db_file) as db:
            check('portable_gui_final_manual_approval_saved',
                  db.get_episode(pid, 1).final_text.endswith('합성 테스트 원고]')
                  and not ui.final_reviewed.isChecked()
                  and not ui.final_quality_ack.isChecked())
        ui._set('export_dir', str(output))
        ui._set('price', '0')
        QTest.mouseClick(ui.buttons['export'], Qt.MouseButton.LeftButton)
        check('bundle_export_txt_reopens',
              (output / 'draft.txt').is_file()
              and draft in (output / 'draft.txt').read_text(encoding='utf-8'))
        check('bundle_export_epub3_verifies',
              (output / 'book.epub').is_file()
              and verify_epub(output / 'book.epub', expected_chapters=1).valid)
        h = sha256(draft.encode('utf-8')).hexdigest()
        report['synthetic_draft_sha256'] = h
        report['synthetic_draft_char_count'] = len(draft)
        window.close()
        window = None
        app.processEvents()
        restart_report = output / 'restarted_report.json'
        process = subprocess.run(
            [sys.executable, '--ci-reopen-project', str(db_file), str(pid),
             h, str(restart_report)],
            capture_output=True, timeout=75, text=True, env=os.environ.copy())
        check('independent_bundled_gui_exe_restarted',
              process.returncode == 0 and restart_report.is_file())
        restarted = json.loads(restart_report.read_text(encoding='utf-8'))
        check('bundle_gui_saved_novel_reopened_and_exports_reloaded',
              restarted.get('whole_reopen_journey') == 'PASS')
        report['result'] = 'PASS'
    except BaseException as exc:
        report['failure_stage'] = report['steps'][-1]['step'] if report['steps'] else 'initialization'
        report['failure_category'] = type(exc).__name__
    finally:
        if window is not None:
            window.close()
        (output / 'portable_gui_report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Test-only synthetic novel and exported fiction must not be uploaded.
    return 0 if report['result'] == 'PASS' else 1
