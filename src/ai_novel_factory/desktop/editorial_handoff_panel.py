"""Windows GUI: explicit read-only 1~1000 episode editorial handoff view."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.editorial_handoff_gate import build_editorial_handoff


class EditorialHandoffPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('원고 인계 차단 현황 (읽기 전용·출판 불가)', parent)
        self.authoring = authoring
        root = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        root.addWidget(self.through)
        self.status = QLabel('현재 작품의 실제 최종본·QC·참고작·검수·편집 이슈를 조회합니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        refresh = QPushButton('전체 원고 인계 차단 항목 조회 (읽기 전용)')
        refresh.setObjectName('editorialHandoffReadOnlyRefresh')
        refresh.clicked.connect(self.refresh)
        root.addWidget(refresh)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['회차', '수정 대기', '차단 근거'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(230)
        root.addWidget(self.table)
        open_button = QPushButton('선택 회차를 기존 편집 화면에서 열기')
        open_button.clicked.connect(self._open_selected)
        root.addWidget(open_button)

    def invalidate(self):
        self.table.setRowCount(0)
        self.status.setText('작품이 변경되었습니다. 현황을 다시 조회하세요.')

    def refresh(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.invalidate()
            return
        try:
            issues = getattr(self.authoring, 'editorial_issue_panel', None)
            directory = issues.folder.text() if issues is not None else ''
            report = build_editorial_handoff(
                session.store, str(session.project_id),
                through_episode=self.through.value(),
                issue_folder=Path(directory) if directory else None)
        except (OSError, ValueError):
            self.status.setText('현재 원고의 검수·편집 이슈를 읽을 수 없습니다.')
            self.table.setRowCount(0)
            return
        self.status.setText(
            f'조회 {len(report.chapters)}화 / 차단 {report.attention_count}화. '
            '이 현황은 합격·저작권 확인·출판 승인으로 사용할 수 없습니다.')
        self.table.setRowCount(len(report.chapters))
        for row, chapter in enumerate(report.chapters):
            values = (str(chapter.episode),
                      f'열린 이슈 {chapter.open_issues} / 과거 판정 {chapter.stale_issues}',
                      ', '.join(chapter.blockers))
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def _open_selected(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            self.status.setText('열 회차를 먼저 선택하세요.')
            return
        number = int(self.table.item(row, 0).text())
        selector = self.authoring.episodes
        index = selector.findData(number)
        if index < 0:
            self.status.setText('저장된 회차가 아닙니다. 자동 생성하지 않습니다.')
            return
        selector.setCurrentIndex(index)
        self.status.setText(f'{number}화를 편집 화면에서 선택했습니다. 출판 승인 아님.')
