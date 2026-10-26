"""Existing Windows GUI: explicit in-memory manual draft rewrite."""
from __future__ import annotations
import shlex
from pathlib import Path
from threading import Event
from PySide6.QtCore import QThread, Signal
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.local_models import LocalExecutableProvider
from ai_novel_factory.local_rewrite_proposal import (
    LocalRewriteProposalError, propose_rewrite_of_saved_draft,
)
from ai_novel_factory.local_selected_rewrite import (
    SelectedRewriteError, SelectedRewriteProposal, propose_selected_rewrite,
)
from ai_novel_factory.local_draft_expansion import (
    DraftExpansionError, DraftExpansionProposal, propose_saved_draft_expansion,
)
from ai_novel_factory.local_rewrite_recovery import (
    LocalRewriteRecoveryError, export_unsaved_rewrite, import_unsaved_rewrite,
)
from .author_navigation_contract import _busy, _unsaved
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QSpinBox, QFormLayout,
    QFileDialog,
)
from ai_novel_factory.manual_rewrite_workspace import (
    begin_manual_rewrite, commit_manual_rewrite,
    preview_manual_rewrite, require_current_manual_rewrite_preview,
)


class LocalRewriteWorker(QThread):
    proposed = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path, lease, provider, direction, parent=None):
        super().__init__(parent)
        self.database_path = str(database_path)
        self.lease = lease
        self.provider = provider
        self.direction = direction

    def run(self):
        try:
            proposal = propose_rewrite_of_saved_draft(
                self.database_path, self.lease.project_id,
                self.lease.episode, self.provider,
                expected_lease=self.lease, explicit_author_model_run=True,
                author_direction=self.direction)
            self.proposed.emit(proposal)
        except (LocalRewriteProposalError, ValueError, OSError, UnicodeError):
            self.failed.emit(
                '로컬 AI 수정 후보 생성에 실패했거나 저장 원고가 변경됐습니다. '
                '원본·최종본은 그대로 유지됩니다.')
        except BaseException:
            self.failed.emit(
                '로컬 모델 실행을 마칠 수 없었습니다. 원본·최종본은 유지됩니다.')


class SelectedRewriteWorker(QThread):
    """Actual GGUF call for one author-selected span, never an auto-save."""
    proposed = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path, lease, provider, direction,
                 selection_start, selection_end, parent=None):
        super().__init__(parent)
        self.database_path = str(database_path)
        self.lease = lease
        self.provider = provider
        self.direction = direction
        self.selection_start = selection_start
        self.selection_end = selection_end

    def run(self):
        try:
            result = propose_selected_rewrite(
                self.database_path, self.lease.project_id,
                self.lease.episode, self.provider,
                expected_lease=self.lease,
                selection_start=self.selection_start,
                selection_end=self.selection_end,
                explicit_author_model_run=True,
                author_direction=self.direction)
            self.proposed.emit(result)
        except (SelectedRewriteError, ValueError, OSError, UnicodeError):
            self.failed.emit(
                '선택 구간 GGUF 수정 후보를 생성하지 못했습니다. '
                '원고·최종본은 변경되지 않았습니다.')
        except BaseException:
            self.failed.emit(
                '로컬 모델 작업이 중단됐습니다. 원고는 그대로 유지됩니다.')


class DraftExpansionWorker(QThread):
    """Bounded local-GGUF continuation; stop applies between model calls."""
    proposed = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path, lease, provider, direction,
                 target, max_calls, parent=None):
        super().__init__(parent)
        self.database_path = str(database_path)
        self.lease = lease
        self.provider = provider
        self.direction = direction
        self.target = target
        self.max_calls = max_calls
        self._stop_event = Event()

    def request_stop(self):
        self._stop_event.set()

    def run(self):
        try:
            result = propose_saved_draft_expansion(
                self.database_path, self.lease.project_id,
                self.lease.episode, self.provider,
                expected_lease=self.lease,
                target_nonspace_chars=self.target,
                max_model_calls=self.max_calls,
                explicit_author_model_run=True,
                author_direction=self.direction,
                should_stop=self._stop_event.is_set)
            self.proposed.emit(result)
        except (DraftExpansionError, ValueError, OSError, UnicodeError):
            self.failed.emit(
                '저장 초고를 이어 쓸 새 GGUF 본문이 없거나 원고가 변경됐습니다. '
                '기존 원고·최종본은 그대로 유지됩니다.')
        except BaseException:
            self.failed.emit(
                '로컬 모델 이어쓰기를 마치지 못했습니다. 원고는 유지됩니다.')


def _qt_cursor_to_codepoint(text: str, qt_position: int) -> int:
    """QTextCursor counts UTF-16 units; Python slices Unicode codepoints."""
    if type(qt_position) is not int or qt_position < 0:
        raise ValueError('invalid cursor')
    data = text.encode('utf-16-le')
    if qt_position * 2 > len(data):
        raise ValueError('cursor outside manuscript')
    return len(data[:qt_position * 2].decode('utf-16-le'))


class ManualRewritePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('저장된 초고 수동 재작성 · 기존 최종본 보호', parent)
        self.authoring = authoring
        self.lease = None
        self.preview_snapshot = None
        self._rewrite_worker = None
        self._model_identity = None
        self._saved_before_model = None
        self._saved_author_direction = None
        root = QVBoxLayout(self)
        label = QLabel('현재 회차 저장 초고를 별도 편집합니다. 직접 저장 버튼 전에는 SQLite 변경 없음. '
                       '최종 원고는 덮어쓰지 않으며 재작성 후 검수/품질 판정은 다시 필요합니다.')
        label.setWordWrap(True)
        root.addWidget(label)
        load = QPushButton('현재 저장 초고를 재작성 편집기로 불러오기')
        self.load_button = load
        load.setObjectName('manualRewriteLoad')
        load.clicked.connect(self.load_current)
        root.addWidget(load)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName('manualRewriteEditor')
        self.editor.setPlaceholderText('작가가 직접 수정한 초고를 입력합니다.')
        root.addWidget(self.editor)
        self.author_direction = QPlainTextEdit()
        self.author_direction.setObjectName('manualRewriteAuthorDirection')
        self.author_direction.setMaximumHeight(95)
        self.author_direction.setPlaceholderText(
            '작가가 직접 지정할 수정 방향·유지할 장면과 인물·말투 (최대 2000자)')
        root.addWidget(QLabel('현재 AI 재작성 요청에만 적용할 작가 직접 지시'))
        root.addWidget(self.author_direction)
        self.ai_consent = QCheckBox(
            '현재 저장 초고를 이번 1회 신뢰한 로컬 GGUF로만 수정 제안하도록 승인 '
            '(작업별 최대 호출은 별도 표시, 자동 저장·품질 합격 없음)')
        self.ai_consent.setObjectName('manualRewriteLocalAiConsent')
        root.addWidget(self.ai_consent)
        self.ai_button = QPushButton('현재 회차 AI 재작성 미검수 후보 생성 (로컬)')
        self.ai_button.setObjectName('manualRewriteLocalAiPropose')
        self.ai_button.clicked.connect(self.propose_ai_rewrite)
        root.addWidget(self.ai_button)
        self.selected_ai_button = QPushButton(
            '초고에서 드래그한 100~6000자 구간만 로컬 GGUF로 재작성')
        self.selected_ai_button.setObjectName('manualRewriteSelectedPassageAi')
        self.selected_ai_button.clicked.connect(self.propose_selected_ai_rewrite)
        root.addWidget(self.selected_ai_button)
        expansion_controls = QFormLayout()
        self.expansion_target = QSpinBox()
        self.expansion_target.setRange(1000, 50000)
        self.expansion_target.setSingleStep(500)
        self.expansion_target.setValue(5000)
        self.expansion_target.setObjectName('manualRewriteExpansionTarget')
        expansion_controls.addRow('회차 목표 공백 제외 글자 수', self.expansion_target)
        self.expansion_calls = QSpinBox()
        self.expansion_calls.setRange(1, 12)
        self.expansion_calls.setValue(8)
        self.expansion_calls.setObjectName('manualRewriteExpansionCalls')
        expansion_controls.addRow('이번 승인 최대 실제 GGUF 호출', self.expansion_calls)
        root.addLayout(expansion_controls)
        self.expand_ai_button = QPushButton(
            '현재 저장 초고의 마지막부터 실제 GGUF 소설 이어쓰기 (원문 유지)')
        self.expand_ai_button.setObjectName('manualRewriteExpandDraftAi')
        self.expand_ai_button.clicked.connect(self.propose_ai_expand)
        root.addWidget(self.expand_ai_button)
        self.stop_expand_button = QPushButton(
            '이어쓰기 중단 요청 (현재 로컬 모델 호출 종료 후 중단)')
        self.stop_expand_button.setObjectName('manualRewriteStopExpansion')
        self.stop_expand_button.setEnabled(False)
        self.stop_expand_button.clicked.connect(self.stop_ai_expand)
        root.addWidget(self.stop_expand_button)
        self.recovery_save_consent = QCheckBox(
            '현재 미저장 재작성·이어쓰기 후보를 새 로컬 복구 파일에 보관하는 이번 1회 승인')
        self.recovery_save_consent.setObjectName('manualRewriteRecoveryExportConsent')
        root.addWidget(self.recovery_save_consent)
        self.recovery_save_button = QPushButton(
            '미저장 후보 복구 파일로 저장 (SQLite·최종본 미변경)')
        self.recovery_save_button.setObjectName('manualRewriteRecoveryExport')
        self.recovery_save_button.clicked.connect(self.export_unsaved_candidate)
        root.addWidget(self.recovery_save_button)
        self.recovery_load_consent = QCheckBox(
            '기존 복구 파일의 후보를 현재 편집기로만 불러오는 이번 1회 승인')
        self.recovery_load_consent.setObjectName('manualRewriteRecoveryImportConsent')
        root.addWidget(self.recovery_load_consent)
        self.recovery_load_button = QPushButton(
            '미저장 후보 복구 파일 불러오기 (원본 revision 일치 시에만)')
        self.recovery_load_button.setObjectName('manualRewriteRecoveryImport')
        self.recovery_load_button.clicked.connect(self.restore_unsaved_candidate)
        root.addWidget(self.recovery_load_button)
        root.addWidget(QLabel(
            '복구 JSON에는 개인 원고 전체가 들어갑니다. 신뢰하는 로컬 폴더에만 보관하세요. '
            '복구는 편집기 입력일 뿐 저장·검수·출판 승인이 아닙니다.'))
        self.preview_button = QPushButton('저장 전 원본·수정 초고 변경 위치 직접 비교')
        self.preview_button.setObjectName('manualRewritePreview')
        self.preview_button.clicked.connect(self.preview_current)
        root.addWidget(self.preview_button)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setObjectName('manualRewriteDiffTable')
        self.preview_table.setHorizontalHeaderLabels(('변경 종류', '기존 초고 줄', '수정 초고 줄'))
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setMaximumHeight(200)
        root.addWidget(self.preview_table)
        self.numeric_evidence = QTableWidget(0, 3)
        self.numeric_evidence.setObjectName('manualRewriteActualCandidateComparison')
        self.numeric_evidence.setHorizontalHeaderLabels((
            '실제 원고 비교 항목', '저장된 이전 초고', '새 AI 후보'))
        self.numeric_evidence.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self.numeric_evidence.setMaximumHeight(240)
        root.addWidget(self.numeric_evidence)
        self.numeric_status = QLabel(
            '미검수 AI 후보의 실제 분량·한글 형식·과거 회차 동일 문장 비교는 아직 없습니다.')
        self.numeric_status.setWordWrap(True)
        self.numeric_status.setObjectName('manualRewriteCandidateComparisonStatus')
        root.addWidget(self.numeric_status)
        self.preview_status = QLabel('NOT_RUN: 작가가 직접 비교를 눌러야 합니다.')
        self.preview_status.setWordWrap(True)
        root.addWidget(self.preview_status)
        self.consent = QCheckBox('현재 회차의 초고만 수정 저장하며 재검수해야 함을 확인합니다')
        self.consent.setObjectName('manualRewriteConsent')
        root.addWidget(self.consent)
        save = QPushButton('수동 재작성 초고 저장 (기존 최종본 유지)')
        self.save_button = save
        save.setObjectName('manualRewriteSave')
        save.clicked.connect(self.save_current)
        root.addWidget(save)
        self.final_handoff = QPushButton(
            '저장된 초고를 기존 최종본 편집기로 가져오기 (미저장·검수 별도)')
        self.final_handoff.setObjectName('manualRewriteToFinalEditor')
        self.final_handoff.clicked.connect(self.handoff_saved_draft_to_final)
        root.addWidget(self.final_handoff)
        self.status = QLabel('재작성 미시작')
        self.status.setObjectName('manualRewriteStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.editor.textChanged.connect(self.invalidate_preview)
        self.editor.textChanged.connect(lambda: self.ai_consent.setChecked(False))
        self.author_direction.textChanged.connect(
            lambda: self.ai_consent.setChecked(False))

    def invalidate_preview(self, *_args):
        self.preview_snapshot = None
        self.numeric_evidence.setRowCount(0)
        self.numeric_status.setText(
            '내용이 변경되어 이전 AI 후보 수치 비교 결과는 무효입니다. '
            '새로운 모델 후보를 직접 생성해야 비교합니다.')
        self.preview_table.setRowCount(0)
        self.consent.setChecked(False)
        self.preview_status.setText('수정 초고 변경 또는 미조회: 다시 직접 비교하세요.')

    def preview_current(self):
        session = self.authoring.session
        lease = self.lease
        self.invalidate_preview()
        if (lease is None or session.store is None
                or session.project_id != lease.project_id
                or session.episode_number != lease.episode):
            self.preview_status.setText('현재 작품·회차의 저장 초고를 다시 불러오세요.')
            return
        try:
            snapshot = preview_manual_rewrite(
                session.store, lease, self.editor.toPlainText())
        except (ValueError, OSError, UnicodeError):
            self.preview_status.setText('초고 변경 또는 입력 형식을 확인하세요. 저장·검수하지 않았습니다.')
            return
        self.preview_snapshot = snapshot
        labels = {'replace': '수정', 'insert': '추가', 'delete': '삭제'}
        self.preview_table.setRowCount(min(len(snapshot.changed_blocks), 100))
        for index, (kind, old_start, old_end, new_start, new_end) in enumerate(
                snapshot.changed_blocks[:100]):
            for column, value in enumerate((
                    labels.get(kind, '변경'),
                    f'{old_start}~{old_end}', f'{new_start}~{new_end}')):
                self.preview_table.setItem(index, column, QTableWidgetItem(value))
        if not snapshot.details_available:
            detail = '줄 수가 많아 변경 위치 목록 생략 · 전체 초고 직접 검수 필요'
        elif len(snapshot.changed_blocks) > 100:
            detail = f'변경 {len(snapshot.changed_blocks)}구간 중 앞 100구간 표시'
        else:
            detail = f'변경 {len(snapshot.changed_blocks)}구간 표시'
        self.preview_status.setText(
            f'{lease.episode}화 원본 {snapshot.before_characters}자 → '
            f'수정 {snapshot.after_characters}자 · {detail}. '
            '비교는 품질 합격·QC PASS·출판 승인 아님. 직접 저장은 별도입니다.')

    def invalidate(self, *_args):
        self.ai_consent.setChecked(False)
        self.recovery_save_consent.setChecked(False)
        self.recovery_load_consent.setChecked(False)
        self.lease = None
        self.invalidate_preview()
        self.editor.clear()
        self.consent.setChecked(False)
        self.status.setText('현재 회차를 다시 불러와야 합니다.')

    def load_current(self):
        if self.is_ai_running():
            self.status.setText('로컬 AI 수정 후보 생성 중입니다. 원고를 바꾸지 않습니다.')
            return
        self.invalidate()
        session = self.authoring.session
        if not session.store or not session.project_id or not session.episode_number:
            self.status.setText('먼저 작품과 회차를 선택하세요.')
            return
        try:
            lease, draft = begin_manual_rewrite(
                session.store, session.project_id, session.episode_number)
        except (ValueError, OSError):
            self.status.setText('현재 저장 초고를 불러오지 못했습니다.')
            return
        self.editor.setPlainText(draft)
        self.lease = lease
        self.status.setText(f'{lease.episode}화 저장 초고를 편집 중 · 미저장')

    def export_unsaved_candidate(self):
        """Explicit new-file backup of an unsaved candidate; never SQLite."""
        if self.is_ai_running():
            self.status.setText('로컬 AI 작업 중에는 후보를 내보내지 않습니다.')
            return
        approved = self.recovery_save_consent.isChecked()
        self.recovery_save_consent.setChecked(False)
        session, lease = self.authoring.session, self.lease
        if (not approved or lease is None or session.store is None
                or session.project_id != lease.project_id
                or session.episode_number != lease.episode
                or _busy(self.authoring) or _unsaved(self.authoring)):
            self.status.setText('현재 회차를 열고 이번 복구 파일 저장을 직접 승인하세요.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '미저장 초고 후보 복구 JSON 새 파일',
            f'AI_NOVEL_{lease.episode:04d}_unsaved_rewrite.json',
            'AI NOVEL 복구 JSON (*.json)')
        if not path:
            self.status.setText('복구 파일 저장을 취소했습니다. 원본은 유지됩니다.')
            return
        try:
            receipt = export_unsaved_rewrite(
                session.store, lease, self.editor.toPlainText(),
                path, explicit_author_export=True)
        except (LocalRewriteRecoveryError, ValueError, OSError, UnicodeError):
            self.status.setText(
                '복구 파일을 새로 저장하지 못했습니다. 기존 파일 덮어쓰기·'
                'SQLite 저장은 수행하지 않았습니다.')
            return
        self.status.setText(
            f'{receipt.episode}화 미저장 수정 후보 {receipt.candidate_chars}자 '
            '로컬 JSON 새 파일로 별도 보관. SQLite·최종본 변경 없음. '
            '복구 JSON은 개인 원고이므로 외부에 공유하지 마세요.')

    def restore_unsaved_candidate(self):
        """Load only if the current editor has no unsaved conflicting edits."""
        if self.is_ai_running():
            self.status.setText('로컬 AI 작업 중에는 복구 후보를 불러오지 않습니다.')
            return
        approved = self.recovery_load_consent.isChecked()
        self.recovery_load_consent.setChecked(False)
        session, lease = self.authoring.session, self.lease
        if (not approved or lease is None or session.store is None
                or session.project_id != lease.project_id
                or session.episode_number != lease.episode
                or _busy(self.authoring) or _unsaved(self.authoring)):
            self.status.setText('현재 저장 초고와 이번 복구 파일 불러오기를 승인하세요.')
            return
        try:
            latest, saved = begin_manual_rewrite(
                session.store, lease.project_id, lease.episode)
            if latest != lease or self.editor.toPlainText() != saved:
                raise ValueError('unsaved editor content or stale lease')
        except (ValueError, OSError):
            self.status.setText(
                '현재 편집기에 다른 미저장 내용이 있거나 저장 원고가 변경됐습니다. '
                '후보를 덮어쓰지 않습니다.')
            return
        path, _ = QFileDialog.getOpenFileName(
            self, '기존 미저장 원고 복구 JSON 선택', '',
            'AI NOVEL 복구 JSON (*.json)')
        if not path:
            self.status.setText('복구 파일 불러오기를 취소했습니다.')
            return
        try:
            recovered = import_unsaved_rewrite(
                session.store, lease, path, explicit_author_import=True)
            # A second check prevents a changed project from receiving stale
            # text after the file dialog. The actual save will check again.
            latest, now_saved = begin_manual_rewrite(
                session.store, lease.project_id, lease.episode)
            if (latest != lease or now_saved != saved
                    or self.editor.toPlainText() != saved):
                raise ValueError('source changed during import')
        except (LocalRewriteRecoveryError, ValueError, OSError, UnicodeError):
            self.status.setText(
                '복구 파일 무결성·작품·회차·revision이 일치하지 않아 '
                '편집기를 변경하지 않았습니다.')
            return
        self.editor.setPlainText(recovered.candidate_text)
        self.invalidate_preview()
        self.status.setText(
            f'{recovered.episode}화 미저장 후보 '
            f'{len(recovered.candidate_text)}자 편집기에만 복구. '
            '원본·최종본·SQLite는 그대로입니다. 직접 검수·비교 후 별도 저장하세요.')

    def save_current(self):
        if self.is_ai_running():
            self.status.setText('로컬 AI 수정 제안이 끝나야 직접 저장할 수 있습니다.')
            return
        session = self.authoring.session
        lease = self.lease
        if (lease is None or session.store is None or session.project_id != lease.project_id
                or session.episode_number != lease.episode or not self.consent.isChecked()):
            self.status.setText('현재 회차와 저장 승인을 다시 확인해야 합니다.')
            return
        self.consent.setChecked(False)
        try:
            if self.preview_snapshot is not None:
                require_current_manual_rewrite_preview(
                    self.preview_snapshot, session.store, lease,
                    self.editor.toPlainText())
            revision = commit_manual_rewrite(
                session.store, lease, self.editor.toPlainText(), explicit_author_save=True)
        except (ValueError, OSError):
            self.status.setText('원고 변경 또는 저장 실패. 기존 최종본을 유지했습니다.')
            self.lease = None
            return
        self.lease = None
        self.invalidate_preview()
        self.authoring._invalidate_author_review_snapshots()
        self.authoring._sync()
        self.status.setText(f'{lease.episode}화 초고 revision {revision} 저장 · 검수/검사 재실행 필요')

    def handoff_saved_draft_to_final(self):
        """작가가 별도 클릭할 때만 저장 초고를 기존 최종본 편집기에 복사한다.

        이 작업은 SQLite에 쓰지 않는다. 이미 저장된 최종본이나 편집 중인
        최종본 입력을 덮어쓰지 않으며, 작가 검수·저장·출판을 승인하지 않는다.
        """
        session = self.authoring.session
        if (session.store is None or session.project_id is None
                or session.episode_number is None):
            self.status.setText('기존 작품과 저장된 회차를 먼저 선택하세요.')
            return
        if (self.authoring.is_generating()
                or self.authoring.auto_panel.is_running()):
            self.status.setText('로컬 AI 집필 중에는 최종본 편집기로 이동하지 않습니다.')
            return
        try:
            # The currently selected saved chapter, not a stale rewrite
            # preview, is the only source for this explicit handoff.
            lease, draft = begin_manual_rewrite(
                session.store, session.project_id, session.episode_number)
            current = session.store.get_episode(lease.project_id, lease.episode)
            if current.final_text.strip():
                raise ValueError('기존 최종본은 덮어쓸 수 없습니다.')
            if self.authoring._text('final_text').strip():
                raise ValueError('최종본 편집기의 미저장 입력을 덮어쓸 수 없습니다.')
            # A different, unsaved rewrite in this panel must be saved
            # deliberately before it can be used as the final editor source.
            if (self.lease is not None
                    and (self.lease != lease
                         or self.editor.toPlainText() != draft)):
                raise ValueError('수동 재작성 중인 미저장 초고를 먼저 저장하세요.')
            # Another editor could have changed the stored draft between
            # the two reads. Do not carry a stale copy into the final field.
            current_lease, current_draft = begin_manual_rewrite(
                session.store, session.project_id, session.episode_number)
            if current_lease != lease or current_draft != draft:
                raise ValueError('원고가 변경되어 다시 불러와야 합니다.')
        except (ValueError, OSError):
            self.status.setText(
                '원고 변경·기존 최종본·미저장 편집을 확인하세요. 아무것도 저장하지 않았습니다.')
            return
        self.authoring.final_reviewed.setChecked(False)
        self.authoring.final_quality_ack.setChecked(False)
        self.authoring._set('final_text', draft)
        self.authoring.fields['final_text'].setFocus()
        self.status.setText(
            f'{lease.episode}화 저장 초고 {len(draft)}자를 기존 최종본 편집기로만 복사했습니다. '
            '아직 SQLite에 저장되지 않았습니다. 작가가 직접 읽고 수정한 뒤 '
            '기존 최종본 검수 체크와 별도 저장 버튼을 눌러야 합니다.')


    def is_ai_running(self):
        return (self._rewrite_worker is not None
                and self._rewrite_worker.isRunning())

    def _ai_set_running(self, running):
        for button in (self.load_button, self.ai_button, self.selected_ai_button,
                       self.expand_ai_button, self.preview_button,
                       self.recovery_save_button, self.recovery_load_button,
                       self.save_button, self.final_handoff):
            button.setEnabled(not running)
        self.expansion_target.setEnabled(not running)
        self.expansion_calls.setEnabled(not running)
        self.stop_expand_button.setEnabled(
            running and isinstance(self._rewrite_worker, DraftExpansionWorker))
        self.editor.setReadOnly(running)
        self.author_direction.setReadOnly(running)

    def propose_ai_rewrite(self):
        """One local model invocation; no source or final SQLite write."""
        if self.is_ai_running():
            return
        allowed = (self.ai_consent.isChecked()
                   and self.authoring.approved.isChecked())
        self.ai_consent.setChecked(False)
        self.authoring.approved.setChecked(False)
        session = self.authoring.session
        lease = self.lease
        if (not allowed or lease is None or session.store is None
                or session.path is None
                or str(session.project_id) != lease.project_id
                or session.episode_number != lease.episode
                or _busy(self.authoring) or _unsaved(self.authoring)):
            self.status.setText(
                '저장된 동일 원고를 먼저 불러오고, 이번 1회 AI 제안과 '
                '해당 로컬 실행 파일을 각각 승인해야 합니다.')
            return
        try:
            latest, saved = begin_manual_rewrite(
                session.store, lease.project_id, lease.episode)
            if (latest != lease or self.editor.toPlainText() != saved
                    or session.store.get_episode(lease.project_id,
                                                 lease.episode).final_text.strip()):
                raise ValueError('unsaved/stale')
            direction = self.author_direction.toPlainText()
            if (len(direction) > 2000 or '\x00' in direction
                    or any(ord(ch) < 32 and ch not in '\n\r\t'
                           for ch in direction)):
                raise ValueError('invalid direction')
            executable = self.authoring._text('executable').strip()
            args = tuple(shlex.split(self.authoring._text('arguments')))
            special = (Path(executable).name.casefold() == 'anf_local_model.exe'
                       and args[:1] == ('--gguf',))
            provider = LocalExecutableProvider(
                executable, arguments=args,
                timeout_seconds=1500 if special else 450 if args[:1] == ('--gguf',)
                else 120, explicitly_allowed=True)
        except (ValueError, OSError):
            self.status.setText(
                '저장 원고·최종본·승인한 로컬 모델 경로를 확인하세요. '
                '수정 후보를 실행하지 않았습니다.')
            return
        self._model_identity = (
            str(session.path), lease.project_id, lease.episode, lease)
        self._saved_before_model = saved
        self._saved_author_direction = direction
        self._ai_set_running(True)
        worker = LocalRewriteWorker(
            str(session.path), lease, provider, direction, self)
        self._rewrite_worker = worker
        worker.proposed.connect(self._receive_ai_proposal)
        worker.failed.connect(self._ai_failed)
        worker.finished.connect(self._ai_finished)
        self.status.setText(
            f'{lease.episode}화 저장 원문으로 승인된 로컬 GGUF 수정 후보 생성 중. '
            '원고·최종본·출판 기록은 저장하지 않습니다.')
        worker.start()

    def propose_selected_ai_rewrite(self):
        """Author selects an exact saved span; preserve the rest byte-for-byte.

        This is an alternative to whole-chapter rewrite when a 5000+ character
        chapter has only one scene needing revision. One-time local-model
        consent is consumed before launching the worker.
        """
        if self.is_ai_running():
            return
        allowed = (self.ai_consent.isChecked()
                   and self.authoring.approved.isChecked())
        self.ai_consent.setChecked(False)
        self.authoring.approved.setChecked(False)
        session = self.authoring.session
        lease = self.lease
        if (not allowed or lease is None or session.store is None
                or session.path is None
                or str(session.project_id) != lease.project_id
                or session.episode_number != lease.episode
                or _busy(self.authoring) or _unsaved(self.authoring)):
            self.status.setText(
                '선택 구간 수정 전에 현재 저장 초고와 승인한 로컬 모델을 '
                '각각 이번 1회 승인하세요.')
            return
        try:
            latest, saved = begin_manual_rewrite(
                session.store, lease.project_id, lease.episode)
            if (latest != lease or self.editor.toPlainText() != saved
                    or session.store.get_episode(
                        lease.project_id, lease.episode).final_text.strip()):
                raise ValueError('stale or unsaved manuscript')
            cursor = self.editor.textCursor()
            if not cursor.hasSelection():
                raise ValueError('missing selected passage')
            start = _qt_cursor_to_codepoint(saved, cursor.selectionStart())
            end = _qt_cursor_to_codepoint(saved, cursor.selectionEnd())
            if not 100 <= end - start <= 6000:
                raise ValueError('selection must be 100 to 6000 chars')
            direction = self.author_direction.toPlainText()
            if (len(direction) > 2000 or '\x00' in direction
                    or any(ord(ch) < 32 and ch not in '\n\r\t'
                           for ch in direction)):
                raise ValueError('invalid author direction')
            executable = self.authoring._text('executable').strip()
            args = tuple(shlex.split(self.authoring._text('arguments')))
            special = (Path(executable).name.casefold() == 'anf_local_model.exe'
                       and args[:1] == ('--gguf',))
            provider = LocalExecutableProvider(
                executable, arguments=args,
                timeout_seconds=1500 if special else 450 if args[:1] == ('--gguf',)
                else 120, explicitly_allowed=True)
        except (ValueError, OSError, UnicodeError):
            self.status.setText(
                '저장 초고의 100~6000자 구간을 드래그 선택하고 '
                '모델·지시·원고 상태를 확인하세요. 아무것도 실행하지 않았습니다.')
            return
        self._model_identity = (
            str(session.path), lease.project_id, lease.episode, lease)
        self._saved_before_model = saved
        self._saved_author_direction = direction
        self._ai_set_running(True)
        worker = SelectedRewriteWorker(
            str(session.path), lease, provider, direction, start, end, self)
        self._rewrite_worker = worker
        worker.proposed.connect(self._receive_ai_proposal)
        worker.failed.connect(self._ai_failed)
        worker.finished.connect(self._ai_finished)
        self.status.setText(
            f'{lease.episode}화 {start+1}~{end}자 선택 구간만 실제 로컬 '
            'GGUF 재작성 중. 구간 밖 저장 원고와 최종본은 변경하지 않습니다.')
        worker.start()

    def stop_ai_expand(self):
        worker = self._rewrite_worker
        if isinstance(worker, DraftExpansionWorker) and worker.isRunning():
            worker.request_stop()
            self.stop_expand_button.setEnabled(False)
            self.status.setText(
                '중단 요청 접수: 현재 실행 중인 GGUF 호출이 끝나면 멈춥니다. '
                '이미 생성된 미검수 후보는 원본을 덮어쓰지 않습니다.')

    def propose_ai_expand(self):
        """Actual multi-call continuation of saved prose, no SQLite writes."""
        if self.is_ai_running():
            return
        allowed = (self.ai_consent.isChecked()
                   and self.authoring.approved.isChecked())
        self.ai_consent.setChecked(False)
        self.authoring.approved.setChecked(False)
        session = self.authoring.session
        lease = self.lease
        if (not allowed or lease is None or session.store is None
                or session.path is None
                or str(session.project_id) != lease.project_id
                or session.episode_number != lease.episode
                or _busy(self.authoring) or _unsaved(self.authoring)):
            self.status.setText(
                '저장된 현재 회차 원고와 이번 1회 로컬 모델을 각각 승인하세요.')
            return
        try:
            latest, saved = begin_manual_rewrite(
                session.store, lease.project_id, lease.episode)
            if (latest != lease or self.editor.toPlainText() != saved
                    or session.store.get_episode(
                        lease.project_id, lease.episode).final_text.strip()):
                raise ValueError('stale or unsaved draft')
            direction = self.author_direction.toPlainText()
            if (len(direction) > 2000 or '\x00' in direction
                    or any(ord(ch) < 32 and ch not in '\n\r\t'
                           for ch in direction)):
                raise ValueError('invalid author direction')
            executable = self.authoring._text('executable').strip()
            args = tuple(shlex.split(self.authoring._text('arguments')))
            special = (Path(executable).name.casefold() == 'anf_local_model.exe'
                       and args[:1] == ('--gguf',))
            provider = LocalExecutableProvider(
                executable, arguments=args,
                timeout_seconds=1500 if special else 450 if args[:1] == ('--gguf',)
                else 120, explicitly_allowed=True)
        except (ValueError, OSError, UnicodeError):
            self.status.setText(
                '현재 저장 초고·최종본·목표 분량·승인 모델 설정을 확인하세요.')
            return
        self._model_identity = (
            str(session.path), lease.project_id, lease.episode, lease)
        self._saved_before_model = saved
        self._saved_author_direction = direction
        worker = DraftExpansionWorker(
            str(session.path), lease, provider, direction,
            self.expansion_target.value(), self.expansion_calls.value(), self)
        self._rewrite_worker = worker
        self._ai_set_running(True)
        worker.proposed.connect(self._receive_ai_proposal)
        worker.failed.connect(self._ai_failed)
        worker.finished.connect(self._ai_finished)
        self.status.setText(
            f'{lease.episode}화 실제 저장 원고 끝부터 목표 '
            f'{self.expansion_target.value()}자까지 로컬 GGUF 이어쓰기 시작. '
            '기존 초고·최종본·SQLite 자동 변경 없음.')
        worker.start()

    def _receive_ai_proposal(self, result):
        session = self.authoring.session
        key = self._model_identity
        self._model_identity = None
        before = self._saved_before_model
        self._saved_before_model = None
        direction_at_start = self._saved_author_direction
        self._saved_author_direction = None
        if (key is None or before is None or session.store is None
                or session.path is None
                or (str(session.path), str(session.project_id),
                    session.episode_number, self.lease) != key
                or self.editor.toPlainText() != before
                or self.author_direction.toPlainText() != direction_at_start
                or _busy(self.authoring) or _unsaved(self.authoring)):
            self.status.setText(
                '작품·원고·편집 내용이 변경되어 AI 후보를 편집기에 넣지 않았습니다.')
            return
        try:
            require_current_manual_rewrite_preview(
                result.preview, session.store, result.lease,
                result.proposed_text)
        except (ValueError, OSError):
            self.status.setText(
                '로컬 AI 호출 중 원고가 바뀌어 후보를 폐기했습니다. 저장하지 않았습니다.')
            return
        # This changes ONLY the unsaved local text editor. It does not
        # accept a revision, save SQLite, or grant publication approval.
        self.editor.setPlainText(result.proposed_text)
        self.invalidate_preview()
        self.preview_snapshot = result.preview
        evidence = result.numeric_evidence
        if evidence is not None:
            self.numeric_evidence.setRowCount(len(evidence.rows))
            for index, metric in enumerate(evidence.rows):
                for col, value in enumerate((
                        metric.metric, metric.original_value,
                        metric.proposed_value)):
                    self.numeric_evidence.setItem(
                        index, col, QTableWidgetItem(str(value)))
            self.numeric_status.setText(
                f'실제 이전 저장 회차 {evidence.previous_episodes_examined}화 대조 / '
                f'누락 {evidence.previous_episodes_missing}화 / '
                f'본문 미검사 {evidence.previous_episodes_unexamined}화. '
                '수치·정확 문장 일치만 비교했고 문학 품질·의미 유사성·'
                '참고작 표절·출판 승인 아님.')
        if isinstance(result, DraftExpansionProposal):
            detail = (
                f'기존 원고 전체 보존 + 실제 GGUF 이어쓰기 '
                f'{result.accepted_new_passages}구간/{result.actual_model_calls}회 호출. '
                f'공백 제외 {result.resulting_nonspace_chars}자, '
                f'목표까지 {result.remaining_nonspace_chars}자 부족. '
                + ('작가 중단 요청 반영. ' if result.stopped_by_author else '')
                + '목표 도달은 품질 합격이 아님. ')
        elif isinstance(result, SelectedRewriteProposal):
            detail = (
                f'실제 선택 구간 {result.selected_start+1}~'
                f'{result.selected_end}자만 GGUF {result.actual_model_calls}회 '
                '재작성; 구간 밖 원문은 그대로 유지. ')
        else:
            detail = (
                f'실제 QC 주의 {len(result.source_qc_findings)}종 참고. '
                f'실제 GGUF 호출 {result.continuation.total_model_calls}회 / '
                f'실제 글자 부족 {result.continuation.remaining_nonspace_chars}자 '
                f'({result.continuation.stop_reason}). ')
        self.status.setText(
            f'{result.lease.episode}화 로컬 AI 미검수 수정 후보 '
            f'{result.preview.after_characters}자 편집기에 표시. '
            + detail
            + f'저장 Novel Bible·인물 설정 {result.saved_canon.author_sections}개 범위, '
            f'인접 실제 저장 원고 {len(result.saved_canon.neighbor_chapters)}화 '
            f'(누락 {len(result.saved_canon.missing_neighbor_chapters)}화) 참고. '
            '원문/최종본 미변경. 직접 읽고 수정·비교한 후 별도 저장하세요.')

    def _ai_failed(self, message):
        self._model_identity = None
        self._saved_before_model = None
        self._saved_author_direction = None
        self.status.setText(message)

    def _ai_finished(self):
        self._ai_set_running(False)
        self._rewrite_worker = None
