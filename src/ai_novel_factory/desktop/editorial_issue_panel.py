"""Windows PySide6 author-initiated revision-bound editorial issue panel."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from ai_novel_factory.editorial_issue_ledger import (
    EditorialIssueError, current_final_identity, list_editorial_issues,
    open_editorial_issue, close_editorial_issue,
)


class EditorialIssuePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 직접 편집 이슈 기록 (로컬·미검수)', parent)
        self.authoring = authoring
        self._identity = None
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

    def _choose_folder(self):
        directory = QFileDialog.getExistingDirectory(self, '기존 로컬 편집 기록 폴더 선택')
        if directory:
            self.folder.setText(directory)
            self.refresh()

    def invalidate(self):
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
