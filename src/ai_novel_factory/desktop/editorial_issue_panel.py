"""Windows PySide6 author-initiated revision-bound editorial issue panel."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from ai_novel_factory.author_editorial_issue_detail_audit import (
    AuthorEditorialIssueDetailError, build_author_editorial_issue_detail_audit,
    read_author_editorial_issue_saved_final,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError

from ai_novel_factory.editorial_issue_ledger import (
    EditorialIssueError, current_final_identity, list_editorial_issues,
    open_editorial_issue, close_editorial_issue,
)


class EditorialIssuePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 직접 편집 이슈 기록 (로컬·미검수)', parent)
        self.authoring = authoring
        self._identity = None
        self._audit_snapshot = None
        self._audit_identity = None
        self._audit_folder = None
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.folder = QLineEdit()
        self.folder.setObjectName('editorialIssueLocalFolder')
        self.folder.setReadOnly(True)
        choose = QPushButton('기존 로컬 편집 기록 폴더 선택')
        choose.clicked.connect(self._choose_folder)
        form.addRow('로컬 폴더', self.folder)
        form.addRow(choose)
        self.number = QSpinBox()
        self.number.setRange(1, 1000)
        self.number.valueChanged.connect(self.refresh)
        form.addRow('회차', self.number)
        self.category = QComboBox()
        for key in ('continuity', 'character_knowledge', 'timeline',
                    'foreshadowing', 'plot_logic', 'reference_similarity',
                    'style', 'language', 'other'):
            self.category.addItem(key, key)
        form.addRow('문제 분류', self.category)
        self.note = QPlainTextEdit()
        self.note.setObjectName('editorialIssueAuthorNote')
        self.note.setPlaceholderText('작가가 직접 확인한 수정 필요 사항 (최대 1000자)')
        self.note.setMaximumHeight(72)
        form.addRow('편집 메모', self.note)
        self.status = QLabel('기존 작품·최종본과 로컬 기록 폴더를 직접 선택하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['회차', '분류', '현재 상태'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(180)
        root.addWidget(self.table)
        add = QPushButton('이 회차에 새 편집 이슈 기록 (직접 승인)')
        add.setObjectName('editorialIssueAddExplicit')
        add.clicked.connect(self._add)
        root.addWidget(add)
        close = QPushButton('현재 최종본을 읽고 선택 이슈 종료 (직접 승인)')
        close.setObjectName('editorialIssueCloseExplicit')
        close.clicked.connect(self._close)
        root.addWidget(close)
        refresh = QPushButton('현재 원고 기준 편집 이슈 새로고침')
        refresh.clicked.connect(self.refresh)
        root.addWidget(refresh)
        root.addWidget(QLabel(
            '전체 회차 편집 이슈 근거 열람: 읽기 전용이며 기존 종료·저장 버튼과 분리됩니다.'))
        audit_controls = QFormLayout()
        self.audit_through = QSpinBox()
        self.audit_through.setRange(1, 1000)
        self.audit_through.setValue(30)
        self.audit_through.setObjectName('editorialIssueAuditThrough')
        self.audit_through.valueChanged.connect(self._invalidate_audit)
        audit_controls.addRow('전수 조회 마지막 회차', self.audit_through)
        root.addLayout(audit_controls)
        audit_button = QPushButton('1화부터 선택 회차까지 모든 편집 이슈 직접 조회')
        audit_button.setObjectName('editorialIssueFullAuditRefresh')
        audit_button.clicked.connect(self.refresh_audit)
        root.addWidget(audit_button)
        self.audit_page = QSpinBox()
        self.audit_page.setRange(1, 1)
        self.audit_page.setObjectName('editorialIssueAuditPage')
        self.audit_page.valueChanged.connect(self._render_audit_page)
        root.addWidget(self.audit_page)
        self.audit_table = QTableWidget(0, 6)
        self.audit_table.setObjectName('editorialIssueFullAuditTable')
        self.audit_table.setHorizontalHeaderLabels(
            ['회차', '분류', '현재 이슈 상태', '최종본', '작가 검수', '참고작 범위'])
        self.audit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.audit_table.setMaximumHeight(220)
        self.audit_table.itemSelectionChanged.connect(self._clear_audit_preview)
        root.addWidget(self.audit_table)
        self.audit_open = QPushButton('선택 이슈 메모·저장 최종본 읽기 (별도 클릭)')
        self.audit_open.setObjectName('editorialIssueReadSavedFinal')
        self.audit_open.setEnabled(False)
        self.audit_open.clicked.connect(self.read_audit_final)
        root.addWidget(self.audit_open)
        self.audit_note = QPlainTextEdit()
        self.audit_note.setObjectName('editorialIssueAuditNote')
        self.audit_note.setReadOnly(True)
        self.audit_note.setMaximumHeight(100)
        self.audit_note.setPlaceholderText('작가가 직접 선택한 이슈 메모가 여기에 표시됩니다.')
        root.addWidget(self.audit_note)
        self.audit_final = QPlainTextEdit()
        self.audit_final.setObjectName('editorialIssueAuditSavedFinal')
        self.audit_final.setReadOnly(True)
        self.audit_final.setMaximumHeight(240)
        self.audit_final.setPlaceholderText('현재 SQLite에 저장된 최종본 원문 전체를 읽기 전용으로 표시합니다.')
        root.addWidget(self.audit_final)

    def _choose_folder(self):
        directory = QFileDialog.getExistingDirectory(self, '기존 로컬 편집 기록 폴더 선택')
        if directory:
            self.folder.setText(directory)
            self.refresh()

    def invalidate(self):
        self._invalidate_audit()
        self._identity = None
        self.folder.clear()
        self.note.clear()
        self.table.setRowCount(0)
        self.status.setText('작품이 변경되어 이전 편집 기록 선택을 폐기했습니다.')

    def _current(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            raise EditorialIssueError('기존 작품을 먼저 열어야 합니다.')
        if not self.folder.text():
            raise EditorialIssueError('로컬 편집 기록 폴더를 먼저 선택해야 합니다.')
        project_id = str(session.project_id)
        number = self.number.value()
        revision, digest = current_final_identity(session.store, project_id, number)
        return session.store, project_id, number, revision, digest

    def refresh(self):
        self._invalidate_audit()
        self._identity = None
        self.table.setRowCount(0)
        try:
            store, project, number, revision, digest = self._current()
            issues = list_editorial_issues(store, project, number,
                                           folder=Path(self.folder.text()))
        except (EditorialIssueError, OSError, ValueError):
            self.status.setText('현재 최종본 또는 로컬 기록을 읽을 수 없습니다. 자동 승인하지 않습니다.')
            return
        self._identity = (project, number, revision, digest)
        self.table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            number_item = QTableWidgetItem(str(issue.episode))
            number_item.setData(Qt.ItemDataRole.UserRole, issue.issue_id)
            self.table.setItem(row, 0, number_item)
            self.table.setItem(row, 1, QTableWidgetItem(issue.category))
            self.table.setItem(row, 2, QTableWidgetItem(issue.status))
        pending = sum(issue.status != 'CLOSED_CURRENT' for issue in issues)
        self.status.setText(f'{number}화 · 미해결/과거 종료 판정 {pending}건 · '
                            '편집 기록은 QC 합격·출판 승인이 아닙니다.')

    def _add(self):
        try:
            store, project, number, revision, digest = self._current()
            if self._identity != (project, number, revision, digest):
                raise EditorialIssueError('원고가 변경되어 새로고침이 필요합니다.')
            open_editorial_issue(
                store, project, number, folder=Path(self.folder.text()),
                category=self.category.currentData(), note=self.note.toPlainText(),
                expected_revision=revision, expected_final_sha256=digest,
                explicit_author_save=True)
            self.note.clear()
            self.refresh()
        except (EditorialIssueError, OSError, ValueError):
            self.status.setText('이슈를 저장하지 않았습니다. 현재 원고·폴더·메모를 다시 확인하세요.')

    def _close(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            self.status.setText('종료할 편집 이슈를 먼저 선택하세요.')
            return
        issue_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        try:
            store, project, number, revision, digest = self._current()
            if self._identity != (project, number, revision, digest):
                raise EditorialIssueError('원고가 변경되어 새로고침이 필요합니다.')
            close_editorial_issue(
                store, project, number, folder=Path(self.folder.text()),
                issue_id=issue_id, expected_revision=revision,
                expected_final_sha256=digest, explicit_author_read_current=True)
            self.refresh()
        except (EditorialIssueError, OSError, ValueError):
            self.status.setText('종료를 기록하지 않았습니다. 현재 최종본을 다시 확인하세요.')

    def _clear_audit_preview(self):
        self.audit_note.clear()
        self.audit_final.clear()

    def _invalidate_audit(self, *_args):
        self._audit_snapshot = None
        self._audit_identity = None
        self._audit_folder = None
        self.audit_open.setEnabled(False)
        self.audit_table.setRowCount(0)
        self._clear_audit_preview()
        self.audit_page.setRange(1, 1)

    def refresh_audit(self):
        """첫 클릭: 선택한 로컬 이슈 폴더의 전 회차 원고·QC 근거를 읽는다."""
        self._invalidate_audit()
        try:
            session, identity = _current_author_state(self.authoring)
            if not self.folder.text():
                raise AuthorEditorialIssueDetailError('기존 기록 폴더를 직접 선택하세요.')
            snapshot = build_author_editorial_issue_detail_audit(
                session.store, identity[1], through_episode=self.audit_through.value(),
                issue_folder=Path(self.folder.text()))
        except (AuthorEditorialIssueDetailError, BatchScopeBridgeError,
                OSError, ValueError, LookupError):
            self.status.setText('작품·원고·QC·편집 이슈 전체를 읽지 못했습니다. 다시 조회하세요.')
            return
        self._audit_snapshot = snapshot
        self._audit_identity = identity
        self._audit_folder = str(Path(self.folder.text()).resolve())
        self.audit_page.setRange(1, max(1, (len(snapshot.rows) + 99) // 100))
        self._render_audit_page()
        self.status.setText(
            f'1~{snapshot.through_episode}화 전체 편집 이슈 {len(snapshot.rows)}건 · '
            f'미해결 {snapshot.open_count}건 · 변경 후 과거 기록 {snapshot.stale_count}건. '
            '원문 열람은 QC 합격·출판 승인이 아닙니다.')

    def _render_audit_page(self, *_args):
        self._clear_audit_preview()
        self.audit_table.setRowCount(0)
        snapshot = self._audit_snapshot
        if snapshot is None:
            self.audit_open.setEnabled(False)
            return
        start = (self.audit_page.value() - 1) * 100
        rows = snapshot.rows[start:start + 100]
        names = {
            'OPEN_CURRENT': '미해결 (현재 원고)',
            'OPEN_STALE': '미해결 (원고 변경)',
            'CLOSED_CURRENT': '현재 원고 종료 기록',
            'CLOSED_STALE': '과거 원고 종료 기록',
        }
        self.audit_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (
                str(row.episode), row.category, names.get(row.state, '확인 필요'),
                '저장됨' if row.final_present else '없음',
                row.review_status, row.reference_status)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.issue_id)
                self.audit_table.setItem(index, col, item)
        self.audit_open.setEnabled(bool(rows))

    def read_audit_final(self):
        """두 번째 클릭: 이슈와 저장 최종본 전체를 재확인하고 화면에만 표시."""
        snapshot, identity, folder = (
            self._audit_snapshot, self._audit_identity, self._audit_folder)
        index = self.audit_table.currentRow()
        self._clear_audit_preview()
        if (snapshot is None or identity is None or folder is None
                or not 0 <= index < self.audit_table.rowCount()
                or self.audit_table.item(index, 0) is None):
            self.status.setText('먼저 전수 조회하고 이슈 한 건을 직접 선택하세요.')
            return
        issue_id = self.audit_table.item(index, 0).data(Qt.ItemDataRole.UserRole)
        start = (self.audit_page.value() - 1) * 100
        if (start + index >= len(snapshot.rows)
                or snapshot.rows[start + index].issue_id != issue_id):
            self.status.setText('선택한 이슈가 변경됐습니다. 다시 조회하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if (current != identity or self.audit_through.value() != snapshot.through_episode
                    or str(Path(self.folder.text()).resolve()) != folder):
                raise AuthorEditorialIssueDetailError('작품·조회 범위·기록 폴더가 변경됐습니다.')
            detail = read_author_editorial_issue_saved_final(
                snapshot, session.store, identity[1], issue_id=issue_id)
        except (AuthorEditorialIssueDetailError, BatchScopeBridgeError,
                OSError, ValueError, LookupError):
            self._invalidate_audit()
            self.status.setText('원고·QC·편집 기록·미저장 입력이 변경됐거나 '
                                '모델/배치가 실행 중입니다. 다시 직접 조회하세요.')
            return
        self.audit_note.setPlainText(detail.note)
        self.audit_final.setPlainText(detail.final_text)
        self.status.setText(
            f'{detail.episode}화 · 원고 버전 {detail.revision} · '
            '이슈 메모와 저장 최종본 원문 전체를 읽기 전용으로 표시했습니다. '
            '이슈 종료·QC 합격·출판 승인은 별도 직접 작업입니다.')
