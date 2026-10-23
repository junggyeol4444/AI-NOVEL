"""Read-only native milestone rollup of stored chapter progress."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from ..author_workflow_milestones import summarize_author_workflow_milestones


class AuthorWorkflowMilestonesPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('30·100·250·1000화 집필 기록 범위', parent)
        self.authoring = authoring
        self._bound_project = None
        root = QVBoxLayout(self)
        self.description = QLabel(
            '기존 저장 회차와 검수·참고작 기록만 비교합니다. 미검증 AI 집필이나 '
            '실제 Windows 실행 성공을 의미하지 않습니다.')
        self.description.setWordWrap(True)
        root.addWidget(self.description)
        refresh = QPushButton('현재 작품의 마일스톤 현황 읽기')
        refresh.setObjectName('authorWorkflowMilestonesRead')
        refresh.clicked.connect(self.refresh)
        root.addWidget(refresh)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName('authorWorkflowMilestonesTable')
        self.table.setHorizontalHeaderLabels((
            '목표', '저장 회차', '초고 있는 회차', '최종본 있는 회차',
            '현재 직접 검수 기록', '참고작 기록 범위만 확인', '작가 확인 필요 회차'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        self.status = QLabel('읽기 전용 · 출판 승인 없음')
        root.addWidget(self.status)

    def invalidate(self, *_args):
        self._bound_project = None
        self.table.setRowCount(0)
        self.status.setText('작품 변경 시 기록 범위를 다시 조회하세요.')

    def refresh(self):
        self.invalidate()
        session = self.authoring.session
        if session.store is None or session.project_id is None or session.path is None:
            self.status.setText('기존 작품 SQLite를 먼저 열어 주세요.')
            return
        try:
            summary = summarize_author_workflow_milestones(
                session.store, str(session.project_id))
        except (ValueError, OSError):
            self.status.setText('저장된 장편 집필 기록을 읽지 못했습니다.')
            return
        self._bound_project = (str(session.path), str(session.project_id))
        self.table.setRowCount(len(summary.milestones))
        for i, item in enumerate(summary.milestones):
            values = (item.episodes, item.saved, item.draft_present,
                      item.final_present, item.human_review_recorded_current,
                      item.references_checked_scope_only, item.chapters_requiring_attention)
            for c, v in enumerate(values):
                self.table.setItem(i, c, QTableWidgetItem(str(v)))
        self.status.setText(
            '실제 모델을 30·100·250·1000화 실행한 결과가 아닌, 저장된 기록의 현황입니다. '
            '참고작 범위 확인도 저작권·문학 품질 합격이 아닙니다. 출판 승인 없음.')
