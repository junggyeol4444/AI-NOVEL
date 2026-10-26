"""Existing Windows GUI: explicit in-memory manual draft rewrite."""
from __future__ import annotations
import shlex
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.local_models import LocalExecutableProvider
from ai_novel_factory.local_rewrite_proposal import (
    LocalRewriteProposalError, propose_rewrite_of_saved_draft,
)
from .author_navigation_contract import _busy, _unsaved
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QCheckBox, QTableWidget, QTableWidgetItem,
)
from ai_novel_factory.manual_rewrite_workspace import (
    begin_manual_rewrite, commit_manual_rewrite,
    preview_manual_rewrite, require_current_manual_rewrite_preview,
)


class LocalRewriteWorker(QThread):
    proposed = Signal(object)
    failed = Signal(str)

    def __init__(self, database_path, lease, provider, parent=None):
        super().__init__(parent)
        self.database_path = str(database_path)
        self.lease = lease
        self.provider = provider

    def run(self):
        try:
            proposal = propose_rewrite_of_saved_draft(
                self.database_path, self.lease.project_id,
                self.lease.episode, self.provider,
                expected_lease=self.lease, explicit_author_model_run=True)
            self.proposed.emit(proposal)
        except (LocalRewriteProposalError, ValueError, OSError, UnicodeError):
            self.failed.emit(
                '로컬 AI 수정 후보 생성에 실패했거나 저장 원고가 변경됐습니다. '
                '원본·최종본은 그대로 유지됩니다.')
        except BaseException:
            self.failed.emit(
                '로컬 모델 실행을 마칠 수 없었습니다. 원본·최종본은 유지됩니다.')


class ManualRewritePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('저장된 초고 수동 재작성 · 기존 최종본 보호', parent)
        self.authoring = authoring
        self.lease = None
        self.preview_snapshot = None
        self._rewrite_worker = None
        self._model_identity = None
        self._saved_before_model = None
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
        self.ai_consent = QCheckBox(
            '현재 저장 초고를 이번 1회 신뢰한 로컬 GGUF로만 수정 제안하도록 승인 '
            '(모델 출력 자동 저장·자동 합격 없음)')
        self.ai_consent.setObjectName('manualRewriteLocalAiConsent')
        root.addWidget(self.ai_consent)
        self.ai_button = QPushButton('현재 회차 AI 재작성 미검수 후보 생성 (로컬)')
        self.ai_button.setObjectName('manualRewriteLocalAiPropose')
        self.ai_button.clicked.connect(self.propose_ai_rewrite)
        root.addWidget(self.ai_button)
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
        for button in (self.load_button, self.ai_button,
                       self.preview_button, self.save_button, self.final_handoff):
            button.setEnabled(not running)
        self.editor.setReadOnly(running)

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
        self._ai_set_running(True)
        worker = LocalRewriteWorker(str(session.path), lease, provider, self)
        self._rewrite_worker = worker
        worker.proposed.connect(self._receive_ai_proposal)
        worker.failed.connect(self._ai_failed)
        worker.finished.connect(self._ai_finished)
        self.status.setText(
            f'{lease.episode}화 저장 원문으로 승인된 로컬 GGUF 수정 후보 생성 중. '
            '원고·최종본·출판 기록은 저장하지 않습니다.')
        worker.start()

    def _receive_ai_proposal(self, result):
        session = self.authoring.session
        key = self._model_identity
        self._model_identity = None
        before = self._saved_before_model
        self._saved_before_model = None
        if (key is None or before is None or session.store is None
                or session.path is None
                or (str(session.path), str(session.project_id),
                    session.episode_number, self.lease) != key
                or self.editor.toPlainText() != before
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
        self.status.setText(
            f'{result.lease.episode}화 로컬 AI 미검수 수정 후보 '
            f'{result.preview.after_characters}자 편집기에 표시. '
            f'실제 QC 주의 {len(result.source_qc_findings)}종 참고. '
            '원문/최종본 미변경. 직접 읽고 수정·비교한 후 별도 저장하세요.')

    def _ai_failed(self, message):
        self._model_identity = None
        self._saved_before_model = None
        self.status.setText(message)

    def _ai_finished(self):
        self._ai_set_running(False)
        self._rewrite_worker = None
