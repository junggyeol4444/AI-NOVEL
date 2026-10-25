"""Existing Windows GUI: explicit in-memory manual draft rewrite."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QCheckBox, QTableWidget, QTableWidgetItem,
)
from ai_novel_factory.manual_rewrite_workspace import (
    begin_manual_rewrite, commit_manual_rewrite,
    preview_manual_rewrite, require_current_manual_rewrite_preview,
)


class ManualRewritePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('저장된 초고 수동 재작성 · 기존 최종본 보호', parent)
        self.authoring = authoring
        self.lease = None
        self.preview_snapshot = None
        root = QVBoxLayout(self)
        label = QLabel('현재 회차 저장 초고를 별도 편집합니다. 직접 저장 버튼 전에는 SQLite 변경 없음. '
                       '최종 원고는 덮어쓰지 않으며 재작성 후 검수/품질 판정은 다시 필요합니다.')
        label.setWordWrap(True)
        root.addWidget(label)
        load = QPushButton('현재 저장 초고를 재작성 편집기로 불러오기')
        load.setObjectName('manualRewriteLoad')
        load.clicked.connect(self.load_current)
        root.addWidget(load)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName('manualRewriteEditor')
        self.editor.setPlaceholderText('작가가 직접 수정한 초고를 입력합니다.')
        root.addWidget(self.editor)
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
        self.preview_status = QLabel('NOT_RUN: 작가가 직접 비교를 눌러야 합니다.')
        self.preview_status.setWordWrap(True)
        root.addWidget(self.preview_status)
        self.consent = QCheckBox('현재 회차의 초고만 수정 저장하며 재검수해야 함을 확인합니다')
        self.consent.setObjectName('manualRewriteConsent')
        root.addWidget(self.consent)
        save = QPushButton('수동 재작성 초고 저장 (기존 최종본 유지)')
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

    def invalidate_preview(self, *_args):
        self.preview_snapshot = None
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
        self.lease = None
        self.invalidate_preview()
        self.editor.clear()
        self.consent.setChecked(False)
        self.status.setText('현재 회차를 다시 불러와야 합니다.')

    def load_current(self):
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
