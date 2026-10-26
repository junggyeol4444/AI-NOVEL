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
    QFileDialog, QListWidget, QComboBox, QPlainTextEdit,
)
from ai_novel_factory.auto_novel_run import run_auto_novel, AutoNovelRunError
from ai_novel_factory.local_plot_only_draft import (
    PlotOnlyDraftError, begin_plot_only_draft, require_current_plot_only_lease,
    propose_plot_only_draft, save_plot_only_draft,
)
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.local_plot_only_recovery import (
    PlotOnlyRecoveryError, export_unsaved_plot, import_unsaved_plot,
)
from ai_novel_factory.author_ai_novel_guidance import (
    AuthorAiNovelGuidanceError, prepare_author_ai_novel_guidance,
    require_current_author_ai_novel_guidance,
)
from ai_novel_factory.local_models import LocalExecutableProvider, LocalModelError
from ai_novel_factory.reference_batch_context import ReferenceBatchError
from ai_novel_factory.references.element_selection import FEATURE_KEYS, FEATURE_LABELS
from ai_novel_factory.launch_consent_lease import (
    LaunchLeaseError, capture_launch_lease, verify_launch_lease,
)
from ai_novel_factory.batch_session_journal import (
    BatchJournalError, begin_session, end_session,
)
from .batch_recovery_panel import default_batch_journal_directory
from .scene_checkpoint_panel import default_scene_checkpoint_directory
from ai_novel_factory.scene_checkpoint_store import SceneCheckpointError
from ai_novel_factory.author_scene_checkpoint_integrity import SceneStageChoice
from ai_novel_factory.author_context_envelope import AuthorContextEnvelopeError
from ai_novel_factory.author_context_scope import plan_author_context_scope
from .reference_selection import REFERENCE_FILE_FILTER, display_filename
from .reference_profile_browser import default_local_catalog_path
from ai_novel_factory.project_local_handoff import require_idle_authoring, LocalHandoffError


class AutoBatchWorker(QThread):
    progress_changed = Signal(int, str)
    finished_report = Signal(object)
    full_text_screen_finished = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path, project_id, provider, target, chars,
                 scenes, parent=None, *, reference_paths=(), reference_metric_keys=None,
                 catalog_path=None, batch_receipt=None,
                 scene_checkpoint_root=None, scene_checkpoint_lease=None,
                 context_sources=None, explicit_resume_choice=None,
                 episode_writing_guidance=None, full_text_screen=False):
        super().__init__(parent)
        self.database_path = Path(database_path)
        self.project_id = project_id
        self.provider = provider
        self.target = target
        self.chars = chars
        self.scenes = scenes
        self.reference_paths = tuple(reference_paths)
        self.reference_metric_keys = reference_metric_keys
        self.catalog_path = catalog_path
        self.batch_receipt = batch_receipt
        self.scene_checkpoint_root = scene_checkpoint_root
        self.scene_checkpoint_lease = scene_checkpoint_lease
        self.context_sources = context_sources
        self.explicit_resume_choice = explicit_resume_choice
        self.episode_writing_guidance = episode_writing_guidance
        self.full_text_screen = full_text_screen is True
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
                reference_metric_keys=self.reference_metric_keys,
                reference_catalog_path=self.catalog_path,
                scene_checkpoint_root=self.scene_checkpoint_root,
                scene_checkpoint_lease=self.scene_checkpoint_lease,
                context_sources=self.context_sources,
                explicit_resume_choice=self.explicit_resume_choice,
                episode_writing_guidance=self.episode_writing_guidance)
            journal_state = 'STOPPED' if result.stopped else 'FINISHED'
            # The author opted into a read-only saved manuscript evidence
            # screen. It is not an all-content literary quality certificate.
            if self.full_text_screen and not result.stopped:
                try:
                    from ai_novel_factory.database.episodes import EpisodeStore
                    from ai_novel_factory.full_manuscript_screen import (
                        scan_saved_full_manuscript,
                    )
                    with EpisodeStore(self.database_path) as persisted:
                        evidence = scan_saved_full_manuscript(
                            persisted, self.project_id,
                            through_episode=self.target,
                            target_chars=self.chars)
                    self.full_text_screen_finished.emit(evidence)
                except (OSError, ValueError):
                    self.full_text_screen_finished.emit(None)
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


class PlotOnlyDraftWorker(QThread):
    """One selected existing plot-only chapter, real local model, no DB writes."""
    proposed = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path, project_id, episode, lease,
                 provider, target, max_calls, parent=None):
        super().__init__(parent)
        self.database_path = str(database_path)
        self.project_id = project_id
        self.episode = episode
        self.lease = lease
        self.provider = provider
        self.target = target
        self.max_calls = max_calls
        self.stop_requested = Event()

    def run(self):
        try:
            result = propose_plot_only_draft(
                self.database_path, self.project_id, self.episode,
                self.provider, expected_lease=self.lease,
                target_nonspace_chars=self.target,
                max_model_calls=self.max_calls,
                explicit_author_model_run=True,
                should_stop=self.stop_requested.is_set)
            self.proposed.emit(result)
        except (PlotOnlyDraftError, LocalModelError) as exc:
            self.failed.emit(str(exc)[:160])
        except (OSError, ValueError, UnicodeError):
            self.failed.emit('저장 플롯·작가 문맥·로컬 모델 입력이 변경되어 후보를 보류했습니다.')
        except BaseException:
            self.failed.emit('로컬 모델 집필 중단: 저장된 플롯 회차는 변경하지 않았습니다.')


class AutoBatchPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('6. 여러 회차 로컬 AI 집필 (검토 전 초고)', parent)
        self.authoring = authoring
        self.worker = None
        self.plot_worker = None
        self._plot_lease = None
        self._plot_identity = None
        self._plot_source_database = None
        self._approved_project = None
        self._launch_lease = None
        self._explicit_resume_choice = None
        self._resume_project_identity = None
        self._approved_ai_writing_guidance = None
        self._screen_summary = None
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
        self.actual_novel_preset = QComboBox()
        self.actual_novel_preset.setObjectName('autoBatchActualNovelPreset')
        self.actual_novel_preset.addItem('직접 회차 입력 (최대 1000화)', 0)
        self.actual_novel_preset.addItem('실제 로컬 AI 30화 소설 집필', 30)
        self.actual_novel_preset.addItem('실제 로컬 AI 100화 소설 집필', 100)
        self.actual_novel_preset.addItem('실제 로컬 AI 250화 소설 집필', 250)
        form.addRow('실제 장편 본문 집필 범위', self.actual_novel_preset)
        self.through = QSpinBox()
        self.through.setObjectName('autoBatchThroughEpisode')
        self.through.setRange(1, 1000)
        self.through.setValue(2)
        form.addRow('생성할 마지막 회차', self.through)
        self.use_ai_episode_guide = QCheckBox(
            '기존 AI 회차별 기획 화면의 완성된 1~N화 후보를 '
            '실제 GGUF 본문 집필에 이번 한 번만 사용')
        self.use_ai_episode_guide.setObjectName('autoBatchUseAiEpisodeGuide')
        form.addRow(self.use_ai_episode_guide)
        self.episode_guide_notice = QLabel(
            '선택하지 않으면 기존 자동 집필이 자체 회차 플롯을 생성합니다. '
            '선택하면 다른 화면에서 생성한 미검수 회차 기획을 모델 문맥으로만 '
            '인계합니다. AI 기획 자체는 작가가 승인한 확정 원고가 아닙니다.')
        self.episode_guide_notice.setWordWrap(True)
        form.addRow(self.episode_guide_notice)
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
        self.scan_after_batch = QCheckBox(
            '집필 종료 후 1~N화 저장 본문의 한글 분량·형식·동일 문장 범위를 확인')
        self.scan_after_batch.setObjectName('autoBatchFullTextEvidenceOptIn')
        self.scan_after_batch.setChecked(True)
        form.addRow(self.scan_after_batch)
        self.scene_checkpoint_opt_in = QCheckBox(
            '이번 실행의 AI 미검수 장면을 로컬에 임시 저장하고 동일 승인 설정에서만 재개')
        self.scene_checkpoint_opt_in.setObjectName('autoBatchSceneCheckpointOptIn')
        self.scene_checkpoint_opt_in.toggled.connect(
            lambda _checked: self.consent.setChecked(False))
        form.addRow(self.scene_checkpoint_opt_in)
        self.resume_notice = QLabel('직접 선택한 임시 장면 재개: 미선택')
        self.resume_notice.setWordWrap(True)
        form.addRow(self.resume_notice)
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
        self.metric_checks = {}
        for key in FEATURE_KEYS:
            control = QCheckBox('통계 참고: ' + FEATURE_LABELS[key])
            control.setObjectName('autoBatchReferenceMetric_' + key)
            control.setChecked(key in (
                'dialogue_ratio', 'sentence_characters',
                'event_cue_density_per_1000', 'cliffhanger_episode_rate'))
            self.metric_checks[key] = control
            form.addRow(control)
        self.context_scope_button = QPushButton(
            '선택한 작가 통합 문맥 1~N화 전수 준비 확인 (모델 실행 없음)')
        self.context_scope_button.setObjectName('autoBatchAuthorContextScopePreview')
        self.context_scope_button.clicked.connect(self.preview_author_context_scope)
        form.addRow(self.context_scope_button)
        self.context_scope_notice = QLabel(
            '작가 통합 문맥을 선택한 경우 실제 집필 전 모든 미작성 회차를 확인합니다. '
            '이 조회는 집필 승인이나 QC 합격이 아닙니다.')
        self.context_scope_notice.setWordWrap(True)
        form.addRow(self.context_scope_notice)
        self.consent = QCheckBox(
            '이번 실행에서만 지정한 로컬 모델로 순차 집필하는 것을 승인합니다')
        self.consent.setObjectName('autoBatchExplicitApproval')
        self.consent.toggled.connect(self._bind_approval)
        self.use_ai_episode_guide.toggled.connect(
            lambda _checked: self.consent.setChecked(False))
        self.actual_novel_preset.currentIndexChanged.connect(
            self._apply_actual_novel_preset)
        self.through.valueChanged.connect(self._sync_actual_novel_preset)
        root.addWidget(self.consent)
        for control in self.metric_checks.values():
            control.toggled.connect(lambda _checked: self.consent.setChecked(False))
            control.toggled.connect(lambda _checked: self.clear_explicit_scene_resume())
        # Approval is for the CURRENT model, its arguments, and this exact
        # chapter configuration. Editing any of them revokes the earlier
        # batch approval before a worker can launch a different executable.
        self.authoring.fields['executable'].textChanged.connect(
            lambda _text: self.consent.setChecked(False))
        self.authoring.fields['arguments'].textChanged.connect(
            lambda _text: self.consent.setChecked(False))
        for field in ('executable', 'arguments'):
            self.authoring.fields[field].textChanged.connect(
                lambda _text: self.clear_explicit_scene_resume())
        self.scan_after_batch.toggled.connect(
            lambda _value: self.consent.setChecked(False))
        for spin in (self.through, self.target_chars, self.scenes):
            spin.valueChanged.connect(
                lambda _value: self.consent.setChecked(False))
        for spin in (self.through, self.target_chars, self.scenes):
            spin.valueChanged.connect(lambda _value: self.clear_explicit_scene_resume())
        self.scene_checkpoint_opt_in.toggled.connect(
            lambda enabled: self.clear_explicit_scene_resume() if not enabled else None)
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

        # Real missing chapter operation: the batch engine deliberately
        # SKIPS an already-saved plot-only chapter, so let its author
        # generate/review/save that one unfinished chapter separately.
        root.addWidget(QLabel(
            '기존 저장 플롯만 있는 미완성 회차의 실제 초고 복구 '
            '(자동 배치가 건너뛴 회차 · 최종본/장면 보호)'))
        recovery_form = QFormLayout()
        self.plot_episode = QSpinBox()
        self.plot_episode.setRange(1, 1000)
        self.plot_episode.setValue(1)
        self.plot_episode.setObjectName('autoBatchPlotOnlyEpisode')
        recovery_form.addRow('복구할 기존 플롯 회차', self.plot_episode)
        self.plot_target = QSpinBox()
        self.plot_target.setRange(1000, 50000)
        self.plot_target.setValue(5000)
        self.plot_target.setObjectName('autoBatchPlotOnlyTarget')
        recovery_form.addRow('공백 제외 목표 글자 수', self.plot_target)
        self.plot_calls = QSpinBox()
        self.plot_calls.setRange(1, 12)
        self.plot_calls.setValue(8)
        self.plot_calls.setObjectName('autoBatchPlotOnlyMaxCalls')
        recovery_form.addRow('이번 실행 최대 GGUF 호출', self.plot_calls)
        root.addLayout(recovery_form)
        self.plot_consent = QCheckBox(
            '기존 플롯만 있는 선택 회차에 한해 실제 로컬 GGUF 본문 생성을 이번 1회 승인')
        self.plot_consent.setObjectName('autoBatchPlotOnlyModelConsent')
        root.addWidget(self.plot_consent)
        self.plot_start_button = QPushButton(
            '저장 플롯만 있는 회차의 미검수 AI 초고 생성')
        self.plot_start_button.setObjectName('autoBatchPlotOnlyStart')
        self.plot_start_button.clicked.connect(self.start_plot_only)
        root.addWidget(self.plot_start_button)
        self.plot_stop_button = QPushButton('플롯 초고 생성 중단 요청')
        self.plot_stop_button.setObjectName('autoBatchPlotOnlyStop')
        self.plot_stop_button.setEnabled(False)
        self.plot_stop_button.clicked.connect(self.stop_plot_only)
        root.addWidget(self.plot_stop_button)
        self.plot_editor = QPlainTextEdit()
        self.plot_editor.setObjectName('autoBatchPlotOnlyCandidate')
        self.plot_editor.setPlaceholderText(
            '실제 GGUF가 생성한 미검수 초고를 작가가 직접 읽고 수정합니다. '
            '별도 저장 승인 전에는 SQLite에 기록하지 않습니다.')
        root.addWidget(self.plot_editor)
        self.plot_export_consent = QCheckBox(
            '미저장 초고 전문을 새 로컬 JSON으로 보관하는 이번 1회를 승인')
        self.plot_export_consent.setObjectName('plotOnlyRecoveryExportConsent')
        root.addWidget(self.plot_export_consent)
        self.plot_export_button = QPushButton('미저장 초고 새 복구 파일로 보관')
        self.plot_export_button.setObjectName('plotOnlyRecoveryExport')
        self.plot_export_button.clicked.connect(self.export_plot_candidate)
        root.addWidget(self.plot_export_button)
        self.plot_import_consent = QCheckBox(
            '현재 빈 편집기에만 기존 복구 파일을 불러오는 이번 1회를 승인')
        self.plot_import_consent.setObjectName('plotOnlyRecoveryImportConsent')
        root.addWidget(self.plot_import_consent)
        self.plot_import_button = QPushButton('기존 복구 파일에서 미저장 초고 불러오기')
        self.plot_import_button.setObjectName('plotOnlyRecoveryImport')
        self.plot_import_button.clicked.connect(self.import_plot_candidate)
        root.addWidget(self.plot_import_button)
        self.plot_save_consent = QCheckBox(
            '현재 후보를 직접 검토했으며 기존 플롯 회차의 미검수 초고로만 저장 승인')
        self.plot_save_consent.setObjectName('autoBatchPlotOnlySaveConsent')
        root.addWidget(self.plot_save_consent)
        self.plot_save_button = QPushButton('작가 직접 검토한 플롯 회차 초고 저장')
        self.plot_save_button.setObjectName('autoBatchPlotOnlySave')
        self.plot_save_button.clicked.connect(self.save_plot_only)
        root.addWidget(self.plot_save_button)
        self.plot_discard_button = QPushButton('이 화면의 미저장 후보 직접 폐기')
        self.plot_discard_button.setObjectName('autoBatchPlotOnlyDiscard')
        self.plot_discard_button.clicked.connect(self.discard_plot_only)
        root.addWidget(self.plot_discard_button)
        self.plot_status = QLabel(
            '미완성 플롯 회차를 직접 선택하고 모델·분량을 승인하세요. '
            '기존 회차/장면/최종본은 자동 덮어쓰지 않습니다.')
        self.plot_status.setObjectName('autoBatchPlotOnlyStatus')
        self.plot_status.setWordWrap(True)
        root.addWidget(self.plot_status)
        for spin in (self.plot_episode, self.plot_target, self.plot_calls):
            spin.valueChanged.connect(
                lambda _value: self.plot_consent.setChecked(False))
        for field in ('executable', 'arguments'):
            self.authoring.fields[field].textChanged.connect(
                lambda _value: self.plot_consent.setChecked(False))
        self.plot_editor.textChanged.connect(
            lambda: self.plot_save_consent.setChecked(False))
        self.plot_editor.textChanged.connect(
            lambda: self.plot_export_consent.setChecked(False))

    def export_plot_candidate(self):
        if self.is_running():
            self.plot_status.setText('모델 집필 중에는 후보 파일을 저장하지 않습니다.')
            return
        approved = self.plot_export_consent.isChecked()
        self.plot_export_consent.setChecked(False)
        session, lease = self.authoring.session, self._plot_lease
        if (not approved or lease is None or session.store is None
                or session.path is None or session.project_id is None
                or self._plot_source_database != str(session.path)
                or str(session.project_id) != lease.project_id
                or self.plot_episode.value() != lease.episode):
            self.plot_status.setText('현재 작품/회차의 후보 복구 파일 생성을 다시 승인하세요.')
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, '새 로컬 복구 JSON 선택', '', 'JSON (*.json)')
        if not file_path:
            return
        try:
            export_unsaved_plot(session.store, lease, self.plot_editor.toPlainText(),
                                file_path, explicit_author_export=True)
        except (PlotOnlyRecoveryError, OSError, ValueError):
            self.plot_status.setText('복구 JSON 저장 불가: 원본 변경 또는 기존 파일/경로 확인 필요.')
            return
        self.plot_status.setText(
            '새 로컬 JSON에 미검수 초고를 보관했습니다. 원고 전문이 담긴 파일이므로 '
            '공유에 주의하세요. SQLite·최종본·출판 승인은 변경하지 않았습니다.')

    def import_plot_candidate(self):
        if self.is_running() or self._plot_lease is not None or self.plot_editor.toPlainText():
            self.plot_status.setText('이미 편집 중인 후보를 덮어쓰지 않습니다. 빈 상태에서만 복구하세요.')
            return
        approved = self.plot_import_consent.isChecked()
        self.plot_import_consent.setChecked(False)
        session = self.authoring.session
        if not approved or session.store is None or session.path is None or session.project_id is None:
            self.plot_status.setText('현재 작품 및 복구 작업을 직접 승인하세요.')
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, '기존 미저장 초고 JSON 선택', '', 'JSON (*.json)')
        if not file_path:
            return
        try:
            lease = begin_plot_only_draft(
                session.store, str(session.project_id), self.plot_episode.value())
            prose = import_unsaved_plot(
                session.store, lease, file_path, explicit_author_import=True)
        except (PlotOnlyRecoveryError, PlotOnlyDraftError, OSError, ValueError):
            self.plot_status.setText('복구 원고 무결성 또는 저장 플롯/원본 revision 불일치.')
            return
        if self.is_running() or self._plot_lease is not None or self.plot_editor.toPlainText():
            self.plot_status.setText('이미 편집 중인 후보를 덮어쓰지 않았습니다.')
            return
        self._plot_lease = lease
        self._plot_source_database = str(session.path)
        self.plot_editor.setPlainText(prose)
        self.plot_status.setText(
            f'{lease.episode}화 미검수 초고를 편집기에만 복구했습니다. '
            '검토 후 별도의 수동 저장 승인이 필요하며 출판 승인이 아닙니다.')

    def start_plot_only(self):
        if self.is_running():
            self.plot_status.setText('현재 진행 중인 실제 로컬 모델 호출이 끝나야 합니다.')
            return
        if self._plot_lease is not None and self.plot_editor.toPlainText().strip():
            self.plot_status.setText(
                '이전 미저장 초고가 있습니다. 먼저 직접 저장하거나 폐기하세요.')
            return
        approved = (self.plot_consent.isChecked()
                    and self.authoring.approved.isChecked())
        self.plot_consent.setChecked(False)
        self.authoring.approved.setChecked(False)
        session = self.authoring.session
        if (not approved or session.path is None or session.store is None
                or session.project_id is None):
            self.plot_status.setText('현재 작품·승인 로컬 모델을 각각 이번 1회 승인하세요.')
            return
        episode = self.plot_episode.value()
        try:
            lease = begin_plot_only_draft(
                session.store, str(session.project_id), episode)
            executable = self.authoring._text('executable').strip()
            arguments = tuple(shlex.split(self.authoring._text('arguments')))
            special = (Path(executable).name.casefold() == 'anf_local_model.exe'
                       and arguments[:1] == ('--gguf',))
            provider = LocalExecutableProvider(
                executable, arguments=arguments,
                timeout_seconds=1500 if special else
                450 if arguments[:1] == ('--gguf',) else 120,
                explicitly_allowed=True)
        except (PlotOnlyDraftError, LocalModelError, OSError, ValueError):
            self.plot_status.setText(
                '기존 플롯만 있는 회차·저장 원본·승인 모델을 다시 확인하세요.')
            return
        self._plot_lease = None
        self._plot_source_database = None
        self._plot_identity = (
            str(session.path), str(session.project_id), episode, lease)
        self.plot_editor.clear()
        self.plot_save_consent.setChecked(False)
        worker = PlotOnlyDraftWorker(
            session.path, str(session.project_id), episode, lease,
            provider, self.plot_target.value(), self.plot_calls.value(), self)
        self.plot_worker = worker
        worker.proposed.connect(self._plot_received)
        worker.failed.connect(self._plot_failed)
        worker.finished.connect(self._plot_finished)
        self.plot_start_button.setEnabled(False)
        self.plot_stop_button.setEnabled(True)
        self.start_button.setEnabled(False)
        self.plot_status.setText(
            f'{episode}화 기존 저장 플롯을 실제 로컬 GGUF로 집필 중. '
            'SQLite/기존 최종본/장면은 변경하지 않습니다.')
        worker.start()

    def stop_plot_only(self):
        if self.plot_worker is not None and self.plot_worker.isRunning():
            self.plot_worker.stop_requested.set()
            self.plot_status.setText(
                '중단 요청됨: 현재 GGUF 호출 종료 후 이미 작성된 미검수 후보를 표시합니다.')

    def _plot_received(self, proposal):
        session = self.authoring.session
        identity = self._plot_identity
        self._plot_identity = None
        if (identity is None or session.store is None or session.path is None
                or (str(session.path), str(session.project_id),
                    self.plot_episode.value(), proposal.lease) != identity
                or self.plot_editor.toPlainText().strip()):
            self.plot_status.setText(
                '작품·회차·편집 내용이 바뀌어 AI 후보를 표시하지 않았습니다.')
            return
        try:
            require_current_plot_only_lease(session.store, proposal.lease)
        except (PlotOnlyDraftError, OSError, ValueError):
            self.plot_status.setText(
                '모델 호출 중 원본 플롯이 변경되어 후보를 표시하지 않았습니다.')
            return
        self._plot_lease = proposal.lease
        self._plot_source_database = str(session.path)
        self.plot_editor.setPlainText(proposal.candidate)
        self.plot_status.setText(
            f'{proposal.lease.episode}화 실제 GGUF {proposal.model_calls}회 호출, '
            f'새 문단 {proposal.accepted_passages}개, '
            f'공백 제외 {proposal.resulting_nonspace_chars}자, '
            f'목표 부족 {proposal.remaining_nonspace_chars}자. '
            + ('작가 중단 요청 반영. ' if proposal.stopped_by_author else '')
            + '미검수 후보입니다. 직접 읽고 수정한 후 별도 저장 승인하세요. '
              '글자 수 도달은 품질/출판 합격이 아닙니다.')

    def _plot_failed(self, message):
        self._plot_identity = None
        self.plot_status.setText('플롯 회차 초고 생성 보류: ' + message)

    def _plot_finished(self):
        self.plot_start_button.setEnabled(True)
        self.plot_stop_button.setEnabled(False)
        self.start_button.setEnabled(self.worker is None)
        if self.plot_worker is not None:
            self.plot_worker.deleteLater()
            self.plot_worker = None

    def save_plot_only(self):
        if self.is_running():
            self.plot_status.setText('로컬 모델 호출 종료 후 직접 저장하세요.')
            return
        approved = self.plot_save_consent.isChecked()
        self.plot_save_consent.setChecked(False)
        session = self.authoring.session
        lease = self._plot_lease
        if (not approved or lease is None or session.store is None
                or session.path is None or session.project_id is None
                or str(session.project_id) != lease.project_id
                or self.plot_episode.value() != lease.episode):
            self.plot_status.setText(
                '현재 작품·회차의 미검수 후보를 직접 검토하고 저장 승인하세요.')
            return
        try:
            new_revision = save_plot_only_draft(
                session.store, lease, self.plot_editor.toPlainText(),
                explicit_author_save=True)
        except (PlotOnlyDraftError, OSError, ValueError, UnicodeError):
            self.plot_status.setText(
                '플롯·원고가 변경되었거나 초고 형식이 올바르지 않아 저장하지 않았습니다.')
            return
        self._plot_lease = None
        self._plot_source_database = None
        self.plot_status.setText(
            f'{lease.episode}화 작가 직접 승인으로 초고 저장 완료 '
            f'(revision {new_revision}). 기존 플롯·최종본 유지. '
            '문학 품질·출판 승인 아님. 다른 회차를 선택할 수 있습니다.')
        if hasattr(self.authoring, 'feature_workspace_hub'):
            self.authoring.feature_workspace_hub.refresh_visible()

    def discard_plot_only(self):
        if self.is_running():
            self.plot_status.setText('로컬 모델 호출 중에는 후보를 폐기하지 않습니다.')
            return
        self._plot_lease = None
        self._plot_identity = None
        self._plot_source_database = None
        self.plot_save_consent.setChecked(False)
        self.plot_editor.clear()
        self.plot_status.setText('이 화면의 미저장 후보를 직접 폐기했습니다. SQLite 변경 없음.')

    def _apply_actual_novel_preset(self, *_args):
        """Actual episode WRITING, not the separate AI planning preview."""
        target = self.actual_novel_preset.currentData()
        if type(target) is not int or not target:
            return
        if self.is_running():
            return
        self.consent.setChecked(False)
        self.through.setValue(target)
        self.status.setText(
            f'실제 장편 소설 {target}화까지 본문 생성 범위를 선택했습니다. '
            '기존에 저장한 회차는 덮어쓰지 않으며 새 회차만 실제 로컬 AI로 '
            '집필합니다. 회차 목표 분량과 저장 작품 목표를 확인한 다음 '
            '이번 실행을 별도로 승인하세요. '
            '품질 합격·검수·출판은 자동 처리하지 않습니다.')

    def _sync_actual_novel_preset(self, *_args):
        """Prevent a stale 250-episode label after manual range editing."""
        target = self.actual_novel_preset.currentData()
        if target and target != self.through.value():
            self.actual_novel_preset.blockSignals(True)
            self.actual_novel_preset.setCurrentIndex(0)
            self.actual_novel_preset.blockSignals(False)

    def preview_author_context_scope(self):
        """작가가 직접 누른 현재 1~N화 문맥 조회. 승인/모델 실행/저장 없음."""
        if self.is_running():
            self.context_scope_notice.setText(
                '진행 중인 로컬 집필이 끝난 후 작가 문맥을 다시 조회하세요.')
            return
        try:
            composer = getattr(self.authoring, 'author_context_composer_panel', None)
            if composer is None:
                raise AuthorContextEnvelopeError('기존 작가 문맥 화면 선택 필요')
            session = self.authoring.session
            store, project_id = session.required()
            if composer.scenes.value() != self.scenes.value():
                raise AuthorContextEnvelopeError('배치와 작가 문맥 장면 수가 다릅니다.')
            sources = composer._capture()
            plan = plan_author_context_scope(
                store, str(project_id), through_episode=self.through.value(),
                scenes_per_episode=self.scenes.value(), sources=sources)
            blocked = [str(row.episode) for row in plan.episodes
                       if row.status == 'CONTEXT_BLOCKED']
            if blocked:
                self.context_scope_notice.setText(
                    f'총 {plan.total}화: 기존 저장 {plan.existing}화, '
                    f'문맥 준비 {plan.ready}화, 추가 확인 {plan.blocked}화. '
                    f'미준비 회차 앞 12개: {", ".join(blocked[:12])}. '
                    '실제 모델 실행 전에 작가 기록을 직접 보완하세요.')
            else:
                self.context_scope_notice.setText(
                    f'총 {plan.total}화: 기존 저장 {plan.existing}화, '
                    f'문맥 조합 가능 {plan.ready}화. '
                    '문맥 준비 조회만 완료 · 실제 AI 집필/QC/출판은 NOT_RUN.')
        except (AuthorContextEnvelopeError, ValueError, OSError):
            self.context_scope_notice.setText(
                '현재 작품·선택 기록·장면 수가 일치하지 않습니다. '
                '작가 통합 문맥 화면에서 다시 직접 선택하세요.')

    def clear_explicit_scene_resume(self):
        if self._explicit_resume_choice is not None:
            self._explicit_resume_choice = None
            self._resume_project_identity = None
            self.resume_notice.setText('직접 선택한 임시 장면 재개: 설정 변경으로 선택 해제')
            self.consent.setChecked(False)

    def set_explicit_scene_resume(self, choice, project_identity):
        if (type(choice) is not SceneStageChoice or self.is_running()
                or not self.scene_checkpoint_opt_in.isChecked()
                or type(project_identity) is not tuple
                or choice.episode > self.through.value()
                or choice.stage > self.scenes.value()):
            raise SceneCheckpointError('장면 재개 범위·장면 수를 기존 배치에서 직접 확인하세요.')
        self._explicit_resume_choice = choice
        self._resume_project_identity = project_identity
        self.consent.setChecked(False)
        self.resume_notice.setText(
            f'{choice.episode}화 {choice.stage}단계 선택: 동일 모델·원고·계획·승인 지문일 때만 재사용. '
            '다음 시작 전에 새 실행 동의가 필요합니다.')

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
        self.clear_explicit_scene_resume()
        self.reference_paths = tuple(selected)
        self.reference_list.clear()
        self.reference_list.addItems([display_filename(path) for path in self.reference_paths])
        self.reference_notice.setText(
            f'참고작 {len(selected)}개 선택 · 승인 후 로컬 분석/직접 비교 · 원문 AI 입력 없음')
        self.consent.setChecked(False)

    def clear_reference_files(self):
        if self.is_running():
            return
        self.clear_explicit_scene_resume()
        self.reference_paths = ()
        self.reference_list.clear()
        self.reference_notice.setText('참고작 미선택: 전수 유사성 검사 NOT_RUN')
        self.consent.setChecked(False)

    def _capture_ai_episode_writing_guidance(self):
        """This never launches a model; it captures the already-generated plan."""
        if not self.use_ai_episode_guide.isChecked():
            return None
        panel = getattr(self.authoring, 'author_ai_episode_planning_panel', None)
        if panel is None or panel.is_running():
            raise AuthorAiNovelGuidanceError(
                '먼저 기존 로컬 AI 회차별 기획 화면에서 1~N화를 생성하세요.')
        session = self.authoring.session
        if session.project_id is None or session.path is None:
            raise AuthorAiNovelGuidanceError('집필 작품이 선택되지 않았습니다.')
        project_id = str(session.project_id)
        identity = (str(session.path), project_id)
        if (panel._identity != identity or panel._source is None
                or panel._result is None):
            raise AuthorAiNovelGuidanceError(
                '현재 작품의 미검수 AI 회차 기획 결과를 다시 선택하세요.')
        require_idle_authoring(self.authoring, project_id)
        guide = prepare_author_ai_novel_guidance(
            panel._source, panel._result, project_id=project_id,
            through_episode=self.through.value())
        require_current_author_ai_novel_guidance(
            guide, session.store, session.path, project_id,
            self.through.value())
        return guide

    def _bind_approval(self, checked):
        # Bind the author-initiated consent to the exact existing project,
        # local executable, selected references, and target parameters.
        session = self.authoring.session
        self._approved_project = (
            (str(session.path), str(session.project_id))
            if checked and session.path is not None
            and session.project_id is not None else None)
        self._launch_lease = None
        self._approved_ai_writing_guidance = None
        if checked:
            try:
                # The author approves both the model batch and the exact
                # selected frozen AI episode plan. Changing either revokes it.
                plan = self._capture_ai_episode_writing_guidance()
                self._launch_lease = capture_launch_lease(
                    **self._launch_configuration())
                self._approved_ai_writing_guidance = plan
            except (LaunchLeaseError, AuthorAiNovelGuidanceError,
                    LocalHandoffError, OSError, ValueError):
                self.consent.setChecked(False)
                self.status.setText(
                    '승인 대상 모델·작품·참고작을 확인할 수 없습니다. 다시 선택하세요.')

    def _selected_metric_keys(self) -> tuple[str, ...]:
        """작가가 허용한 통계 항목만 실제 집필 문맥에 전달."""
        return tuple(key for key in FEATURE_KEYS if self.metric_checks[key].isChecked())

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
            'reference_metric_keys': self._selected_metric_keys(),
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
        return ((self.worker is not None and self.worker.isRunning())
                or (self.plot_worker is not None and self.plot_worker.isRunning()))

    def request_stop(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop_requested.set()
            self.status.setText('중단 요청: 실행 중인 로컬 모델 호출이 완료되면 중단합니다.')

    def start_batch(self):
        if self.is_running():
            return
        self._screen_summary = None
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
        # Check the saved user selection *again* immediately before
        # consuming a one-shot model approval. The plan display can change
        # after consent without the batch form's controls changing.
        try:
            new_guidance = self._capture_ai_episode_writing_guidance()
            old_guidance = self._approved_ai_writing_guidance
            if ((new_guidance is None) != (old_guidance is None)
                    or (new_guidance is not None
                        and new_guidance.fingerprint != old_guidance.fingerprint)):
                raise AuthorAiNovelGuidanceError(
                    'AI 회차 기획 후보가 승인 이후 변경됐습니다.')
        except (AuthorAiNovelGuidanceError, LocalHandoffError, ValueError, OSError):
            self.consent.setChecked(False)
            self.status.setText('AI 회차 기획 선택·작품·미저장 원고가 바뀌었습니다. 다시 승인하세요.')
            return
        explicit_choice = self._explicit_resume_choice
        if explicit_choice is not None and (
                self._resume_project_identity !=
                (str(session.path), str(session.project_id))
                or not self.scene_checkpoint_opt_in.isChecked()
                or explicit_choice.episode > self.through.value()
                or explicit_choice.stage > self.scenes.value()):
            self.consent.setChecked(False)
            self.status.setText('선택한 장면과 현재 배치 설정이 다릅니다. 다시 직접 선택하세요.')
            return
        # Bind stage reuse only to the freshly verified, one-run author approval.
        checkpoint_fingerprint = (
            self._launch_lease.fingerprint
            if self.scene_checkpoint_opt_in.isChecked() else None)
        # Consume the consent and one-run stage selection before worker creation.
        self.consent.setChecked(False)
        self._explicit_resume_choice = None
        self._resume_project_identity = None
        self.resume_notice.setText('직접 선택한 임시 장면 재개: 이번 실행에만 전달됨')
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
                    and (composer.episode.value() != self.through.value()
                         or composer.scenes.value() != self.scenes.value())):
                raise AuthorContextEnvelopeError(
                    '장편 문맥 미리보기 회차·장면 수와 현재 배치 설정이 다릅니다.')
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
            reference_metric_keys=self._selected_metric_keys(),
            catalog_path=(default_local_catalog_path() if self.reference_paths else None),
            batch_receipt=receipt,
            scene_checkpoint_root=checkpoint_root,
            scene_checkpoint_lease=checkpoint_fingerprint,
            context_sources=selected_context_sources,
            explicit_resume_choice=explicit_choice,
            episode_writing_guidance=new_guidance,
            full_text_screen=self.scan_after_batch.isChecked())
        self.worker.progress_changed.connect(
            lambda num, stage: self.status.setText(f'{num}화: {stage}'))
        self.worker.full_text_screen_finished.connect(self._record_full_text_screen)
        self.worker.finished_report.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._cleanup)
        self.start_button.setEnabled(False)
        self.plot_start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText('로컬 모델 연속 집필 시작. 저장된 회차는 건너뜁니다.')
        self.worker.start()

    def _record_full_text_screen(self, report):
        self._screen_summary = (
            None if report is None else (
                report.through_episode, report.missing_saved_text,
                report.format_warnings, report.exact_reuse_warnings))

    def _finished(self, result):
        self.status.setText(
            f'작업 완료: 새 회차 {len(result.created_episodes)}개, '
            f'이미 존재하는 회차 {len(result.skipped_existing)}개, '
            f'로컬 AI 실행 {result.local_model_invocations}회. '
            f'검수 필수 {len(result.review_required_episodes)}개. '
            f'저장 초고의 문체 규칙 범위 검사 {result.style_scope_checked_episodes}화'
            '(WARN/FAIL 기록, 품질 합격 아님). '
            f'실제 로컬 모델 장면 이어쓰기 {result.continuation_model_calls}회. '
            + ('중단 요청 반영됨.' if result.stopped else '비공개 초고만 저장됨.')
            + (f' 저장된 본문 {self._screen_summary[0]}화 범위: '
               f'누락 {self._screen_summary[1]}화, '
               f'형식·분량 검토 {self._screen_summary[2]}화, '
               f'이전 회차 동일 문장 검토 {self._screen_summary[3]}화. '
               '(문학 품질·저작권 합격 아님).'
               if self._screen_summary is not None else
               (' 후속 본문 근거 검사 미선택 또는 미완료.'
                if not result.stopped else '')))
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
        self.plot_start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
