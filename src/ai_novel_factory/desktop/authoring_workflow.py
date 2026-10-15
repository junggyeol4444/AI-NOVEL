"""Local authoring GUI event handlers; never uploads or publishes."""
from __future__ import annotations
import shlex
from PySide6.QtWidgets import QWidget, QFileDialog
from .authoring_controls import AuthoringControls
from .authoring_session import AuthoringSession

class AuthoringWorkflowWidget(AuthoringControls, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = AuthoringSession()
        self.build_controls()
        # The optional portable QA bundle includes both the console IPC bridge
        # and real GGUF weights. Detect only sibling files: never download
        # models or run unknown processes just by opening the GUI.
        import sys
        from pathlib import Path
        if getattr(sys, 'frozen', False):
            base = Path(sys.executable).resolve().parent
            bridge = base / 'ANF_Local_Model.exe'
            model = base / 'models' / 'SmolLM2-135M-Instruct-Q4_K_M.gguf'
            runtime = base / 'runtime' / 'llama-cli.exe'
            if bridge.is_file() and model.is_file() and runtime.is_file():
                self._set('executable', str(bridge))
                self._set('arguments', '')
                self.status.setText(
                    '오프라인 CPU AI 번들 발견. 별도 Python이나 API 키 없이 '
                    '로컬 모델을 사용할 수 있습니다. 실행할 때마다 직접 승인해야 합니다.')

    def _run(self, fn, message):
        try:
            fn()
            self.status.setText(message)
            self._sync()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc)[:200])
        except Exception:
            self.status.setText('작업 실패: 상세 오류는 비공개입니다.')

    def _create(self):
        extra = {key: self._text(key).strip() for key in
                 ('genre', 'subject', 'target_episodes',
                  'characters_per_episode', 'mood')}
        for key in ('target_episodes', 'characters_per_episode'):
            value = extra[key]
            if value and (not value.isdecimal() or not 1 <= int(value) <= 1000000):
                raise ValueError('분량은 1~1000000 범위의 정수여야 합니다.')
        self.session.create_project(self._text('db'), self._text('title'),
                                    self._text('author'), self._text('premise'),
                                    extra_rules=extra)

    def _choose_new_database(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '새 작품 DB 경로', '', 'SQLite (*.db *.sqlite)')
        if path:
            self._set('db', path)

    def _choose_existing_database(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '기존 작품 DB 선택', '', 'SQLite (*.db *.sqlite)')
        if path:
            self._set('db', path)

    def _choose_model_executable(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '신뢰할 수 있는 로컬 AI 실행 파일', '',
            'Windows 실행 파일 (*.exe);;모든 파일 (*)')
        if path:
            self._set('executable', path)

    def _choose_gguf_model(self):
        import sys
        from pathlib import Path
        if not getattr(sys, 'frozen', False):
            self.status.setText('이 기능은 CPU 모델 실행기가 포함된 Windows EXE에서 지원됩니다.')
            return
        base = Path(sys.executable).resolve().parent
        bridge = base / 'ANF_Local_Model.exe'
        runtime = base / 'runtime' / 'llama-cli.exe'
        if not bridge.is_file() or not runtime.is_file():
            self.status.setText('모델 실행기가 포함된 포터블 패키지가 필요합니다.')
            return
        path, _ = QFileDialog.getOpenFileName(
            self, '사용 권한이 있는 로컬 GGUF 모델 선택',
            str(base / 'models'), 'GGUF (*.gguf)')
        if not path:
            return
        selected = Path(path)
        try:
            if (not selected.is_absolute() or selected.is_symlink()
                    or selected.suffix.lower() != '.gguf'
                    or not 8_000_000 <= selected.stat().st_size <= 32_000_000_000):
                raise ValueError('model invalid')
        except (OSError, ValueError):
            self.status.setText('GGUF 모델 경로 또는 파일 크기가 올바르지 않습니다.')
            return
        self._set('executable', str(bridge))
        self._set('arguments', '--gguf "' + str(selected) + '"')
        self.approved.setChecked(False)
        self.status.setText(
            '선택한 로컬 GGUF로 생성하도록 설정했습니다. '
            '모델 파일은 업로드되지 않으며 실행 시 별도 승인이 필요합니다. '
            '실제 한국어 글 품질은 모델 성능에 따라 달라집니다.')

    def _save_final(self):
        self.session.save_final_text(
            self._text('final_text'),
            human_reviewed=self.final_reviewed.isChecked(),
            incomplete_qc_acknowledged=self.final_quality_ack.isChecked())
        self.final_reviewed.setChecked(False)
        self.final_quality_ack.setChecked(False)

    def _choose_export_directory(self):
        path = QFileDialog.getExistingDirectory(
            self, '비공개 원고 출력 폴더 선택')
        if path:
            self._set('export_dir', path)

    def _open(self):
        self.session.open_project(self._text('db'))
        db, pid = self.session.required()
        # Older valid Novel Bible databases may not carry the optional
        # author/canon rules. Opening must never mutate them or strand the
        # newly selected session after a missing-rule exception.
        metadata = {rule.key: rule.value for rule in db.list_rules(pid)}
        self._set('title', db.get_project(pid).title)
        self._set('author', metadata.get('author', ''))
        self._set('premise', metadata.get('premise', ''))
        for key in ('genre', 'subject', 'target_episodes',
                    'characters_per_episode', 'mood'):
            self._set(key, metadata.get(key, ''))

    def _sync(self):
        if not self.session.store:
            return
        db, pid = self.session.required()
        # Read missing legacy rules as empty, never create fictitious canon.
        rules = {rule.key: rule.value for rule in db.list_rules(pid)}
        self._set('bible', rules.get('premise', ''))
        self.episodes.blockSignals(True)
        self.episodes.clear()
        for ep in db.list_episodes(pid):
            self.episodes.addItem(f'{ep.episode}화', ep.episode)
        self.episodes.setCurrentIndex(self.episodes.findData(self.session.episode_number))
        self.episodes.blockSignals(False)
        self._sync_episode()
        self.auto_panel.refresh_defaults()

    def _sync_episode(self):
        db, pid = self.session.required()
        self.scenes.blockSignals(True)
        self.scenes.clear()
        if self.session.episode_number:
            ep = self.session.episode()
            self._set('plot', ep.plot)
            self._set('draft', self.session.pending_draft if self.session.pending_draft is not None else ep.draft)
            self._set('final_text', ep.final_text)
            self.final_reviewed.setChecked(False)
            self.final_quality_ack.setChecked(False)
            for scene in db.list_scenes(pid, ep.episode):
                self.scenes.addItem(f'장면 {scene.position}', scene.scene_id)
            self.scenes.setCurrentIndex(self.scenes.findData(self.session.scene_id))
        self.scenes.blockSignals(False)
        self._sync_scene()

    def _sync_scene(self):
        self._set('scene', self.session.scene().text if self.session.scene_id else '')

    def _select_episode(self, _index):
        number = self.episodes.currentData()
        if number:
            self._run(lambda: self.session.select_episode(number), '회차 선택 완료')

    def _select_scene(self, _index):
        sid = self.scenes.currentData()
        if sid:
            self.session.scene_id = sid
            self.session.pending_draft = None
            self._sync_scene()

    def _generate(self):
        arguments = tuple(shlex.split(self._text('arguments')))
        characters = tuple(v.strip() for v in self._text('characters').split(',') if v.strip())
        self.session.generate(self._text('executable'), arguments, self.approved.isChecked(),
                              self._text('goal'), self._text('conflict'), self._text('location'),
                              characters)
        self.approved.setChecked(False)

    def closeEvent(self, event):
        self.session.close()
        event.accept()
