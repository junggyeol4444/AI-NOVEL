"""기존 Windows PySide6에서 직접 승인한 로컬 AI 회차별 기획 생성 화면."""
from __future__ import annotations

from pathlib import Path
from threading import Event
import shlex

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QFormLayout, QSpinBox, QLabel,
    QCheckBox, QPushButton, QListWidget, QPlainTextEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QComboBox,
)
from ai_novel_factory.author_ai_planning import (
    AuthorAiPlanningError, capture_author_ai_planning_source,
    require_current_author_ai_planning_source,
)
from ai_novel_factory.author_ai_episode_planning import (
    AuthorAiEpisodePlan, generate_author_ai_episode_plans,
)
from ai_novel_factory.local_models import LocalExecutableProvider, LocalModelError
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .draft_backup import write_draft_copy, DraftBackupError
from ..project_local_handoff import require_idle_authoring, LocalHandoffError


class AuthorAiEpisodePlanWorker(QThread):
    progress_changed = Signal(int, int)
    generated = Signal(object)
    failed = Signal(str)

    def __init__(self, source, provider, first, last, resume_from=None, parent=None):
        super().__init__(parent)
        self.source = source
        self.provider = provider
        self.first = first
        self.last = last
        self.resume_from = resume_from
        self.stop_requested = Event()

    def run(self):
        try:
            draft = generate_author_ai_episode_plans(
                self.source, self.provider, self.first, self.last,
                should_stop=self.stop_requested.is_set,
                progress=lambda n, last: self.progress_changed.emit(n, last),
                resume_from=self.resume_from)
            self.generated.emit(draft)
        except (AuthorAiPlanningError, LocalModelError):
            self.failed.emit(
                '승인한 로컬 AI 회차 기획 생성이 실패했습니다. '
                '기존 원고/SQLite에는 저장하지 않았습니다.')
        except BaseException:
            self.failed.emit(
                '로컬 AI 회차 기획이 중단됐습니다. '
                '기존 원고/SQLite에는 저장하지 않았습니다.')


class AuthorAiEpisodePlanningPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('로컬 AI 회차별 상세 기획 · 작가 별도 승인', parent)
        self.authoring = authoring
        self._worker = None
        self._token = None
        self._source = None
        self._result = None
        self._identity = None
        self._provider_identity = None
        self._pending = None
        self._resuming = False
        self._manual_beats = {}
        root = QVBoxLayout(self)
        notice = QLabel(
            '저장된 작품 설정·인물로 연속 최대 250화의 회차별 AI 기획 후보를 '
            '기존 승인 로컬 실행기로 생성합니다. 30·100·250화 지원. '
            '실제 생성량이 많을수록 승인 로컬 모델 호출도 늘어납니다. '
            '이 기능은 회차 원고 생성·'
            'SQLite 저장·작가 검수·출판이 아닙니다. '
            '선택한 실행 파일의 외부 통신 여부는 제공자와 확인하세요.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        form = QFormLayout()
        self.first = QSpinBox()
        self.first.setRange(1, 1000)
        self.first.setValue(1)
        self.first.setObjectName('authorAiEpisodeFirst')
        form.addRow('첫 회차', self.first)
        self.batch_preset = QComboBox()
        self.batch_preset.setObjectName('authorAiEpisodeBatchPreset')
        self.batch_preset.addItem('직접 회차 범위 설정', 0)
        self.batch_preset.addItem('30화 범위', 30)
        self.batch_preset.addItem('100화 범위', 100)
        self.batch_preset.addItem('250화 범위', 250)
        form.addRow('장편 기획 범위', self.batch_preset)
        self.last = QSpinBox()
        self.last.setRange(1, 1000)
        self.last.setValue(10)
        self.last.setObjectName('authorAiEpisodeLast')
        form.addRow('마지막 회차 (한 번에 최대 250화)', self.last)
        root.addLayout(form)
        self.batch_preset.currentIndexChanged.connect(self._apply_preset)
        self.consent = QCheckBox(
            '선택한 회차 기획에 대해 기존 로컬 모델을 이번 한 번만 실행하는 데 동의')
        self.consent.setObjectName('authorAiEpisodeConsent')
        root.addWidget(self.consent)
        self.start_button = QPushButton('승인된 로컬 AI로 회차별 기획 후보 생성')
        self.start_button.setObjectName('authorAiEpisodeStart')
        self.start_button.clicked.connect(self.start)
        root.addWidget(self.start_button)
        self.resume_button = QPushButton(
            '중단된 다음 회차부터 재개 (기존 모델·작품과 새 1회 승인 필요)')
        self.resume_button.setObjectName('authorAiEpisodeResume')
        self.resume_button.setEnabled(False)
        self.resume_button.clicked.connect(self.resume)
        root.addWidget(self.resume_button)
        self.stop_button = QPushButton('현재 AI 호출 종료 후 다음 회차부터 중단')
        self.stop_button.setObjectName('authorAiEpisodeStop')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.request_stop)
        root.addWidget(self.stop_button)
        self.status = QLabel('작품·로컬 모델을 선택한 뒤 별도 승인해 실행하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.choices = QListWidget()
        self.choices.setObjectName('authorAiEpisodeChoices')
        self.choices.currentRowChanged.connect(self.show_choice)
        root.addWidget(self.choices)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName('authorAiEpisodePreview')
        self.preview.setReadOnly(True)
        root.addWidget(self.preview)
        manual = QGroupBox('작가 직접 작성하는 회차별 장면 계획 · 미승인')
        manual_layout = QVBoxLayout(manual)
        manual_note = QLabel(
            'AI 회차 기획은 참고 후보입니다. 장면별 목표·갈등·장소·필수 사건·'
            '제외 요소는 작가가 직접 입력해야 하며, 기존 장면 기록을 자동 변경하지 않습니다.')
        manual_note.setWordWrap(True)
        manual_layout.addWidget(manual_note)
        self.manual_count = QSpinBox()
        self.manual_count.setRange(1, 20)
        self.manual_count.setValue(3)
        self.manual_count.setObjectName('authorAiEpisodeManualSceneCount')
        manual_layout.addWidget(self.manual_count)
        self.manual_table = QTableWidget(3, 5)
        self.manual_table.setObjectName('authorAiEpisodeManualSceneTable')
        self.manual_table.setHorizontalHeaderLabels(
            ('장면 목표', '갈등', '장소', '반드시 포함', '포함하지 말 것'))
        self.manual_table.setMinimumHeight(180)
        manual_layout.addWidget(self.manual_table)
        self.manual_handoff = QPushButton(
            '작가가 직접 작성한 장면 계획을 기존 장면 설계표에 전달 (저장하지 않음)')
        self.manual_handoff.setObjectName('authorAiEpisodeManualHandoff')
        self.manual_handoff.clicked.connect(self.handoff_manual_scenes)
        manual_layout.addWidget(self.manual_handoff)
        root.addWidget(manual)
        self.manual_count.valueChanged.connect(self._resize_manual)
        self.manual_table.cellChanged.connect(self._remember_manual)
        export = QPushButton('선택한 AI 회차 기획 후보를 새 비공개 TXT로 별도 저장')
        export.setObjectName('authorAiEpisodeExport')
        export.clicked.connect(self.export_private)
        root.addWidget(export)
        self.first.valueChanged.connect(self.invalidate)
        self.last.valueChanged.connect(self.invalidate)

    def _apply_preset(self, *_args):
        count = self.batch_preset.currentData()
        if type(count) is int and count:
            self.last.setValue(min(1000, self.first.value() + count - 1))
            self.invalidate()
            if self.first.value() + count - 1 > 1000:
                self.status.setText(
                    '저장된 회차 상한 1000화 안에서만 선택했습니다. '
                    '현재 범위를 직접 확인하고 별도 실행 승인하세요.')

    def is_running(self):
        return self._worker is not None and self._worker.isRunning()

    def invalidate(self, *_args):
        if self.is_running():
            self._worker.stop_requested.set()
        self._token = None
        self._source = self._result = self._identity = None
        self._provider_identity = None
        self._pending = None
        self._resuming = False
        self._manual_beats.clear()
        self._load_manual(None)
        self.consent.setChecked(False)
        self.resume_button.setEnabled(False)
        self.choices.clear()
        self.preview.clear()
        self.status.setText('작품 또는 회차 범위가 바뀌었습니다. 이전 AI 후보를 재사용하지 않습니다.')

    def _provider(self):
        executable = self.authoring._text('executable')
        arguments = tuple(shlex.split(self.authoring._text('arguments')))
        local_bridge = (Path(executable).name.casefold() == 'anf_local_model.exe'
                        and arguments[:1] == ('--gguf',))
        timeout = 1500 if local_bridge else 450 if arguments[:1] == ('--gguf',) else 120
        return LocalExecutableProvider(
            executable, arguments=arguments, timeout_seconds=timeout,
            explicitly_allowed=True)

    def _approved(self):
        approved = self.consent.isChecked() and self.authoring.approved.isChecked()
        self.consent.setChecked(False)
        self.authoring.approved.setChecked(False)
        return approved

    def start(self):
        if self.is_running():
            self.status.setText('기존 AI 호출이 끝나야 새 기획을 시작할 수 있습니다.')
            return
        approved = self._approved()
        self._result = None
        self._source = None
        self._token = None
        self._pending = None
        self._resuming = False
        self._manual_beats.clear()
        self._load_manual(None)
        self.resume_button.setEnabled(False)
        self.choices.clear()
        self.preview.clear()
        if not approved:
            self.status.setText('이번 회차 기획 승인과 로컬 모델 실행 승인이 모두 필요합니다.')
            return
        first, last = self.first.value(), self.last.value()
        if not 1 <= first <= last <= 1000 or last - first >= 250:
            self.status.setText(
                '연속된 1~250개 회차만 선택하세요. '
                '251~1000화는 250화 이내 구간으로 나누어 따로 승인하세요.')
            return
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            source = capture_author_ai_planning_source(
                session.store, session.path, str(session.project_id),
                through_episode=last)
            provider = self._provider()
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, LocalModelError, ValueError, OSError):
            self.status.setText(
                '저장된 작품 목표 회차·인물·Novel Bible 및 승인한 로컬 모델을 확인하세요.')
            return
        self._source = source
        self._identity = identity
        self._provider_identity = (
            self.authoring._text('executable'), self.authoring._text('arguments'))
        self._launch(source, provider, first, last, None)

    def resume(self):
        if self.is_running():
            self.status.setText('이전 로컬 AI 호출이 끝나야 재개할 수 있습니다.')
            return
        approved = self._approved()
        prior, source = self._result, self._source
        if (not approved or prior is None or source is None
                or not prior.interrupted
                or len(prior.episode_drafts) >= prior.last_episode - prior.first_episode + 1
                or (self.first.value(), self.last.value())
                   != (prior.first_episode, prior.last_episode)):
            self.status.setText('중단된 동일 회차 후보와 새 모델·기획 실행 승인이 필요합니다.')
            return
        if self._provider_identity != (
                self.authoring._text('executable'), self.authoring._text('arguments')):
            self.status.setText('기존 로컬 모델/인수가 변경돼 재개하지 않습니다.')
            return
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if identity != self._identity:
                raise AuthorAiPlanningError('작품 변경')
            require_current_author_ai_planning_source(
                source, session.store, session.path, str(session.project_id))
            provider = self._provider()
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, LocalModelError, ValueError, OSError):
            self.status.setText('작품·인물·원고 상태가 변경되어 이어서 생성하지 않습니다.')
            return
        self._resuming = True
        self._launch(source, provider, prior.first_episode, prior.last_episode, prior)

    def _launch(self, source, provider, first, last, prior):
        token = object()
        self._token = token
        self._pending = None
        worker = AuthorAiEpisodePlanWorker(
            source, provider, first, last, resume_from=prior, parent=self)
        self._worker = worker
        worker.progress_changed.connect(
            lambda number, last_number: self._progress(number, last_number, token))
        worker.generated.connect(lambda result: self._receive(result, token))
        worker.failed.connect(lambda message: self._failed(message, token))
        worker.finished.connect(lambda: self._finished(token))
        self.start_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText(
            f'기존 승인 모델로 {first}~{last}화 기획 후보 '
            f'{last-first+1}회 모델 호출 범위. '
            '장편 기획만 생성하며 원고·SQLite·출판 상태는 변경하지 않습니다.')
        worker.start()

    def request_stop(self):
        if self.is_running():
            self._worker.stop_requested.set()
            self.status.setText('중단 요청됨. 현재 호출이 끝나면 다음 회차를 실행하지 않습니다.')

    def _progress(self, number, last, token):
        if token is self._token:
            self.status.setText(
                f'로컬 AI {number}/{last}화 기획 생성 중 · 미검수·자동 저장 없음')

    def _receive(self, result, token):
        if token is self._token:
            self._pending = result

    def _failed(self, message, token):
        if token is self._token:
            if self._resuming and self._result is not None:
                self.status.setText(
                    '재개 중 실패했습니다. 이전 중단 회차 후보는 메모리에 보존했습니다.')
            else:
                self._result = None
                self.choices.clear()
                self.preview.clear()
                self.status.setText(message)
            self._resuming = False

    def _finished(self, token):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        result = self._pending
        self._pending = None
        if result is not None and token is self._token:
            self._accept(result)
        if self._result is not None:
            self.resume_button.setEnabled(
                self._result.interrupted
                and len(self._result.episode_drafts)
                    < self._result.last_episode - self._result.first_episode + 1)

    def _accept(self, result):
        source = self._source
        if source is None or result.source_fingerprint != source.fingerprint:
            self.invalidate()
            return
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if identity != self._identity:
                raise AuthorAiPlanningError('작품 변경')
            require_current_author_ai_planning_source(
                source, session.store, session.path, str(session.project_id))
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.invalidate()
            self.status.setText('생성 중 작품·인물·원고가 변경되어 AI 후보를 폐기했습니다.')
            return
        self._result = result
        self._resuming = False
        self.choices.clear()
        for number, _text in result.episode_drafts:
            self.choices.addItem(f'{number}화 AI 상세 기획 후보')
        if result.episode_drafts:
            self.choices.setCurrentRow(0)
        self.status.setText(
            f'AI 회차 기획 후보 {len(result.episode_drafts)}/'
            f'{result.last_episode-result.first_episode+1}화 '
            + ('중단됨 · 재개 가능. ' if result.interrupted else '호출 완료. ')
            + '실제 검수·원고 저장·출판 없음.')

    def _current_number(self):
        result = self._result
        row = self.choices.currentRow()
        if result is None or row < 0 or row >= len(result.episode_drafts):
            return None
        return result.episode_drafts[row][0]

    def _manual_rows(self):
        return tuple(tuple(
            self.manual_table.item(row, col).text()
            if self.manual_table.item(row, col) is not None else ''
            for col in range(5)) for row in range(self.manual_count.value()))

    def _remember_manual(self, *_args):
        number = self._current_number()
        if number is not None:
            self._manual_beats[number] = self._manual_rows()

    def _resize_manual(self, count):
        self.manual_table.setRowCount(count)
        self._remember_manual()

    def _load_manual(self, number):
        rows = self._manual_beats.get(number, (('', '', '', '', ''),) * 3)
        self.manual_table.blockSignals(True)
        self.manual_count.blockSignals(True)
        self.manual_count.setValue(len(rows))
        self.manual_table.setRowCount(len(rows))
        for row in range(len(rows)):
            for col in range(5):
                self.manual_table.setItem(
                    row, col, QTableWidgetItem(rows[row][col]))
        self.manual_count.blockSignals(False)
        self.manual_table.blockSignals(False)

    def show_choice(self, row):
        result = self._result
        if result is None or row < 0 or row >= len(result.episode_drafts):
            self.preview.clear()
            self._load_manual(None)
        else:
            self.preview.setPlainText(result.episode_drafts[row][1])
            self._load_manual(result.episode_drafts[row][0])

    def handoff_manual_scenes(self):
        source, result = self._source, self._result
        number = self._current_number()
        if source is None or result is None or number is None:
            self.status.setText('AI 기획 후보의 회차를 선택한 뒤 직접 장면별 내용을 입력하세요.')
            return
        beats = self._manual_rows()
        if (not 1 <= len(beats) <= 20
                or any(not value.strip() or len(value) > 400
                       or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
                       for row in beats for value in row)):
            self.status.setText(
                '모든 장면의 5개 항목을 직접 작성하세요. '
                '각 항목은 한 줄 400자 이하이며 빈 칸은 전달하지 않습니다.')
            return
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if identity != self._identity or result.source_fingerprint != source.fingerprint:
                raise AuthorAiPlanningError('작품이 변경됐습니다.')
            require_current_author_ai_planning_source(
                source, session.store, session.path, str(session.project_id))
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    'author_scene_plan_panel', project_identity=identity):
                raise AuthorAiPlanningError('기존 장면 계획 화면을 열 수 없습니다.')
            target = getattr(self.authoring, 'author_scene_plan_panel', None)
            if target is None or not target.accept_ai_episode_manual_beats(
                    source, number, beats, identity):
                raise AuthorAiPlanningError('기존 장면 입력 또는 저장 계획을 보호했습니다.')
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.status.setText(
                '작품·원고·장면 계획이 변경됐거나 기존 입력이 있습니다. '
                '기존 장면/원고를 변경하지 않았습니다.')
            return
        self.status.setText(
            f'{number}화의 작가 직접 작성 장면 {len(beats)}개를 '
            '기존 수동 설계표에 전달했습니다. 실제 JSON 저장은 '
            '해당 화면의 별도 1회 승인과 저장 버튼이 필요합니다.')

    def export_private(self):
        source, result = self._source, self._result
        if source is None or result is None or not result.episode_drafts:
            self.status.setText('먼저 실제 AI 회차 기획 후보를 생성하세요.')
            return
        try:
            session, identity = _current_author_state(self.authoring)
            require_idle_authoring(self.authoring, str(session.project_id))
            if identity != self._identity:
                raise AuthorAiPlanningError('작품 변경')
            require_current_author_ai_planning_source(
                source, session.store, session.path, str(session.project_id))
        except (AuthorAiPlanningError, BatchScopeBridgeError,
                LocalHandoffError, ValueError, OSError):
            self.invalidate()
            self.status.setText('기획 원본 변경: TXT를 저장하지 않았습니다.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '작가 미검수 회차별 AI 기획 새 로컬 TXT 사본', '', 'TXT (*.txt)')
        if not path:
            return
        try:
            write_draft_copy(path, result.private_text())
        except (DraftBackupError, AuthorAiPlanningError, ValueError, OSError):
            self.status.setText('기존 파일 덮어쓰기 없이 새 TXT를 저장하지 못했습니다.')
            return
        self.status.setText(
            '새 로컬 TXT에 미검수 회차 기획 후보를 보관했습니다. '
            '기존 원고·SQLite·출판 상태는 변경하지 않았습니다.')
