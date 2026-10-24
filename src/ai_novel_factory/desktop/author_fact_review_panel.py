"""Windows GUI read-only author-fact/QC/human-review scope matrix."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_fact_review_matrix import build_author_fact_review_matrix
from ai_novel_factory.author_fact_final_alignment import (
    AuthorFactFinalAlignmentError, build_author_fact_final_alignment,
    require_current_author_fact_final_alignment,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import select_saved_episode


class AuthorFactReviewPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('인물 지식·복선·시간선 근거와 QC 연계 (읽기 전용)', parent)
        self.authoring = authoring
        self._alignment = None
        self._alignment_identity = None
        layout = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.valueChanged.connect(self.invalidate_alignment)
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

        # 기존 QC 조회와 별개인 실제 저장 최종본 문자열 대조. 자동 변경 없음.
        read_alignment = QPushButton('작가 사실·저장 최종본 1~선택 회차 전체 대조')
        read_alignment.setObjectName('authorFactFinalReadOnly')
        read_alignment.clicked.connect(self.preview_fact_alignment)
        layout.addWidget(read_alignment)
        self.alignment_table = QTableWidget(0, 7)
        self.alignment_table.setHorizontalHeaderLabels([
            '회차', '최종본 글자', '적용 사실', '근거 변경',
            '값 문자열 발견', '값 문자열 미발견', '동시 다른 값 후보',
        ])
        self.alignment_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alignment_table.setMaximumHeight(250)
        layout.addWidget(self.alignment_table)
        self.alignment_status = QLabel('NOT_RUN: 작가가 직접 대조한 뒤 별도로 회차를 선택하세요.')
        self.alignment_status.setWordWrap(True)
        layout.addWidget(self.alignment_status)
        self.open_alignment_button = QPushButton('선택한 저장 회차를 기존 편집기로 이동 (별도 클릭)')
        self.open_alignment_button.setEnabled(False)
        self.open_alignment_button.clicked.connect(self.open_fact_alignment)
        layout.addWidget(self.open_alignment_button)

    def invalidate(self):
        self.table.setRowCount(0)
        self.invalidate_alignment()
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

    def invalidate_alignment(self, *_args):
        self._alignment = None
        self._alignment_identity = None
        self.alignment_table.setRowCount(0)
        self.open_alignment_button.setEnabled(False)
        self.alignment_status.setText('작품·범위·원고·사실 기록 변경 시 다시 직접 조회하세요.')

    def preview_fact_alignment(self):
        self.invalidate_alignment()
        try:
            session, identity = _current_author_state(self.authoring)
            panel = getattr(self.authoring, 'author_fact_panel', None)
            folder = panel.folder.text() if panel is not None else ''
            snapshot = build_author_fact_final_alignment(
                session.store, identity[1], folder=folder,
                through_episode=self.through.value())
        except (AuthorFactFinalAlignmentError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.alignment_status.setText('현재 저장 원고·작가 사실 기록을 읽지 못했습니다. 직접 선택을 확인하세요.')
            return
        self._alignment = snapshot
        self._alignment_identity = identity
        self.alignment_table.setRowCount(len(snapshot.rows))
        for index, row in enumerate(snapshot.rows):
            cells = (row.episode, row.final_chars, row.active_facts,
                     row.stale_sources, row.value_found, row.value_not_found,
                     row.conflicting_keys)
            for column, value in enumerate(cells):
                self.alignment_table.setItem(index, column, QTableWidgetItem(str(value)))
        self.open_alignment_button.setEnabled(True)
        self.alignment_status.setText(
            f'{snapshot.through_episode}화 직접 대조: 최종본 누락 {snapshot.missing_final}화, '
            f'근거 변경 {snapshot.stale_source_rows}화, 검토 후보 {snapshot.review_candidate_rows}화. '
            '문자열 출현/미출현은 사실 진위·품질 PASS·출판 승인이 아닙니다.')

    def open_fact_alignment(self):
        snapshot, identity = self._alignment, self._alignment_identity
        row_index = self.alignment_table.currentRow()
        if (snapshot is None or identity is None
                or not 0 <= row_index < len(snapshot.rows)):
            self.alignment_status.setText('먼저 전수 조회하고 저장 회차를 직접 선택하세요.')
            return
        row = snapshot.rows[row_index]
        self._alignment = None
        self._alignment_identity = None
        self.open_alignment_button.setEnabled(False)
        if row.revision is None:
            self.alignment_status.setText('저장되지 않은 회차는 자동 생성하거나 이동하지 않습니다.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity or self.through.value() != snapshot.through_episode:
                raise AuthorFactFinalAlignmentError('작품 또는 범위가 변경됐습니다.')
            require_current_author_fact_final_alignment(
                snapshot, session.store, identity[1])
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=row.episode)
            self.alignment_status.setText(decision.message)
        except (AuthorFactFinalAlignmentError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.alignment_status.setText('원고·사실 기록이 변경되어 이전 인계를 무효화했습니다.')
