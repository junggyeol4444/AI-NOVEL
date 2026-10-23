"""Project-scoped desktop dashboard for 1~1000 saved chapter review status."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..episode_review_dashboard import build_review_dashboard


class ReviewDashboardPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 전체 회차 검수·참고작·원고 상태 (읽기 전용)', parent)
        self.authoring = authoring
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('마지막 회차'))
        self.through = QSpinBox()
        self.through.setObjectName('novelReviewDashboardThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        top.addWidget(self.through)
        self.refresh_button = QPushButton('저장된 원고·검수·참고작 기록 새로고침')
        self.refresh_button.setObjectName('novelReviewDashboardRefresh')
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        root.addLayout(top)
        self.status = QLabel('기존 작품을 열어야 조회할 수 있습니다. 출판 승인과 별개입니다.')
        self.status.setWordWrap(True)
        self.status.setObjectName('novelReviewDashboardStatus')
        root.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName('novelReviewDashboardTable')
        self.table.setHorizontalHeaderLabels((
            '회차', '원고', 'QC 기록', '참고작 비교 범위', '작가 검수'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(230)
        root.addWidget(self.table)
        self.open_button = QPushButton('선택한 회차를 기존 편집 화면에서 열기')
        self.open_button.setObjectName('novelReviewDashboardOpen')
        self.open_button.clicked.connect(self.open_selected)
        root.addWidget(self.open_button)

    def refresh(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('기존 작품 SQLite를 먼저 열어야 합니다.')
            self.table.setRowCount(0)
            return
        try:
            report = build_review_dashboard(
                session.store, str(session.project_id),
                through_episode=self.through.value())
        except (OSError, ValueError):
            self.status.setText('현재 작품의 회차 검수 현황을 읽을 수 없습니다.')
            self.table.setRowCount(0)
            return
        self.status.setText(
            f'본문 누락 {report.missing_manuscripts}화 / 작가 검수 없음·과거 판정 '
            f'{report.unreviewed_or_stale}화 / 참고작 비교 누락·불완전 '
            f'{report.reference_not_examined}화 / QC 미완료 {report.qc_incomplete}화. '
            'QC 기록과 참고작 비교 범위는 문학 품질·저작권·출판 승인 아님.')
        self.table.setRowCount(len(report.chapters))
        for row, chapter in enumerate(report.chapters):
            values = (str(chapter.episode), chapter.manuscript, chapter.qc_state,
                      chapter.reference_scope, chapter.human_review)
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def open_selected(self):
        row = self.table.currentRow()
        if row < 0:
            self.status.setText('이동할 회차를 먼저 선택하세요.')
            return
        number_item = self.table.item(row, 0)
        if number_item is None:
            return
        number = int(number_item.text())
        selector = self.authoring.episodes
        index = selector.findData(number)
        if index < 0:
            self.status.setText('해당 회차는 저장되어 있지 않습니다. 자동 생성하지 않습니다.')
            return
        selector.setCurrentIndex(index)
        self.status.setText(f'{number}화를 기존 편집 화면에서 선택했습니다. 검수·출판 승인 아님.')
