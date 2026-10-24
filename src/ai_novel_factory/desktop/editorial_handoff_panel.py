"""Windows GUI: explicit read-only 1~1000 episode editorial handoff view."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.editorial_handoff_gate import build_editorial_handoff
from ai_novel_factory.author_editorial_issue_detail_audit import (
    AuthorEditorialIssueDetailError, build_author_editorial_issue_detail_audit,
    require_current_author_editorial_issue_detail_audit,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import select_saved_episode


class EditorialHandoffPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('원고 인계 차단 현황 (읽기 전용·출판 불가)', parent)
        self.authoring = authoring
        self._detail_identity = None
        self._detail_snapshot = None
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

        # 기존 편집 이슈 기록의 실제 개별 메모/종료 revision을 조회한다.
        folder_row = QHBoxLayout()
        self.detail_folder = QLineEdit()
        self.detail_folder.setReadOnly(True)
        self.detail_folder.setObjectName('authorEditorialIssueDetailFolder')
        folder_row.addWidget(self.detail_folder)
        choose_folder = QPushButton('기존 편집 이슈 폴더 직접 선택')
        choose_folder.clicked.connect(self.choose_detail_folder)
        folder_row.addWidget(choose_folder)
        root.addLayout(folder_row)
        detail_preview = QPushButton('1~선택 회차의 개별 이슈·원고·QC·참고작 실제 기록 대조')
        detail_preview.setObjectName('authorEditorialIssueDetailPreview')
        detail_preview.clicked.connect(self.preview_detail)
        root.addWidget(detail_preview)
        self.detail_table = QTableWidget(0, 7)
        self.detail_table.setObjectName('authorEditorialIssueDetailTable')
        self.detail_table.setHorizontalHeaderLabels((
            '회차', '분류', '종료·수정 상태', '현재 원고 revision',
            '작가 이슈 메모', '수동 검수 기록', '참고작 범위'))
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_table.setMaximumHeight(280)
        root.addWidget(self.detail_table)
        self.detail_status = QLabel('NOT_RUN: 기존 이슈 기록 폴더를 직접 선택해 조회하세요.')
        self.detail_status.setWordWrap(True)
        root.addWidget(self.detail_status)
        detail_row = QHBoxLayout()
        self.detail_target = QComboBox()
        self.detail_target.addItem('기존 편집 이슈 직접 기록·종료 화면', 'editorial_issue_panel')
        self.detail_target.addItem('기존 초고 수동 재작성 화면', 'manual_rewrite_panel')
        detail_row.addWidget(self.detail_target)
        self.detail_open = QPushButton('선택 이슈의 기존 작가 화면 열기 (별도 클릭)')
        self.detail_open.setObjectName('authorEditorialIssueDetailOpen')
        self.detail_open.setEnabled(False)
        self.detail_open.clicked.connect(self.open_detail)
        detail_row.addWidget(self.detail_open)
        root.addLayout(detail_row)
        self.through.valueChanged.connect(self.invalidate_detail)

    def invalidate(self):
        self.detail_folder.clear()
        self.invalidate_detail()
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

    def invalidate_detail(self, *_args):
        self._detail_identity = None
        self._detail_snapshot = None
        self.detail_table.setRowCount(0)
        self.detail_open.setEnabled(False)
        self.detail_status.setText('작품·범위·원고·편집 기록 변경 시 다시 직접 조회하세요.')

    def choose_detail_folder(self):
        directory = QFileDialog.getExistingDirectory(self, '기존 편집 이슈 기록 폴더 선택')
        if directory:
            self.invalidate_detail()
            self.detail_folder.setText(directory)

    def preview_detail(self):
        self.invalidate_detail()
        try:
            session, identity = _current_author_state(self.authoring)
            folder = self.detail_folder.text()
            if not folder:
                raise AuthorEditorialIssueDetailError('기존 기록 폴더를 직접 선택하세요.')
            snapshot = build_author_editorial_issue_detail_audit(
                session.store, identity[1], through_episode=self.through.value(),
                issue_folder=folder)
        except (AuthorEditorialIssueDetailError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.detail_status.setText('현재 저장 원고·편집 이슈·QC를 읽지 못했습니다. 자동 승인 없음.')
            return
        self._detail_identity, self._detail_snapshot = identity, snapshot
        self.detail_table.setRowCount(len(snapshot.rows))
        for index, row in enumerate(snapshot.rows):
            values = (str(row.episode), row.category, row.state,
                      str(row.current_revision) if row.current_revision is not None else '미저장',
                      row.note[:150], row.review_status, row.reference_status)
            for column, value in enumerate(values):
                self.detail_table.setItem(index, column, QTableWidgetItem(value))
        self.detail_open.setEnabled(bool(snapshot.rows))
        self.detail_status.setText(
            f'{snapshot.through_episode}화 / 이슈 {len(snapshot.rows)}건 / '
            f'열린 이슈 {snapshot.open_count}건 / 과거 판정 {snapshot.stale_count}건 / '
            f'현재 원고 기준 종료 {snapshot.current_closed_count}건. '
            '작가 메모·종료 기록의 표시이며 QC 합격·저작권·출판 승인이 아닙니다.')

    def open_detail(self):
        snapshot, identity = self._detail_snapshot, self._detail_identity
        index = self.detail_table.currentRow()
        target = self.detail_target.currentData()
        self.invalidate_detail()  # 이전 조회의 반복 인계 금지
        if (snapshot is None or identity is None
                or not 0 <= index < len(snapshot.rows)
                or target not in {'editorial_issue_panel', 'manual_rewrite_panel'}
                or not self.detail_folder.text()
                or str(Path(self.detail_folder.text()).resolve()) != snapshot.folder
                or self.through.value() != snapshot.through_episode):
            self.detail_status.setText('현재 조회한 이슈와 이동 화면을 다시 직접 선택하세요.')
            return
        row = snapshot.rows[index]
        if row.current_revision is None or not row.final_present:
            self.detail_status.setText('저장 최종본이 없는 회차는 자동 생성하지 않습니다.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise AuthorEditorialIssueDetailError('작품이 변경됐습니다.')
            require_current_author_editorial_issue_detail_audit(
                snapshot, session.store, identity[1])
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=row.episode)
            if not decision.allowed:
                self.detail_status.setText(decision.message)
                return
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    target, episode_number=row.episode, project_identity=identity):
                raise AuthorEditorialIssueDetailError('기존 작가 화면을 열지 못했습니다.')
            if target == 'editorial_issue_panel':
                panel = getattr(self.authoring, 'editorial_issue_panel', None)
                if panel is not None:
                    panel.number.setValue(row.episode)  # 저장·종료 실행 아님
        except (AuthorEditorialIssueDetailError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.detail_status.setText('현재 원고·이슈 기록이 변경됐거나 기존 화면을 열지 못했습니다.')
            return
        self.detail_status.setText(
            f'{row.episode}화의 기존 작가 화면만 열었습니다. '
            '수정 저장·이슈 종료·검수·출판은 작가가 별도로 직접 결정합니다.')
