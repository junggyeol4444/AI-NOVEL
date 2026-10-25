"""작가 직접 승인한 기존 로컬 GGUF/EXE로 전체 줄거리·아크별 AI 기획 후보를 만든다.

별도의 모델 다운로드/교체/원격 호출 없음. 미검수 텍스트만 화면에 표시.
실제 원고·SQLite·아크 JSON·출판 결과를 자동 저장하지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from threading import Event
import shlex

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QGroupBox, QLabel,
    QListWidget, QPlainTextEdit, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)
from ai_novel_factory.author_ai_planning import (
    AuthorAiPlanningError, capture_author_ai_planning_source,
    generate_author_ai_planning, require_current_author_ai_planning_source,
)
from ai_novel_factory.local_models import LocalExecutableProvider, LocalModelError
from ai_novel_factory.desktop.draft_backup import write_draft_copy, DraftBackupError
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from ..project_local_handoff import require_idle_authoring, LocalHandoffError


class AuthorAiPlanningWorker(QThread):
    progress_changed = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source, provider, parent=None, *, resume_from=None):
        super().__init__(parent)
        self.source = source
        self.provider = provider
        self.resume_from = resume_from
        self.stop_requested = Event()

    def run(self):
        try:
            draft = generate_author_ai_planning(
                self.source, self.provider,
                should_stop=self.stop_requested.is_set,
                progress=lambda index, total: self.progress_changed.emit(index, total),
                resume_from=self.resume_from)
            self.completed.emit(draft)
        except (LocalModelError, AuthorAiPlanningError):
            self.failed.emit(
                '선택한 로컬 AI 기획 호출에 실패했습니다. '
                '모델 설정/응답 형식/기획 문맥을 다시 확인하세요.')
        except BaseException:
            self.failed.emit('로컬 AI 기획이 중단됐습니다. 결과를 저장하지 않았습니다.')


class AuthorAiPlanningPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('실제 로컬 AI 장편 전체 줄거리·아크 기획 후보 · 별도 승인', parent)
        self.authoring = authoring
        self._worker = None
        self._source = None
        self._result = None
        self._identity = None
        self._run_token = None
        self._pending_result = None
        self._edits = {}
        self._provider_identity = None
        self._resume_running = False
        root = QVBoxLayout(self)
        notice = QLabel(
            '작가가 직접 승인한 기존 로컬 EXE/GGUF만 실행합니다. '
            '전체 줄거리 1회와 아크별 AI 호출이 순차 진행됩니다. '
            '문학 품질 합격·원고 저장·편집기 승인·출판이 아닙니다. '
            '선택한 실행 파일의 외부 통신 여부는 파일 제공자와 직접 확인하세요.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        form = QFormLayout()
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.setObjectName('authorAiPlanningThrough')
        form.addRow('장편 후보 조회 마지막 회차', self.through)
        self.arc_count = QSpinBox()
        self.arc_count.setRange(0, 40)
        self.arc_count.setSpecialValueText('자동')
        self.arc_count.setObjectName('authorAiPlanningArcCount')
        form.addRow('전체 아크 수 (최대 40개)', self.arc_count)
        self.scene_count = QSpinBox()
        self.scene_count.setRange(1, 20)
        self.scene_count.setValue(3)
        form.addRow('기획 장면 수 (수동 설계 표용)', self.scene_count)
        root.addLayout(form)
        self.consent = QCheckBox(
            '이번 1회 전체 줄거리와 아크별 기획 생성을 기존 승인 로컬 모델로 실행합니다')
        self.consent.setObjectName('authorAiPlanningConsent')
        root.addWidget(self.consent)
        self.start_button = QPushButton('기존 로컬 AI로 전체 줄거리·아크별 기획 시작')
        self.start_button.setObjectName('authorAiPlanningStart')
        self.start_button.clicked.connect(self.start_planning)
        root.addWidget(self.start_button)
        self.resume_button = QPushButton(
            '중단된 아크 다음 번호부터 이어서 생성 (새로운 1회 승인 필요)')
        self.resume_button.setObjectName('authorAiPlanningResume')
        self.resume_button.setEnabled(False)
        self.resume_button.clicked.connect(self.resume_planning)
        root.addWidget(self.resume_button)
        self.stop_button = QPushButton('현재 AI 호출 뒤 기획 중단 요청')
        self.stop_button.setObjectName('authorAiPlanningStop')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_planning)
        root.addWidget(self.stop_button)
        self.status = QLabel('모델 실행 전 · 작가 직접 승인·저장된 작품 선택 필요')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.choices = QListWidget()
        self.choices.setObjectName('authorAiPlanningChoices')
        self.choices.currentRowChanged.connect(self.show_choice)
        root.addWidget(self.choices)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName('authorAiPlanningPreview')
        self.preview.setReadOnly(True)
        root.addWidget(self.preview)
        manual_box = QGroupBox('작가 직접 수정한 아크 요약 → 기존 수동 아크 입력 폼 인계')
        manual_form = QFormLayout(manual_box)
        self.manual_title = QLineEdit()
        self.manual_title.setObjectName('authorAiPlanningManualArcTitle')
        manual_form.addRow('아크 제목 (100자 이하)', self.manual_title)
        self.manual_fields = {}
        for name, label in (
                ('objective', '목표 (400자 이하, 한 줄)'),
                ('conflict', '갈등 (400자 이하, 한 줄)'),
                ('foreshadow', '복선 (400자 이하, 한 줄)'),
                ('resolution', '해소 (400자 이하, 한 줄)')):
            edit = QPlainTextEdit()
            edit.setMaximumHeight(65)
            edit.setObjectName('authorAiPlanningManual' + name.title())
            self.manual_fields[name] = edit
            manual_form.addRow(label, edit)
        root.addWidget(manual_box)
        handoff = QPushButton('직접 수정한 아크 요약을 기존 수동 아크 폼에 전달 (저장 안 함)')
        handoff.setObjectName('authorAiPlanningToArc')
        handoff.clicked.connect(self.handoff_manual_arc)
        root.addWidget(handoff)
        self.manual_title.textChanged.connect(self._remember_manual_edit)
        for edit in self.manual_fields.values():
            edit.textChanged.connect(self._remember_manual_edit)
        export = QPushButton('확인한 AI 기획 후보 전체를 새 로컬 TXT 사본으로 저장 (별도 클릭)')
        export.setObjectName('authorAiPlanningExport')
        export.clicked.connect(self.export_private)
        root.addWidget(export)
        for widget in (self.through, self.arc_count, self.scene_count):
            widget.valueChanged.connect(self.invalidate)

    def is_running(self):
        return self._worker is not None and self._worker.isRunning()

    def invalidate(self, *_args):
        if self.is_running():
            self._worker.stop_requested.set()
        self._run_token = None
        self._pending_result = None
        self._source = None
        self._identity = None
        self._result = None
        self._edits = {}
        self._provider_identity = None
        self._resume_running = False
        self.resume_button.setEnabled(False)
        self.consent.setChecked(False)
        self.choices.clear()
        self.preview.clear()
        self.status.setText('작품·범위·모델 실행 상태가 바뀌었습니다. 이전 AI 기획을 재사용하지 않습니다.')

    def _new_provider(self):
        arguments = tuple(shlex.split(self.authoring._text('arguments')))
        executable = self.authoring._text('executable')
        local_bridge = (Path(executable).name.casefold() == 'anf_local_model.exe'
                        and arguments[:1] == ('--gguf',))
        timeout = 1500 if local_bridge else 450 if arguments[:1] == ('--gguf',) else 120
        return LocalExecutableProvider(
            executable, arguments=arguments,
            timeout_seconds=timeout, explicitly_allowed=True)

    def start_planning(self):
        if self.is_running():
            self.status.setText('현재 AI 기획이 끝나거나 중단된 뒤 다시 실행하세요.')
            return
        approved_here = self.consent.isChecked()
        approved_model = self.authoring.approved.isChecked()
        # Model executable, its arguments, and this specific run are separate consents.
        self.consent.setChecked(False)
        self.authoring.approved.setChecked(False)
        self._source = self._result = self._identity = self._run_token = None
        self._pending_result = None
        self._edits = {}
        self._provider_identity = None
        self._resume_running = False
        self.resume_button.setEnabled(False)
        self.choices.clear()
        self.preview.clear()
        if not approved_here or not approved_model:
            self.status.setText(
                '기존 로컬 모델 실행 승인과 이번 아크 기획 1회 승인 둘 다 필요합니다.')
            return
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            source = capture_author_ai_planning_source(
                session.store, session.path, str(session.project_id),
                through_episode=self.through.value(),
                arc_option=self.arc_count.value(),
                scene_count=self.scene_count.value())
            provider = self._new_provider()
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, LocalModelError, ValueError, OSError):
            self.status.setText(
                '기존 작품 장르·소재·분위기·아크 범위 또는 직접 승인한 로컬 모델을 확인하세요.')
            return
        token = object()
        self._run_token = token
        self._source = source
        self._identity = identity
        self._provider_identity = (
            self.authoring._text('executable'), self.authoring._text('arguments'))
        worker = AuthorAiPlanningWorker(source, provider, self)
        self._worker = worker
        worker.progress_changed.connect(self._on_progress)
        worker.completed.connect(lambda result: self._receive_generated(result, token))
        worker.failed.connect(lambda error: self._on_failed(error, token))
        worker.finished.connect(lambda: self._on_finished(token))
        self.start_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText(
            f'전체 줄거리 1회 + 아크 {len(source.planning.arcs)}개를 '
            '승인된 로컬 모델에서 순차 생성합니다. 자동 저장 없음.')
        worker.start()

    def resume_planning(self):
        """중단된 메모리 후보와 같은 모델/작품에 대해서만 남은 아크를 실행."""
        if self.is_running():
            self.status.setText('이전 AI 호출이 종료된 뒤 재개할 수 있습니다.')
            return
        prior, source = self._result, self._source
        approved_here = self.consent.isChecked()
        approved_model = self.authoring.approved.isChecked()
        self.consent.setChecked(False)
        self.authoring.approved.setChecked(False)
        if (prior is None or source is None or not prior.interrupted
                or not prior.overview.strip()
                or len(prior.arc_drafts) >= len(source.planning.arcs)
                or not approved_here or not approved_model):
            self.status.setText(
                '중단된 아크 후보와 이번 재개 승인 및 기존 로컬 모델 승인이 필요합니다.')
            return
        if self._provider_identity != (
                self.authoring._text('executable'), self.authoring._text('arguments')):
            self.status.setText(
                '처음 생성한 로컬 모델/인수가 변경됐습니다. 이전 후보 재개를 거부합니다.')
            return
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if identity != self._identity:
                raise AuthorAiPlanningError('작품 변경')
            require_current_author_ai_planning_source(
                source, session.store, session.path, str(session.project_id))
            provider = self._new_provider()
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, LocalModelError, ValueError, OSError):
            self.status.setText(
                '저장 작품 설정·인물·기존 모델 승인 상태가 바뀌어 재개하지 않습니다.')
            return
        token = object()
        self._run_token = token
        self._pending_result = None
        self._resume_running = True
        worker = AuthorAiPlanningWorker(
            source, provider, self, resume_from=prior)
        self._worker = worker
        worker.progress_changed.connect(self._on_progress)
        worker.completed.connect(lambda result: self._receive_generated(result, token))
        worker.failed.connect(lambda error: self._on_failed(error, token))
        worker.finished.connect(lambda: self._on_finished(token))
        self.start_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText(
            f'이전 아크 {len(prior.arc_drafts)}개 후보를 메모리에서 유지하고 '
            f'나머지 {len(source.planning.arcs)-len(prior.arc_drafts)}개만 '
            '기존 승인 로컬 모델로 생성합니다. 원고/DB 자동 저장 없음.')
        worker.start()

    def stop_planning(self):
        if self.is_running():
            self._worker.stop_requested.set()
            self.status.setText(
                '중단 요청 수신. 현재 모델 호출이 종료되면 이어지는 아크를 생성하지 않습니다.')

    def _on_progress(self, index, total):
        if self._run_token is not None:
            self.status.setText(
                f'로컬 AI 아크 기획 {index}/{total} 호출 중 · 미검수·자동 저장 없음')

    def _receive_generated(self, result, token):
        # Worker QThread must fully exit before GUI authoring idle checks.
        if token is self._run_token:
            self._pending_result = result

    def _on_complete(self, result, token):
        if token is not self._run_token or self._source is None:
            return
        try:
            session, identity = _current_author_state(self.authoring)
            if identity != self._identity:
                raise AuthorAiPlanningError('다른 작품입니다.')
            require_idle_authoring(self.authoring, str(session.project_id))
            require_current_author_ai_planning_source(
                self._source, session.store, session.path, str(session.project_id))
            if result.source_fingerprint != self._source.fingerprint:
                raise AuthorAiPlanningError('작품의 AI 기획 원본이 변경됐습니다.')
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.invalidate()
            self.status.setText(
                '기획 생성 중 현재 작품·인물·원고가 변경되어 후보를 표시하지 않았습니다.')
            return
        self._result = result
        self._resume_running = False
        self.resume_button.setEnabled(
            result.interrupted and bool(result.overview.strip())
            and len(result.arc_drafts) < len(self._source.planning.arcs))
        self.choices.clear()
        self.choices.addItem('전체 줄거리 후보')
        for number, _text in result.arc_drafts:
            arc = next(a for a in self._source.planning.arcs if a.number == number)
            self.choices.addItem(
                f'아크 {number} ({arc.start_episode}~{arc.end_episode}화)')
        self.choices.setCurrentRow(0)
        self.status.setText(
            f'AI 전체 줄거리와 아크 {len(result.arc_drafts)}/'
            f'{len(self._source.planning.arcs)}개 후보 표시. '
            + ('중단되어 남은 아크 미작성. ' if result.interrupted else '')
            + '검수·원고 저장·출판 승인 없음.')

    def _on_failed(self, safe_error, token):
        if token is self._run_token:
            if self._resume_running and self._result is not None:
                self.status.setText(
                    '재개한 로컬 AI 호출에 실패했습니다. 기존 중단 후보는 '
                    '메모리에 보존했습니다. 다시 별도 승인 후 재개하세요.')
            else:
                self._result = None
                self.choices.clear()
                self.preview.clear()
                self.status.setText(safe_error)
            self._resume_running = False

    def _on_finished(self, token):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if self._result is not None and self._source is not None:
            self.resume_button.setEnabled(
                self._result.interrupted and bool(self._result.overview.strip())
                and len(self._result.arc_drafts) < len(self._source.planning.arcs))
        old_worker = self._worker
        self._worker = None
        if old_worker is not None:
            old_worker.deleteLater()
        result = self._pending_result
        self._pending_result = None
        if result is not None and token is self._run_token:
            self._on_complete(result, token)

    def _manual_values(self):
        return (
            self.manual_title.text(),
            self.manual_fields['objective'].toPlainText(),
            self.manual_fields['conflict'].toPlainText(),
            self.manual_fields['foreshadow'].toPlainText(),
            self.manual_fields['resolution'].toPlainText(),
        )

    def _remember_manual_edit(self, *_args):
        row = self.choices.currentRow()
        if self._result is None or not 1 <= row <= len(self._result.arc_drafts):
            return
        number = self._result.arc_drafts[row - 1][0]
        self._edits[number] = self._manual_values()

    def _load_manual_arc(self, number):
        if number is None:
            values = ('', '', '', '', '')
        else:
            values = self._edits.get(number, (f'아크 {number}', '', '', '', ''))
        editors = (self.manual_title, *self.manual_fields.values())
        for edit, value in zip(editors, values):
            edit.blockSignals(True)
            if isinstance(edit, QLineEdit):
                edit.setText(value)
            else:
                edit.setPlainText(value)
            edit.blockSignals(False)

    def handoff_manual_arc(self):
        source, result, identity = self._source, self._result, self._identity
        index = self.choices.currentRow()
        if (source is None or result is None or identity is None
                or not 1 <= index <= len(result.arc_drafts)):
            self.status.setText('생성된 아크 후보를 선택한 뒤 직접 요약을 작성하세요.')
            return
        number = result.arc_drafts[index - 1][0]
        values = self._manual_values()
        limits = (100, 400, 400, 400, 400)
        if any(type(value) is not str or not value.strip()
               or len(value) > maximum
               or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
               for value, maximum in zip(values, limits)):
            self.status.setText(
                '아크 제목 100자, 목표·갈등·복선·해소 각각 400자 이내의 '
                '한 줄 사용자 작성 요약을 모두 입력하세요. AI 원문은 잘라내지 않습니다.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if current != identity or result.source_fingerprint != source.fingerprint:
                raise AuthorAiPlanningError('작품 기획이 변경됐습니다.')
            require_current_author_ai_planning_source(
                source, session.store, session.path, str(session.project_id))
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    'author_arc_panel', project_identity=identity):
                raise AuthorAiPlanningError('기존 아크 편집 화면을 열지 못했습니다.')
            target = getattr(self.authoring, 'author_arc_panel', None)
            if target is None or not target.accept_ai_planning_candidate(
                    source, number, values, identity):
                raise AuthorAiPlanningError('기존 아크 입력칸이나 저장 기록을 보호했습니다.')
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.status.setText(
                '기존 아크 폴더·작품·미저장 아크 입력을 확인하세요. '
                '이미 기록된 계획이나 입력 내용을 덮어쓰지 않았습니다.')
            return
        self.status.setText(
            f'작가가 직접 정리한 아크 {number} 요약을 기존 입력칸에 전달했습니다. '
            '기존 아크 화면에서 별도 저장 승인을 해야 합니다.')

    def show_choice(self, row):
        if self._result is None or self._source is None:
            self.preview.clear()
            return
        if row == 0:
            self.preview.setPlainText(self._result.overview)
        elif 1 <= row <= len(self._result.arc_drafts):
            self.preview.setPlainText(self._result.arc_drafts[row - 1][1])
        else:
            self.preview.clear()
        number = (self._result.arc_drafts[row - 1][0]
                  if 1 <= row <= len(self._result.arc_drafts) else None)
        self._load_manual_arc(number)

    def export_private(self):
        source, result = self._source, self._result
        if source is None or result is None:
            self.status.setText('먼저 승인한 로컬 AI 기획 후보를 생성하세요.')
            return
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if identity != self._identity:
                raise AuthorAiPlanningError('작품이 변경되었습니다.')
            require_current_author_ai_planning_source(
                source, session.store, session.path, str(session.project_id))
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.invalidate()
            self.status.setText('기획 원본이 변경됐습니다. TXT 저장을 실행하지 않았습니다.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '미검수 AI 장편 기획 후보 TXT 새 사본', '', 'TXT (*.txt)')
        if not path:
            return
        try:
            text = result.as_private_text(source.planning)
            if self._edits:
                lines = ['', '작가 직접 작성한 임시 아크 요약 (수동 아크 기록으로 저장 전)']
                for number, values in sorted(self._edits.items()):
                    if any(value.strip() for value in values):
                        lines.append(f'아크 {number}:')
                        lines.extend(
                            f'{title}: {value}'
                            for title, value in zip(
                                ('제목', '목표', '갈등', '복선', '해소'), values))
                text += '\n'.join(lines) + '\n'
            write_draft_copy(path, text)
        except (DraftBackupError, AuthorAiPlanningError, ValueError, OSError):
            self.status.setText('새 로컬 TXT 파일 생성을 완료하지 못했습니다. 기존 파일 변경 없음.')
            return
        self.status.setText(
            '사용자가 선택한 새로운 로컬 TXT에 AI 기획 후보를 별도 보관했습니다. '
            '작품 SQLite·아크 기록·출판 상태는 변경하지 않았습니다.')
