"""Windows GUI read-only author-fact/QC/human-review scope matrix."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_fact_review_matrix import build_author_fact_review_matrix


class AuthorFactReviewPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('인물 지식·복선·시간선 근거와 QC 연계 (읽기 전용)', parent)
        self.authoring = authoring
        layout = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        layout.addWidget(self.through)
        self.refresh_button = QPushButton('회차별 작가 사실·QC·수동 검수 근거 조회')
        self.refresh_button.setObjectName('authorFactReviewMatrix')
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ['회차', '유효 사실', '근거 변경/충돌', 'QC 미해결', '검수·차단 범위'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(240)
        layout.addWidget(self.table)
        self.status = QLabel('표시된 구조화 사실만의 범위이며 원고 전체 품질 합격이 아닙니다.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        button = QPushButton('선택 회차를 기존 원고 편집 화면에서 열기')
        button.clicked.connect(self._open_selected)
        layout.addWidget(button)

    def invalidate(self):
        self.table.setRowCount(0)
        self.status.setText('작품이 변경되었습니다. 근거 범위를 다시 조회하세요.')

    def refresh(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.invalidate()
            return
        try:
            panel = getattr(self.authoring, 'author_fact_panel', None)
            folder = panel.folder.text() if panel is not None else ''
            report = build_author_fact_review_matrix(
                session.store, str(session.project_id),
                through_episode=self.through.value(), fact_folder=folder or None)
        except (OSError, ValueError):
            self.invalidate()
            self.status.setText('현재 저장 원고의 사실·QC 기록을 읽지 못했습니다.')
            return
        self.table.setRowCount(len(report.chapters))
        for index, row in enumerate(report.chapters):
            cells = (str(row.episode), str(row.active_facts),
                     f'{row.stale_facts} / {row.conflicting_keys}',
                     str(row.qc_unresolved),
                     ', '.join(row.blockers))
            for column, value in enumerate(cells):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.status.setText(
            f'{report.through_episode}화 조회 / {report.attention_count}화 확인 필요. '
            '작가가 표시한 근거 외 원고는 검사되지 않았으며 출판 승인이 아닙니다.')

    def _open_selected(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            self.status.setText('기존 편집 화면에서 열 회차를 먼저 선택하세요.')
            return
        number = int(self.table.item(row, 0).text())
        selector = self.authoring.episodes
        index = selector.findData(number)
        if index < 0:
            self.status.setText('아직 저장되지 않은 회차입니다. 자동 생성하지 않습니다.')
            return
        selector.setCurrentIndex(index)
        self.status.setText(f'{number}화 기존 편집 화면을 선택했습니다. 출판 승인 아님.')
