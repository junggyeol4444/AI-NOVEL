"""UI for an explicitly approved real-model batch drafting run.

Runs on a worker thread, one saved episode at a time; cancellation is cooperative
at model call boundaries. This is NOT a full quality-approved/publication engine.
"""
from __future__ import annotations

from pathlib import Path
import shlex
from threading import Event

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGroupBox, QLabel, QPushButton, QSpinBox, QVBoxLayout,
    QFileDialog, QListWidget,
)
from ai_novel_factory.auto_novel_run import run_auto_novel, AutoNovelRunError
from ai_novel_factory.local_models import LocalExecutableProvider, LocalModelError
from ai_novel_factory.reference_batch_context import ReferenceBatchError
from ai_novel_factory.launch_consent_lease import (
    LaunchLeaseError, capture_launch_lease, verify_launch_lease,
)
from ai_novel_factory.batch_session_journal import (
    BatchJournalError, begin_session, end_session,
)
from .batch_recovery_panel import default_batch_journal_directory
from .scene_checkpoint_panel import default_scene_checkpoint_directory
from ai_novel_factory.scene_checkpoint_store import SceneCheckpointError
from ai_novel_factory.author_context_envelope import AuthorContextEnvelopeError
from .reference_selection import REFERENCE_FILE_FILTER, display_filename
from .reference_profile_browser import default_local_catalog_path


class AutoBatchWorker(QThread):
    progress_changed = Signal(int, str)
    finished_report = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path, project_id, provider, target, chars,
                 scenes, parent=None, *, reference_paths=(), catalog_path=None, batch_receipt=None,
                 scene_checkpoint_root=None, scene_checkpoint_lease=None,
                 context_sources=None):
        super().__init__(parent)
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.provider = provider
        self.target = target
        self.chars = chars
        self.scenes = scenes
        self.reference_paths = tuple(reference_paths)
        self.catalog_path = catalog_path
        self.batch_receipt = batch_receipt
        self.scene_checkpoint_root = scene_checkpoint_root
        self.scene_checkpoint_lease = scene_checkpoint_lease
        self.context_sources = context_sources
        self.stop_requested = Event()

    def run(self):
        journal_state = 'FAILED'
        try:
            result = run_auto_novel(
                self.database_path, self.project_id, self.provider,
                through_episode=self.target, target_chars=self.chars,
                scenes_per_episode=self.scenes,
                progress=lambda n, step: self.progress_changed.emit(n, step),
                should_stop=self.stop_requested.is_set,
                reference_paths=self.reference_paths,
                reference_catalog_path=self.catalog_path,
                scene_checkpoint_root=self.scene_checkpoint_root,
                scene_checkpoint_lease=self.scene_checkpoint_lease,
                context_sources=self.context_sources)
            journal_state = 'STOPPED' if result.stopped else 'FINISHED'
            self.finished_report.emit(result)
        except (AutoNovelRunError, LocalModelError, ReferenceBatchError) as exc:
            # These are explicitly sanitized, finite application messages.
            self.failed.emit(str(exc)[:160])
        except (OSError, ValueError):
            # An OS error can embed private filenames or user rule contents.
            self.failed.emit('로컬 집필 중 파일 접근·검증 오류가 발생했습니다.')
        except BaseException:
            self.failed.emit('자동 집필이 중단되었습니다. 작업 상태를 확인하세요.')
        finally:
            # Separate local receipt, not approval or proof of manuscript quality.
            if self.batch_receipt is not None:
                try:
                    end_session(self.batch_receipt.path,
                                self.batch_receipt.session_id,
                                state=journal_state)
                except (BatchJournalError, OSError, ValueError):
                    self.failed.emit('로컬 집필 종료 기록에 문제가 있습니다. 현재 SQLite 원고를 확인하세요.')


class AutoBatchPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('6. 여러 회차 로컬 AI 집필 (검토 전 초고)', parent)
        self.authoring = authoring
        self.worker = None
        self._approved_project = None
        self._launch_lease = None
        root = QVBoxLayout(self)
        notice = QLabel(
            '작품의 장르·소재·분위기·목표 회차를 먼저 저장하세요. '
            '실제 로컬 실행형 AI로 회차 플롯과 장면 초고를 생성합니다. '
            '기존 회차는 덮어쓰지 않습니다. '
            '검사 근거가 불충분한 초고는 수동 검수 대기이며 확정·게시되지 않습니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        form = QFormLayout()
        root.addLayout(form)
        self.through = QSpinBox()
        self.through.setObjectName('autoBatchThroughEpisode')
        self.through.setRange(1, 1000)
        self.through.setValue(2)
        form.addRow('생성할 마지막 회차', self.through)
        self.target_chars = QSpinBox()
        self.target_chars.setObjectName('autoBatchTargetChars')
        self.target_chars.setRange(50, 50000)
        self.target_chars.setValue(5000)
        form.addRow('회차별 목표 글자 수', self.target_chars)
        self.scenes = QSpinBox()
        self.scenes.setObjectName('autoBatchScenes')
        self.scenes.setRange(1, 20)
        self.scenes.setValue(3)
        form.addRow('회차별 장면 수', self.scenes)
        self.scene_checkpoint_opt_in = QCheckBox(
            '이번 실행의 AI 미검수 장면을 로컬에 임시 저장하고 동일 승인 설정에서만 재개')
        self.scene_checkpoint_opt_in.setObjectName('autoBatchSceneCheckpointOptIn')
        self.scene_checkpoint_opt_in.toggled.connect(
            lambda _checked: self.consent.setChecked(False))
        form.addRow(self.scene_checkpoint_opt_in)
        self.reference_paths = ()
        self.reference_choose = QPushButton('참고작 TXT/MD/EPUB/DOCX/PDF 직접 선택')
        self.reference_choose.setObjectName('autoBatchChooseReferences')
        self.reference_choose.clicked.connect(self.choose_reference_files)
        form.addRow(self.reference_choose)
        self.reference_clear = QPushButton('이번 실행의 참고작 선택 해제')
        self.reference_clear.setObjectName('autoBatchClearReferences')
        self.reference_clear.clicked.connect(self.clear_reference_files)
        form.addRow(self.reference_clear)
        self.reference_list = QListWidget()
        self.reference_list.setObjectName('autoBatchSelectedReferenceNames')
        self.reference_list.setMaximumHeight(90)
        form.addRow('이번 실행 참고작', self.reference_list)
        self.reference_notice = QLabel('참고작 미선택: 전수 유사성 검사 NOT_RUN')
        self.reference_notice.setWordWrap(True)
        form.addRow(self.reference_notice)
        self.consent = QCheckBox(
            '이번 실행에서만 지정한 로컬 모델로 순차 집필하는 것을 승인합니다')
        self.consent.setObjectName('autoBatchExplicitApproval')
        self.consent.toggled.connect(self._bind_approval)
        root.addWidget(self.consent)
        # Approval is for the CURRENT model, its arguments, and this exact
        # chapter configuration. Editing any of them revokes the earlier
        # batch approval before a worker can launch a different executable.
        self.authoring.fields['executable'].textChanged.connect(
            lambda _text: self.consent.setChecked(False))
        self.authoring.fields['arguments'].textChanged.connect(
            lambda _text: self.consent.setChecked(False))
        for spin in (self.through, self.target_chars, self.scenes):
            spin.valueChanged.connect(
                lambda _value: self.consent.setChecked(False))
        self.start_button = QPushButton('로컬 AI 여러 회차 집필 시작')
        self.start_button.setObjectName('autoBatchStart')
        self.stop_button = QPushButton('현재 장면 완료 후 중단')
        self.stop_button.setObjectName('autoBatchStop')
        self.stop_button.setEnabled(False)
        root.addWidget(self.start_button)
        root.addWidget(self.stop_button)
        self.status = QLabel('대기: 모델 실행 파일/인수를 위에서 지정하세요.')
        self.status.setWordWrap(True)
        self.status.setObjectName('autoBatchStatus')
        root.addWidget(self.status)
        self.start_button.clicked.connect(self.start_batch)
        self.stop_button.clicked.connect(self.request_stop)

    def choose_reference_files(self):
        if self.is_running():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, '이번 자동 집필에 사용할 참고작 선택', '', REFERENCE_FILE_FILTER)
        if not paths:
            return
        selected = list(self.reference_paths)
        for path in paths:
            if path not in selected:
                selected.append(path)
        if len(selected) > 100:
            self.reference_notice.setText('참고작은 한 번에 최대 100개까지 선택할 수 있습니다.')
            return
        self.reference_paths = tuple(selected)
        self.reference_list.clear()
        self.reference_list.addItems([display_filename(path) for path in self.reference_paths])
        self.reference_notice.setText(
            f'참고작 {len(selected)}개 선택 · 승인 후 로컬 분석/직접 비교 · 원문 AI 입력 없음')
        self.consent.setChecked(False)

    def clear_reference_files(self):
        if self.is_running():
            return
        self.reference_paths = ()
        self.reference_list.clear()
        self.reference_notice.setText('참고작 미선택: 전수 유사성 검사 NOT_RUN')
        self.consent.setChecked(False)

    def _bind_approval(self, checked):
        # Bind the author-initiated consent to the exact existing project,
        # local executable, selected references, and target parameters.
        session = self.authoring.session
        self._approved_project = (
            (str(session.path), str(session.project_id))
            if checked and session.path is not None
            and session.project_id is not None else None)
        self._launch_lease = None
        if checked:
            try:
                self._launch_lease = capture_launch_lease(
                    **self._launch_configuration())
            except (LaunchLeaseError, OSError, ValueError):
                self.consent.setChecked(False)
                self.status.setText(
                    '승인 대상 모델·작품·참고작을 확인할 수 없습니다. 다시 선택하세요.')

    def _launch_configuration(self):
        session = self.authoring.session
        return {
            'database_path': str(session.path) if session.path is not None else '',
            'project_id': str(session.project_id) if session.project_id is not None else '',
            'executable': self.authoring._text('executable').strip(),
            'arguments': self.authoring._text('arguments'),
            'through_episode': self.through.value(),
            'target_chars': self.target_chars.value(),
            'scenes_per_episode': self.scenes.value(),
            'reference_paths': self.reference_paths,
        }

    def refresh_defaults(self):
        if self.is_running():
            return
        for key, spin in (('target_episodes', self.through),
                          ('characters_per_episode', self.target_chars)):
            value = self.authoring._text(key).strip()
            if value.isdecimal() and spin.minimum() <= int(value) <= spin.maximum():
                spin.setValue(int(value))

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()

    def request_stop(self):
        if self.is_running():
            self.worker.stop_requested.set()
            self.status.setText('중단 요청: 실행 중인 로컬 모델 호출이 완료되면 중단합니다.')

    def start_batch(self):
        if self.is_running():
            return
        session = self.authoring.session
        if session.project_id is None or session.path is None:
            self.status.setText('작품 메뉴에서 먼저 작품을 생성하거나 열어 주세요.')
            return
        if self.target_chars.value() < 50 * self.scenes.value():
            self.status.setText(
                '회차 목표 분량이 장면 수에 비해 작습니다. '
                '장면마다 최소 50자 이상으로 설정하세요.')
            return
        if self.target_chars.value() > 10_000 * self.scenes.value():
            self.status.setText(
                '한 장면은 최대 10,000자까지 지원합니다. '
                '회차 목표 분량은 유지하고 장면 수를 늘려 주세요.')
            return
        if (not self.consent.isChecked()
                or self._approved_project !=
                (str(session.path), str(session.project_id))):
            self.consent.setChecked(False)
            self.status.setText('실제 로컬 AI 연속 실행에 대한 이번 회차 승인이 필요합니다.')
            return
        try:
            verify_launch_lease(self._launch_lease,
                                **self._launch_configuration())
        except (LaunchLeaseError, OSError, ValueError):
            self.consent.setChecked(False)
            self.status.setText('승인 이후 파일·작품·모델 설정이 바뀌었습니다. 다시 승인하세요.')
            return
        # Bind stage reuse only to the freshly verified, one-run author approval.
        checkpoint_fingerprint = (
            self._launch_lease.fingerprint
            if self.scene_checkpoint_opt_in.isChecked() else None)
        # Consume the consent before model initialization or worker creation.
        self.consent.setChecked(False)
        try:
            executable = self.authoring._text('executable').strip()
            arguments = tuple(shlex.split(self.authoring._text('arguments')))
            provider = LocalExecutableProvider(
                executable, arguments=arguments,
                timeout_seconds=(
                    1500 if (Path(executable).name.casefold() == 'anf_local_model.exe'
                             and arguments[:1] == ('--gguf',))
                    else 450 if arguments[:1] == ('--gguf',) else 120),
                explicitly_allowed=True)
        except LocalModelError as exc:
            # Our own sanitized setup diagnostics are safe for the GUI.
            self.status.setText(str(exc)[:160])
            return
        except (ValueError, OSError):
            # Raw exceptions can contain user-owned paths or launch options.
            self.status.setText('로컬 실행 파일 또는 인수 설정을 확인하세요.')
            return
        try:
            checkpoint_root = (default_scene_checkpoint_directory()
                               if checkpoint_fingerprint is not None else None)
        except (SceneCheckpointError, OSError, ValueError):
            self.status.setText('장면 임시 기록의 로컬 폴더를 확인할 수 없습니다.')
            return
        # Optional four-source context is consumed only after the author
        # separately approved its selection in the desktop feature hub.
        composer = getattr(self.authoring, 'author_context_composer_panel', None)
        try:
            selected_context_sources = (
                composer.consume_batch_sources() if composer is not None else None)
            if (selected_context_sources is not None
                    and composer.episode.value() != self.through.value()):
                raise AuthorContextEnvelopeError(
                    '장편 문맥 미리보기 회차와 현재 배치 마지막 회차가 다릅니다.')
        except (AuthorContextEnvelopeError, OSError, ValueError):
            self.status.setText('통합 작가 문맥 선택이나 지문이 바뀌었습니다. 다시 확인·승인하세요.')
            return
        # A new local receipt is created only after this explicit launch action.
        # No source text, model arguments or consent are stored in the receipt.
        try:
            receipt = begin_session(
                default_batch_journal_directory(),
                database_path=session.path, project_id=str(session.project_id),
                through_episode=self.through.value(),
                target_chars=self.target_chars.value(),
                scenes_per_episode=self.scenes.value(),
                reference_paths=self.reference_paths)
        except (BatchJournalError, OSError, ValueError):
            self.status.setText('작업 시작 기록을 생성할 수 없어 실행하지 않았습니다.')
            return
        self.worker = AutoBatchWorker(
            str(session.path), str(session.project_id), provider,
            self.through.value(), self.target_chars.value(), self.scenes.value(),
            self, reference_paths=self.reference_paths,
            catalog_path=(default_local_catalog_path() if self.reference_paths else None),
            batch_receipt=receipt,
            scene_checkpoint_root=checkpoint_root,
            scene_checkpoint_lease=checkpoint_fingerprint,
            context_sources=selected_context_sources)
        self.worker.progress_changed.connect(
            lambda num, stage: self.status.setText(f'{num}화: {stage}'))
        self.worker.finished_report.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._cleanup)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText('로컬 모델 연속 집필 시작. 저장된 회차는 건너뜁니다.')
        self.worker.start()

    def _finished(self, result):
        self.status.setText(
            f'작업 완료: 새 회차 {len(result.created_episodes)}개, '
            f'이미 존재하는 회차 {len(result.skipped_existing)}개, '
            f'로컬 AI 실행 {result.local_model_invocations}회. '
            f'검수 필수 {len(result.review_required_episodes)}개. '
            + ('중단 요청 반영됨.' if result.stopped else '비공개 초고만 저장됨.'))
        # Keep existing form edits untouched, but show the newly generated
        # saved episodes in the selector immediately. Preserve selection.
        session = self.authoring.session
        if (session.store is not None and session.project_id is not None
                and self.worker is not None
                and str(session.path) == str(self.worker.database_path)
                and str(session.project_id) == self.worker.project_id):
            selector = self.authoring.episodes
            selected = selector.currentData()
            selector.blockSignals(True)
            try:
                selector.clear()
                for episode in session.store.list_episodes(session.project_id):
                    selector.addItem(str(episode.episode) + '화', episode.episode)
                index = selector.findData(selected)
                selector.setCurrentIndex(index if index >= 0 else -1)
            finally:
                selector.blockSignals(False)
        if hasattr(self.authoring, 'feature_workspace_hub'):
            self.authoring.feature_workspace_hub.refresh_visible()
        if hasattr(self.authoring, 'scene_checkpoint_panel'):
            self.authoring.scene_checkpoint_panel.refresh()

    def _failed(self, message):
        self.status.setText('집필 실패/보류: ' + message)
        if hasattr(self.authoring, 'feature_workspace_hub'):
            self.authoring.feature_workspace_hub.refresh_visible()

    def _cleanup(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
