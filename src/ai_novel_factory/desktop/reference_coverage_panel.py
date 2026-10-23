"""Reference comparison coverage across saved chapters, read-only."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHBoxLayout,
)
from ..reference_coverage_report import summarize_reference_coverage
from ..author_reference_recheck_queue import (
    ReferenceRecheckQueueError, build_reference_recheck_queue,
    require_current_reference_recheck_queue,
)
from .author_navigation_contract import _busy, _unsaved, select_saved_episode

_ACTION_LABELS = {
    'FINAL_MANUSCRIPT_REQUIRED': '최종본 직접 작성·저장 필요',
    'REVIEW_FLAGGED_THEN_RESCAN': '위험 표시 직접 검토 후 다시 검사',
    'RECORDED_SCOPE_UNBOUND_RESCAN': '과거 기록만 존재·현재 선택 재검사',
    'SCAN_CURRENT_SELECTION': '현재 선택 참고작 전수 검사 필요',
}


class ReferenceCoveragePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('참고작 전수 비교 범위 (원고 수정·출판 없음)', parent)
        self.authoring = authoring
        self._queue = None
        self._identity = None
        self._selection = ()
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
        self.queue_button = QPushButton('현재 선택 참고작·최종본 전수 재검사 대기열 확인')
        self.queue_button.setObjectName('referenceRecheckQueuePreview')
        self.queue_button.clicked.connect(self.preview_queue)
        layout.addWidget(self.queue_button)
        self.queue_table = QTableWidget(0, 5)
        self.queue_table.setObjectName('referenceRecheckQueueTable')
        self.queue_table.setHorizontalHeaderLabels(
            ('회차', '최종본', '과거 검사 범위', '수동 검수', '현재 선택 후속 작업'))
        self.queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.queue_table.setMaximumHeight(240)
        layout.addWidget(self.queue_table)
        actions = QHBoxLayout()
        self.editor_button = QPushButton('선택한 저장 회차를 기존 편집기로 열기')
        self.editor_button.setObjectName('referenceRecheckOpenEditor')
        self.editor_button.clicked.connect(self.open_editor)
        self.audit_button = QPushButton('선택 회차까지 기존 최종 참고작 검사 화면 열기')
        self.audit_button.setObjectName('referenceRecheckOpenAudit')
        self.audit_button.clicked.connect(self.open_audit)
        for button in (self.editor_button, self.audit_button):
            button.setEnabled(False)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.through.valueChanged.connect(self.invalidate)

    def invalidate(self, *_args):
        self._queue = None
        self._identity = None
        self._selection = ()
        self.queue_table.setRowCount(0)
        self.editor_button.setEnabled(False)
        self.audit_button.setEnabled(False)
        self.summary.setText('작품·원고·참고작 변경 후 다시 조회하세요. 기존 PASS·출판 승인 아님.')

    def refresh(self):
        self.invalidate()
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

    def _current(self):
        session = self.authoring.session
        if session.store is None or session.path is None or session.project_id is None:
            raise ReferenceRecheckQueueError('기존 작품을 먼저 열어 주세요.')
        if _busy(self.authoring):
            raise ReferenceRecheckQueueError('진행 중인 모델·배치 집필을 마친 뒤 조회하세요.')
        try:
            if _unsaved(self.authoring):
                raise ReferenceRecheckQueueError('미저장 원고·장면·플롯을 직접 정리하세요.')
        except (ValueError, OSError, LookupError):
            raise ReferenceRecheckQueueError('미저장 원고 상태를 확인할 수 없습니다.') from None
        return session, (str(session.path), str(session.project_id))

    def preview_queue(self):
        self.invalidate()
        try:
            session, identity = self._current()
            selection = tuple(self.authoring.auto_panel.reference_paths)
            queue = build_reference_recheck_queue(
                session.store, identity[1], through_episode=self.through.value(),
                selected_paths=selection)
        except (ReferenceRecheckQueueError, ValueError, OSError):
            self.summary.setText('현재 작품·선택 참고작·원고 기록을 확인하지 못했습니다.')
            return
        self._queue, self._identity, self._selection = queue, identity, selection
        self.queue_table.setRowCount(len(queue.chapters))
        for index, chapter in enumerate(queue.chapters):
            values = (str(chapter.episode),
                      '저장됨' if chapter.final_present else '누락',
                      chapter.saved_scope_status, chapter.human_review_status,
                      _ACTION_LABELS.get(chapter.next_action, '직접 확인'))
            for col, value in enumerate(values):
                self.queue_table.setItem(index, col, QTableWidgetItem(value))
        self.editor_button.setEnabled(True)
        self.audit_button.setEnabled(True)
        formats = ', '.join(
            f'{ext.lstrip(".").upper()} {count}'
            for ext, count in queue.selected_formats if count)
        self.summary.setText(
            f'{queue.through_episode}화 대기열: 최종본 누락 {queue.missing_final}화, '
            f'현재 선택 참고작 재검사 필요 {queue.needs_fresh_scan}화, '
            f'과거 검사 범위 기록 {queue.prior_scope_only}화. '
            f'직접 선택 {queue.selected_count}개 ({formats}). '
            '과거 기록은 현재 선택 파일과 동일하다고 인정하지 않습니다. '
            '이 화면은 검사·모델 실행·출판 승인이 아닙니다.')

    def _consume_selected(self):
        snapshot, identity, selection = self._queue, self._identity, self._selection
        index = self.queue_table.currentRow()
        if snapshot is None or identity is None or not 0 <= index < len(snapshot.chapters):
            raise ReferenceRecheckQueueError('대기열을 조회하고 한 회차를 선택하세요.')
        chapter = snapshot.chapters[index]
        session, current_identity = self._current()
        if identity != current_identity:
            raise ReferenceRecheckQueueError('작품이 변경됐습니다. 다시 조회하세요.')
        if tuple(self.authoring.auto_panel.reference_paths) != selection:
            raise ReferenceRecheckQueueError('참고작 선택이 변경됐습니다. 다시 조회하세요.')
        require_current_reference_recheck_queue(
            snapshot, session.store, identity[1],
            through_episode=snapshot.through_episode, selected_paths=selection)
        self._queue = None
        self._identity = None
        self._selection = ()
        self.editor_button.setEnabled(False)
        self.audit_button.setEnabled(False)
        return chapter, identity

    def open_editor(self):
        try:
            chapter, identity = self._consume_selected()
            if chapter.revision is None:
                self.summary.setText('저장되지 않은 회차입니다. 기존 집필 화면에서 직접 생성하세요.')
                return
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=chapter.episode)
            self.summary.setText(decision.message)
        except (ReferenceRecheckQueueError, ValueError, OSError):
            self.invalidate()
            self.summary.setText('원고·참고작이 변경됐습니다. 대기열을 다시 조회하세요.')

    def open_audit(self):
        try:
            chapter, identity = self._consume_selected()
            if not chapter.final_present:
                self.summary.setText('저장 최종본이 없습니다. 먼저 직접 작성·저장하세요.')
                return
            opened = self.authoring.feature_workspace_hub.open_feature(
                'final_reference_audit_panel', episode_number=chapter.episode,
                project_identity=identity)
            if opened:
                self.summary.setText(
                    f'1~{chapter.episode}화 기존 최종 참고작 검사 화면을 열었습니다. '
                    '전수 비교·기록 저장은 별도 작가 승인·클릭이 필요합니다.')
            else:
                self.summary.setText('기존 검사 화면을 열지 못했습니다. 작품을 확인하세요.')
        except (ReferenceRecheckQueueError, ValueError, OSError):
            self.invalidate()
            self.summary.setText('원고·참고작이 변경됐습니다. 대기열을 다시 조회하세요.')
