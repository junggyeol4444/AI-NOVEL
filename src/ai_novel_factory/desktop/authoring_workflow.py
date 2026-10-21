"""Local authoring GUI event handlers; never uploads or publishes."""
from __future__ import annotations
import shlex
from PySide6.QtWidgets import QWidget, QFileDialog
from .authoring_controls import AuthoringControls
from .authoring_session import AuthoringSession
from .draft_worker import DraftWorker
from ai_novel_factory.korean_draft_quality import screen_korean_draft
from ai_novel_factory.local_models import effective_scene_target

_ASYNC_STARTED = object()

class AuthoringWorkflowWidget(AuthoringControls, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = AuthoringSession()
        self._draft_worker = None
        self._draft_request = None
        self._draft_identity = None
        self.build_controls()
        # Approval belongs to the exact executable AND arguments the author
        # reviewed. A later manual edit must immediately invalidate approval;
        # it must never carry over to another arbitrary local program/model.
        self.fields['executable'].textChanged.connect(
            lambda _text: self.approved.setChecked(False))
        self.fields['arguments'].textChanged.connect(
            lambda _text: self.approved.setChecked(False))
        # An empty workspace has no pending AI draft to save.
        self.buttons['save_draft'].setEnabled(False)
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
                    '오프라인 CPU 실행기와 연결 점검용 135M GGUF 발견. '
                    '이 기본 모델은 한국어 장편 집필용으로 검증되지 않았습니다. '
                    '실제 소설 집필에는 사용 권한이 있는 로컬 GGUF를 직접 선택하세요. '
                    '모델 자동 교체·다운로드는 없으며 실행할 때마다 승인해야 합니다.')

    def _run(self, fn, message):
        try:
            outcome = fn()
            if outcome is not _ASYNC_STARTED:
                self.status.setText(message)
                self._sync()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc)[:200])
        except Exception:
            self.status.setText('작업 실패: 상세 오류는 비공개입니다.')

    def _create(self):
        if self.auto_panel.is_running():
            raise ValueError('로컬 AI 다회차 집필 중에는 다른 작품을 생성할 수 없습니다.')
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
            # Executable replacement must never reuse --gguf args pointing
            # to a different runtime or preserve a previous approval.
            self.approved.setChecked(False)
            self._set('executable', path)
            self._set('arguments', '')
            self.status.setText(
                '로컬 실행 파일을 선택했습니다. 이전 모델 인수를 초기화했습니다. '
                '새 실행 파일의 기능을 확인한 뒤 이번 실행을 직접 승인하세요.')

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
        # Quote paths with spaces or literal double quotes using the
        # documented shlex tokenization already used in _generate.
        self._set('arguments', '--gguf ' + shlex.quote(str(selected)))
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
        if self.auto_panel.is_running():
            raise ValueError('로컬 AI 다회차 집필 중에는 작품을 변경할 수 없습니다.')
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
        self.buttons['save_draft'].setEnabled(
            self.session.pending_draft is not None and not self.is_generating())

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
            self.buttons['save_draft'].setEnabled(False)
            self._sync_scene()

    def is_generating(self):
        return self._draft_worker is not None and self._draft_worker.isRunning()

    def _generate(self):
        if self.is_generating():
            raise ValueError('이미 로컬 AI 집필이 실행 중입니다.')
        arguments = tuple(shlex.split(self._text('arguments')))
        characters = tuple(v.strip() for v in self._text('characters').split(',') if v.strip())
        request, provider, identity = self.session.prepare_generation(
            self._text('executable'), arguments, self.approved.isChecked(),
            self._text('goal'), self._text('conflict'), self._text('location'), characters)
        self.approved.setChecked(False)
        self._draft_request, self._draft_identity = request, identity
        worker = DraftWorker(request, provider, self)
        self._draft_worker = worker
        worker.generated.connect(self._on_generation_result)
        worker.failed.connect(self._on_generation_failed)
        worker.finished.connect(self._on_generation_finished)
        self.buttons['generate'].setEnabled(False)
        self.buttons['save_draft'].setEnabled(False)
        self.status.setAccessibleName('로컬 AI 집필 중')
        self.status.setText('로컬 AI 집필 중 — 화면은 계속 응답합니다. 자동 저장·출판 없음.')
        worker.start()
        return _ASYNC_STARTED

    def _on_generation_result(self, result):
        try:
            self.session.accept_generation(self._draft_request, result, self._draft_identity)
            self._sync_episode()
            draft = result.draft
            # The saved author setting, not an unsaved input edit, is the
            # actual full-episode quota. Match the native explicit goal parser.
            target_text = self.session.rule('characters_per_episode').strip()
            episode_target = int(target_text) if target_text.isdecimal() else 5000
            target = effective_scene_target(
                self._draft_request.scene_goal, self._draft_request.target_chars)
            if target is None:
                target = episode_target
            # A scene pass never certifies the entire episode.
            screening = screen_korean_draft(draft, target_chars=target)
            stats = (f'총 {screening.total_chars}자 / 한글 {screening.hangul_syllables}자 / '
                     f'영문 {screening.latin_letters}자 / '
                     f'중복문장 {screening.repeated_sentence_share:.1%} / '
                     f'중복구간 {screening.repeated_chunk_share:.1%} / '
                     f'한자·중국어 문자 {screening.han_script_chars}개 / '
                     f'소설 외 형식 {screening.non_prose_markers}건')
            if not screening.format_gate_pass:
                self.status.setAccessibleName('한국어 형식 검사 미달')
                self.status.setText(
                    f'한국어 장면 형식 검사 미달: {stats}. '
                    f'장면 목표 {target}자 / 회차 목표 {episode_target}자. '
                    '검수·수정·재집필 필요, 자동 확정·출판 없음.')
            else:
                self.status.setAccessibleName('한국어 형식 1차 검사 충족')
                self.status.setText(
                    f'한국어 장면 형식 1차 검사 충족: {stats}. '
                    f'장면 목표 {target}자 / 회차 목표 {episode_target}자. '
                    '전체 회차 분량·문학적 품질·독창성·유사성·연속성은 미검증입니다.')
        except (ValueError, OSError):
            self.status.setText('작품/회차/장면이 변경되어 결과를 적용하지 않았습니다.')
        except Exception:
            self.status.setText('AI 결과 반영 실패. 원고는 자동 저장되지 않았습니다.')

    def _on_generation_failed(self, category):
        safe_category = category if category in (
            'native_timeout', 'native_inference_failure',
            'native_process_crash', 'native_output_rejected',
            'native_no_hangul', 'native_non_korean_script',
            'native_prompt_echo', 'LocalModelError') else 'UnknownError'
        self.status.setAccessibleName('로컬 AI 생성 실패 ' + safe_category)
        if safe_category == 'native_output_rejected':
            self.status.setText('모델 출력 형식 검사 실패: 원고 저장을 차단했습니다.')
        elif safe_category == 'native_no_hangul':
            self.status.setText(
                '선택된 로컬 모델에서 한국어 소설이 생성되지 않았습니다. '
                '한국어 작성이 가능한 GGUF 모델을 직접 선택하세요. 초고 저장 없음.')
        elif safe_category == 'native_non_korean_script':
            bundled_qa = (
                self._text('arguments').strip() == ''
                and self._text('executable').replace('\\', '/').lower().endswith(
                    '/anf_local_model.exe'))
            if bundled_qa:
                self.status.setText(
                    '기본 번들 135M GGUF에서 한국어 비중이 부족한 원고가 생성됐습니다. '
                    '이 모델의 한국어 장편 집필 안정성은 검증되지 않았습니다. '
                    '기존 초고를 저장하지 않았습니다. '
                    '한국어를 지원하는 로컬 GGUF는 사용자가 직접 선택·승인해야 합니다.')
            else:
                self.status.setText(
                    '모델 원고에 한국어 단어와 외국 문자·깨진 표기가 혼입됐습니다. '
                    '원고를 수정·번역해 저장하지 않고 차단했습니다.')
        elif safe_category == 'native_prompt_echo':
            self.status.setText(
                '모델이 원고 대신 실행 지시나 콘솔 문구를 반복했습니다. '
                '정상 원고로 저장하지 않았습니다.')
        elif safe_category == 'native_process_crash':
            self.status.setText('Windows 로컬 모델 실행기가 비정상 종료되었습니다. 초고 저장 없음.')
        else:
            self.status.setText('로컬 AI 생성 실패 (' + safe_category + '): 초고 저장 없음.')
        if self.session.pending_draft is not None:
            # A previously generated unsaved preview remains author-owned;
            # do not silently delete it on a failed *new* generation.
            self.status.setText(
                self.status.text() + ' 이전 미저장 초고는 그대로 유지됩니다.')

    def _on_generation_finished(self):
        self.buttons['generate'].setEnabled(True)
        # A failed native inference must not present an empty/old preview as
        # a fresh result ready to be persisted.
        self.buttons['save_draft'].setEnabled(
            self.session.pending_draft is not None)
        self._draft_request = self._draft_identity = None
        worker = self._draft_worker
        self._draft_worker = None
        if worker is not None:
            worker.deleteLater()

    def closeEvent(self, event):
        if self.auto_panel.is_running():
            self.auto_panel.request_stop()
            self.status.setText('로컬 AI 다회차 집필 중입니다. 현재 호출 완료 후 종료하세요.')
            event.ignore()
            return
        if self.is_generating():
            self.status.setText('로컬 AI 작업 중입니다. 작업 완료 후 종료하세요.')
            event.ignore()
            return
        self.session.close()
        event.accept()
