"""Read-only author-selected chapter revision dependency map in existing Qt UI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem,
)

from ai_novel_factory.longform_revision_impact import plan_revision_impact


class LongformRevisionImpactPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 원고 수정 시 후속 회차 영향 범위 (읽기 전용)', parent)
        self.authoring = authoring
        layout = QVBoxLayout(self)
        self.source = QSpinBox()
        self.source.setRange(1, 1000)
        layout.addWidget(QLabel('영향 기준으로 선택한 기존 최종본 회차'))
        layout.addWidget(self.source)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(100)
        layout.addWidget(QLabel('확인할 마지막 회차'))
        layout.addWidget(self.through)
        button = QPushButton('후속 회차의 잠재 영향과 작가 사실 근거 조회')
        button.setObjectName('longformRevisionImpactPreview')
        button.clicked.connect(self.refresh)
        layout.addWidget(button)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['회차', '작가 사실 연결', 'QC/최종본', '잠재 영향(합격 아님)'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(260)
        layout.addWidget(self.table)
        self.status = QLabel('조회 전. 이 화면은 변경 발생이나 실제 모순을 판정하지 않습니다.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        go = QPushButton('선택 회차를 기존 편집 화면에서 열기')
        go.clicked.connect(self.open_selected)
        layout.addWidget(go)

    def invalidate(self, *_args):
        self.table.setRowCount(0)
        self.status.setText('작품이 변경되었습니다. 새로 조회하세요.')

    def refresh(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.invalidate()
            return
        fact_panel = getattr(self.authoring, 'author_fact_panel', None)
        folder = fact_panel.folder.text().strip() if fact_panel is not None else ''
        try:
            report = plan_revision_impact(
                session.store, str(session.project_id),
                changed_episode=self.source.value(),
                through_episode=self.through.value(),
                fact_folder=folder or None)
        except (ValueError, OSError):
            self.invalidate()
            self.status.setText('현재 최종본/작가 근거를 읽지 못했습니다. 기존 파일은 변경하지 않았습니다.')
            return
        self.table.setRowCount(len(report.chapters))
        for index, row in enumerate(report.chapters):
            values = (str(row.episode), f'{row.linked_author_facts}개 / 과거 {row.stale_fact_sources}개',
                      '확인 필요' if row.qc_requires_review else '현재 QC 기록 있음(품질 보증 아님)',
                      ', '.join(row.reasons))
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.status.setText(
            f'{report.source_episode}화 기준 / 후속 {report.possible_downstream_count}화 잠재 영향. '
            '연결되지 않은 후속 회차도 자동 안전 판정하지 않습니다. 출판 승인 없음.')

    def open_selected(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            self.status.setText('기존 저장 회차를 먼저 선택하세요.')
            return
        number = int(self.table.item(row, 0).text())
        selector = self.authoring.episodes
        index = selector.findData(number)
        if index < 0:
            self.status.setText('아직 저장되지 않은 회차입니다. 자동 생성하지 않습니다.')
            return
        selector.setCurrentIndex(index)
        self.status.setText(f'{number}화 기존 편집 화면으로 이동했습니다. 자동 수정 없음.')
