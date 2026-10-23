"""Native PySide6 author work queue; no model, QC or publish actions."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..author_workflow_dependencies import (
    AuthorWorkflowDependenciesError, build_author_workflow_dependencies,
    require_current_workflow_chapter,
)


_ACTION_LABELS = {
    'CREATE_EPISODE': '회차 직접 생성',
    'PREPARE_DRAFT': 'AI 초고 또는 직접 초고 준비',
    'WRITE_OR_REVIEW_FINAL': '작가 최종 원고 직접 검수·저장',
    'COMPLETE_OR_REFRESH_QC': '현재 원고 QC 기록 확인',
    'REVIEW_REFERENCES': '참고작 선택 범위 검사 확인',
    'CONFIRM_HUMAN_REVIEW': '현재 원고 직접 검수',
    'SEPARATE_PUBLICATION_APPROVAL': '출판은 별도 승인 필요',
}


class AuthorWorkflowDependenciesPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 집필 · 회차별 실제 남은 작업', parent)
        self.authoring = authoring
        self._bound_project = None
        self._report = None
        body = QVBoxLayout(self)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('확인할 마지막 회차'))
        self.through = QSpinBox()
        self.through.setObjectName('authorWorkflowThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        tools.addWidget(self.through)
        self.filter = QComboBox()
        self.filter.addItems(('전체', '출판 별도 승인 제외 미완료', '최종본 없음', '참고작 검사 필요', '수동 검수 필요'))
        tools.addWidget(self.filter)
        reload_button = QPushButton('기존 저장 기록에서 새로 읽기')
        reload_button.clicked.connect(self.refresh)
        tools.addWidget(reload_button)
        body.addLayout(tools)
        self.status = QLabel('프로젝트를 연 뒤 직접 조회하세요. 검수 합격·출판 승인 화면이 아닙니다.')
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(('회차', '원고 revision', '직접 검수 기록', '참고작 범위', '다음 작가 작업'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setObjectName('authorWorkflowDependencyTable')
        body.addWidget(self.table)
        self.open_button = QPushButton('선택한 저장 회차를 기존 편집기로 열기')
        self.open_button.clicked.connect(self.open_selected)
        body.addWidget(self.open_button)
        self.through.valueChanged.connect(self.invalidate)
        self.filter.currentIndexChanged.connect(self._render)

    def invalidate(self, *_args):
        self._report = None
        self._bound_project = None
        self.table.setRowCount(0)
        self.status.setText('작품이나 범위 변경 후 현재 저장 기록을 다시 읽으세요.')

    def refresh(self):
        self.invalidate()
        session = self.authoring.session
        if session.store is None or session.project_id is None or session.path is None:
            self.status.setText('기존 작품을 먼저 생성하거나 열어 주세요.')
            return
        try:
            report = build_author_workflow_dependencies(
                session.store, str(session.project_id),
                through_episode=self.through.value())
        except (ValueError, OSError):
            self.status.setText('현재 작품 작업 기록을 읽지 못했습니다. 합격 처리하지 않습니다.')
            return
        self._bound_project = (str(session.path), str(session.project_id))
        self._report = report
        self._render()

    def _render(self, *_args):
        report = self._report
        self.table.setRowCount(0)
        if report is None:
            return
        category = self.filter.currentIndex()
        rows = []
        for item in report.chapters:
            if category == 1 and not any(a != 'SEPARATE_PUBLICATION_APPROVAL' for a in item.remaining_actions):
                continue
            if category == 2 and item.final_present:
                continue
            if category == 3 and item.reference_status == 'CHECKED_SCOPE_ONLY':
                continue
            if category == 4 and item.review_status == 'REVIEWED_QC_RECORDED_NOT_PUBLISHED':
                continue
            rows.append(item)
        self.table.setRowCount(len(rows))
        for i, item in enumerate(rows):
            values = (str(item.episode), str(item.revision or '미작성'),
                      item.review_status, item.reference_status,
                      _ACTION_LABELS.get(item.next_action, '작가 직접 확인'))
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setData(256, item.episode)
                self.table.setItem(i, col, cell)
        self.status.setText(
            f'조회 {report.through_episode}화 / 미작성 {report.missing_episodes}화 / '
            f'최종본 미비 {report.missing_final_manuscripts}화 / '
            f'검수 확인 필요 {report.review_action_count}화 / '
            f'참고작 범위 확인 필요 {report.reference_action_count}화. '
            '모든 결과는 기존 저장 기록 표시이며 AI·QC 합격 및 출판 승인이 아닙니다.')

    def open_selected(self):
        session = self.authoring.session
        report = self._report
        identity = (str(session.path), str(session.project_id))
        index = self.table.currentRow()
        if (report is None or identity != self._bound_project or index < 0
                or session.store is None or self.table.item(index, 0) is None):
            self.invalidate()
            return
        number = int(self.table.item(index, 0).text())
        item = next((r for r in report.chapters if r.episode == number), None)
        if item is None:
            self.invalidate()
            return
        try:
            require_current_workflow_chapter(session.store, str(session.project_id), item)
            session.select_episode(number)
            self.authoring._sync()
        except (AuthorWorkflowDependenciesError, OSError, ValueError):
            self.invalidate()
            self.status.setText('작품·회차가 변경되었습니다. 다시 조회 후 열어 주세요.')
            return
        self.status.setText(f'{number}화 기존 편집기로 이동했습니다. 검수·출판 승인 상태는 변하지 않습니다.')
