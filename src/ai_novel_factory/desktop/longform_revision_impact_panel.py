"""Read-only author-selected chapter revision dependency map in existing Qt UI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QGroupBox, QVBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem,
)

from ai_novel_factory.author_revision_handoff import (
    AuthorRevisionHandoffError, preview_author_revision_handoff,
    require_current_author_revision_handoff,
)
from .author_navigation_contract import _busy, _unsaved, select_saved_episode


_TARGETS = (
    ('인물·복선·시간선 사실 근거', 'author_fact_review_panel'),
    ('고유명사·말투 표기 검토', 'author_language_review_panel'),
    ('최종본 참고작 전수 비교', 'final_reference_audit_panel'),
    ('현재 회차 QC 검수 기록', 'review_dashboard_panel'),
    ('작가 수동 검수 기록', 'review_worklist'),
    ('수동 초고 재작성', 'manual_rewrite_panel'),
    ('편집 이슈 직접 기록', 'editorial_issue_panel'),
    ('장면별 중단·재개 기록', 'scene_checkpoint_panel'),
)


class LongformRevisionImpactPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 원고 수정 시 후속 회차 영향 범위 (읽기 전용)', parent)
        self.authoring = authoring
        self._snapshot = None
        self._identity = None
        self._fact_folder = None
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
        tool_row = QHBoxLayout()
        self.tool_selector = QComboBox()
        self.tool_selector.setObjectName('longformRevisionTarget')
        for title, target in _TARGETS:
            self.tool_selector.addItem(title, target)
        self.tool_button = QPushButton('선택 회차의 기존 검토·재작성 화면 열기')
        self.tool_button.setObjectName('longformRevisionOpenTool')
        self.tool_button.clicked.connect(self.open_tool)
        tool_row.addWidget(self.tool_selector)
        tool_row.addWidget(self.tool_button)
        layout.addLayout(tool_row)
        self.source.valueChanged.connect(self.invalidate)
        self.through.valueChanged.connect(self.invalidate)
        self.invalidate()

    def invalidate(self, *_args):
        self._snapshot = None
        self._identity = None
        self._fact_folder = None
        self.table.setRowCount(0)
        self.tool_button.setEnabled(False)
        self.status.setText('작품·회차·원고가 변경됐다면 영향 범위를 다시 조회하세요.')

    def _current(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None or session.path is None:
            raise AuthorRevisionHandoffError('기존 작품 SQLite를 먼저 여세요.')
        if _busy(self.authoring):
            raise AuthorRevisionHandoffError('모델·배치 실행 중에는 이동할 수 없습니다.')
        try:
            if _unsaved(self.authoring):
                raise AuthorRevisionHandoffError('미저장 초고·장면·플롯·최종본을 먼저 정리하세요.')
        except (ValueError, OSError, LookupError):
            raise AuthorRevisionHandoffError('현재 편집 상태를 확인하지 못했습니다.') from None
        fact_panel = getattr(self.authoring, 'author_fact_panel', None)
        folder = fact_panel.folder.text().strip() if fact_panel is not None else ''
        return session, (str(session.path), str(session.project_id)), folder or None

    def refresh(self):
        self.invalidate()
        try:
            session, identity, folder = self._current()
            snapshot = preview_author_revision_handoff(
                session.store, str(session.project_id),
                source_episode=self.source.value(),
                through_episode=self.through.value(), fact_folder=folder)
        except (AuthorRevisionHandoffError, ValueError, OSError):
            self.status.setText('현재 저장 최종본·QC·참고작·작가 사실을 조회하지 못했습니다.')
            return
        self._snapshot, self._identity, self._fact_folder = snapshot, identity, folder
        self.table.setRowCount(len(snapshot.plan.chapters))
        for index, row in enumerate(snapshot.plan.chapters):
            values = (str(row.episode),
                      f'{row.linked_author_facts}개 / 과거 {row.stale_fact_sources}개',
                      '확인 필요' if row.qc_requires_review else '현재 QC 기록 있음(품질 보증 아님)',
                      ', '.join(row.reasons))
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.tool_button.setEnabled(True)
        self.status.setText(
            f'{snapshot.source_episode}~{snapshot.through_episode}화 후속 검토 범위. '
            '원고·QC·참고작·작가 사실 변경 시 인계 무효. '
            '연결이 없는 회차도 안전 판정하지 않으며 출판 승인 아님.')

    def _selected_chapter(self):
        snapshot = self._snapshot
        index = self.table.currentRow()
        if snapshot is None or index < 0 or index >= len(snapshot.plan.chapters):
            raise AuthorRevisionHandoffError('기존 저장 회차를 먼저 선택하세요.')
        number = snapshot.plan.chapters[index].episode
        chapter = snapshot.workflow.chapters[number - 1]
        if chapter.revision is None:
            raise AuthorRevisionHandoffError('미생성 회차는 자동 생성하지 않습니다.')
        return chapter

    def _require_current(self):
        session, identity, folder = self._current()
        snapshot = self._snapshot
        if (snapshot is None or identity != self._identity or folder != self._fact_folder
                or snapshot.source_episode != self.source.value()
                or snapshot.through_episode != self.through.value()):
            raise AuthorRevisionHandoffError('작품·근거 폴더·회차가 변경됐습니다. 다시 조회하세요.')
        require_current_author_revision_handoff(
            snapshot, session.store, str(session.project_id), fact_folder=folder)
        return identity

    def open_selected(self):
        try:
            chapter = self._selected_chapter()
            identity = self._require_current()
            decision = select_saved_episode(
                self.authoring, project_identity=identity,
                episode=chapter.episode, snapshot=chapter)
            self.status.setText(decision.message)
        except (AuthorRevisionHandoffError, ValueError, OSError):
            self.invalidate()
            self.status.setText('원고·QC·작가 근거가 바뀌었거나 회차를 선택하지 않았습니다. 다시 조회하세요.')

    def open_tool(self):
        target = self.tool_selector.currentData()
        if target not in {key for _, key in _TARGETS}:
            self.status.setText('기존 검토 도구를 직접 선택하세요.')
            return
        try:
            chapter = self._selected_chapter()
            identity = self._require_current()
            decision = select_saved_episode(
                self.authoring, project_identity=identity,
                episode=chapter.episode, snapshot=chapter)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    target, episode_number=chapter.episode, project_identity=identity):
                self.status.setText('기존 도구 화면을 열지 못했습니다.')
                return
            self.status.setText(
                f'{chapter.episode}화 기존 검토·재작성 화면을 열었습니다. '
                '검사·저장·모델 실행·출판 승인은 별도 직접 버튼이 필요합니다.')
        except (AuthorRevisionHandoffError, ValueError, OSError):
            self.invalidate()
            self.status.setText('현재 저장 원고·QC·참고작·작가 근거가 변경됐습니다. 다시 조회하세요.')
