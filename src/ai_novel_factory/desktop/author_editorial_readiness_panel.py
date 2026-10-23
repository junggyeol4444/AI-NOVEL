"""Windows 네이티브 편집 이슈·최종본·QC·검수 상태의 읽기 전용 통합 화면."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import (
    QFileDialog, QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_editorial_readiness import (
    EditorialReadinessError, build_editorial_readiness_matrix,
    require_current_editorial_readiness,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import check_author_navigation


_TARGETS = (
    ('편집 이슈 직접 기록·종료', 'editorial_issue_panel'),
    ('원고 수동 재작성', 'manual_rewrite_panel'),
    ('저장 QC 현황', 'review_dashboard_panel'),
    ('최종본 참고작 전수 검사', 'final_reference_audit_panel'),
    ('작가 수동 검수', 'review_worklist'),
    ('EPUB3 다권 계획', 'epub_volume_panel'),
    ('SQLite 별도 백업', 'project_backup_panel'),
    ('출판 별도 승인 화면', 'publication_approval_panel'),
)


class AuthorEditorialReadinessPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 편집 이슈·QC·검수 연결 현황', parent)
        self.authoring = authoring
        self._identity = None
        self._snapshot = None
        self._folder_identity = None
        root = QVBoxLayout(self)
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        self.folder.setObjectName('authorEditorialFolder')
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder)
        select = QPushButton('기존 편집 이슈 기록 폴더 직접 선택')
        select.clicked.connect(self.choose_folder)
        folder_row.addWidget(select)
        root.addLayout(folder_row)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('마지막 회차'))
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.valueChanged.connect(self.invalidate)
        controls.addWidget(self.through)
        preview = QPushButton('원고·QC·검수·편집 이슈 현황 직접 조회')
        preview.clicked.connect(self.refresh)
        controls.addWidget(preview)
        root.addLayout(controls)
        self.status = QLabel('기존 작품과 편집 이슈 기록 폴더를 직접 선택하세요. 출판 승인 화면이 아닙니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName('authorEditorialReadinessTable')
        self.table.setHorizontalHeaderLabels((
            '회차', '최종본', '미해결', '과거 종료', '현재 종료', '검수 기록', '참고작 범위'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        action = QHBoxLayout()
        self.stage = QComboBox()
        for title, key in _TARGETS:
            self.stage.addItem(title, key)
        action.addWidget(self.stage)
        self.open_button = QPushButton('선택한 회차의 기존 화면 열기 (별도 클릭)')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_stage)
        action.addWidget(self.open_button)
        root.addLayout(action)

    def invalidate(self, *_args):
        self._identity = self._snapshot = self._folder_identity = None
        self.table.setRowCount(0)
        self.open_button.setEnabled(False)
        self.status.setText('현재 원고·검수·편집 기록을 다시 직접 조회하세요.')

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, '기존 편집 이슈 기록 폴더 선택')
        if path:
            self.invalidate()
            self.folder.setText(path)

    def refresh(self):
        self.invalidate()
        try:
            session, identity = _current_author_state(self.authoring)
            folder = Path(self.folder.text())
            snapshot = build_editorial_readiness_matrix(
                session.store, identity[1], through_episode=self.through.value(),
                issue_folder=folder)
        except (EditorialReadinessError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('작품·최종본·편집 기록을 조회하지 못했습니다. 자동 승인하지 않습니다.')
            return
        self._identity, self._snapshot = identity, snapshot
        self._folder_identity = str(folder)
        self.table.setRowCount(len(snapshot.chapters))
        for i, row in enumerate(snapshot.chapters):
            values = (str(row.episode), '있음' if row.final_present else '없음',
                      str(row.open_issues), str(row.stale_closures),
                      str(row.closed_current), row.review_status, row.reference_status)
            for col, value in enumerate(values):
                self.table.setItem(i, col, QTableWidgetItem(value))
        self.open_button.setEnabled(bool(snapshot.chapters))
        self.status.setText(
            f'{snapshot.through_episode}화 · 최종본 없음 {snapshot.missing_final}화 · '
            f'미해결/과거 종료 편집 이슈 {snapshot.pending_issues}건. '
            '편집 기록상 미해결이 없어도 QC·저작권·출판 승인이 아닙니다.')

    def open_stage(self):
        identity, snapshot, folder = self._identity, self._snapshot, self._folder_identity
        row_index = self.table.currentRow()
        target = self.stage.currentData()
        self.invalidate()  # 한 번의 명시적 이동 뒤 미리보기 재사용 금지
        if (identity is None or snapshot is None or folder is None
                or str(self.folder.text()) != folder
                or not 0 <= row_index < len(snapshot.chapters)
                or target not in {key for _, key in _TARGETS}):
            self.status.setText('현재 조회한 회차와 이동할 화면을 다시 선택하세요.')
            return
        row = snapshot.chapters[row_index]
        if row.revision is None:
            self.status.setText('저장되지 않은 회차입니다. 기존 편집기에서 직접 작성하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise EditorialReadinessError('작품이 변경됐습니다.')
            require_current_editorial_readiness(
                snapshot, session.store, identity[1], issue_folder=folder)
            decision = check_author_navigation(
                self.authoring, project_identity=identity, episode=row.episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    target, episode_number=row.episode, project_identity=identity):
                raise EditorialReadinessError('기존 기능 화면을 열지 못했습니다.')
        except (EditorialReadinessError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('원고·검수·편집 기록이 변경됐거나 화면을 열지 못했습니다. 다시 조회하세요.')
            return
        self.status.setText(f'{row.episode}화 기존 화면을 열었습니다. 검수·수정·승인은 별도 직접 실행입니다.')