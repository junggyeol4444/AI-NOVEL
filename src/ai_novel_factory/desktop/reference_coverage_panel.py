"""Reference comparison coverage across saved chapters, read-only."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHBoxLayout,
)
from ..reference_coverage_report import summarize_reference_coverage


class ReferenceCoveragePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('참고작 전수 비교 범위 (원고 수정·출판 없음)', parent)
        self.authoring = authoring
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel('마지막 회차'))
        self.through = QSpinBox()
        self.through.setObjectName('referenceCoverageThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        row.addWidget(self.through)
        self.button = QPushButton('저장된 참고작 검사 기록 읽기')
        self.button.setObjectName('referenceCoverageRefresh')
        self.button.clicked.connect(self.refresh)
        row.addWidget(self.button)
        layout.addLayout(row)
        self.summary = QLabel('검사 기록이 없으면 NOT_RUN입니다. 의미적 독창성·저작권·출판 승인과 별개입니다.')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName('referenceCoverageTable')
        self.table.setHorizontalHeaderLabels(('회차', '범위 판정', '선택', '실제 비교', '미검사 범위'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(200)
        layout.addWidget(self.table)

    def refresh(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.summary.setText('기존 작품 DB를 먼저 열어야 합니다.')
            self.table.setRowCount(0)
            return
        try:
            report = summarize_reference_coverage(
                session.store, str(session.project_id),
                through_episode=self.through.value())
        except (ValueError, OSError):
            self.summary.setText('현재 저장된 참고작 검사 기록을 읽을 수 없습니다.')
            self.table.setRowCount(0)
            return
        self.summary.setText(
            f'미검사·과거 판정 {report.not_examined}화 / 검사 범위 불완전 '
            f'{report.incomplete}화 / 중복 차단·실패 {report.blocked_or_failed}화 / '
            f'기록된 범위만 확인 {report.checked_scope_only}화. '
            '모든 회차에 작가 수동 검수가 필요하며 출판 승인은 별개입니다.')
        self.table.setRowCount(len(report.chapters))
        for index, chapter in enumerate(report.chapters):
            for col, text in enumerate((str(chapter.episode), chapter.status,
                                        str(chapter.selected), str(chapter.compared),
                                        str(chapter.unexamined))):
                self.table.setItem(index, col, QTableWidgetItem(text))
