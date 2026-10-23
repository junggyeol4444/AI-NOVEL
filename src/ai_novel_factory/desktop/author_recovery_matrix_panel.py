"""기존 Windows GUI에서 저장 회차·임시 장면·중단 기록을 함께 조회한다."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_recovery_matrix import (
    AuthorRecoveryMatrixError, preview_author_recovery_matrix,
    require_current_author_recovery_matrix,
)
from .author_navigation_contract import _busy, _unsaved, select_saved_episode
from .author_batch_scope_bridge import (
    BatchScopeBridgeError, preview_author_batch_scope, handoff_author_batch_scope,
)
from .scene_checkpoint_panel import default_scene_checkpoint_directory
from .batch_recovery_panel import default_batch_journal_directory


_TARGETS = (
    ('장면별 임시 초고 현황', 'scene_checkpoint_panel'),
    ('이전 배치 실행 기록', 'batch_recovery_panel'),
    ('저장 초고 직접 재작성', 'manual_rewrite_panel'),
    ('회차 QC 검수 현황', 'review_dashboard_panel'),
    ('작가 수동 검수 기록', 'review_worklist'),
    ('최종본 참고작 전수 검사', 'final_reference_audit_panel'),
)


class AuthorRecoveryMatrixPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('회차·장면·배치 중단 기록 통합 확인 (읽기 전용)', parent)
        self.authoring = authoring
        self._snapshot = None
        self._identity = None
        self._batch_snapshot = None
        self._reference_lease = None
        layout = QVBoxLayout(self)
        notice = QLabel(
            'SQLite 저장 회차가 정본입니다. 임시 장면 파일은 미검수 AI 초안이며 '
            '이 화면에서 재개·모델 실행·QC 합격·출판 승인을 수행하지 않습니다. '
            '이전 모델 실행 동의는 새 배치에 이전되지 않습니다.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        controls = QHBoxLayout()
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.setObjectName('authorRecoveryThrough')
        self.preview_button = QPushButton('저장 회차·장면·중단 기록 직접 조회')
        self.preview_button.setObjectName('authorRecoveryPreview')
        controls.addWidget(QLabel('마지막 회차'))
        controls.addWidget(self.through)
        controls.addWidget(self.preview_button)
        layout.addLayout(controls)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ('회차', 'SQLite 저장 상태', '원고 revision', '임시 묶음', '미검증 장면 파일'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setObjectName('authorRecoveryMatrixTable')
        layout.addWidget(self.table)
        self.status = QLabel('작품을 열고 조회 버튼을 직접 누르세요.')
        self.status.setWordWrap(True)
        self.status.setObjectName('authorRecoveryStatus')
        layout.addWidget(self.status)
        self.editor_button = QPushButton('선택한 저장 회차를 기존 편집기로 이동')
        self.editor_button.setObjectName('authorRecoveryOpenEditor')
        layout.addWidget(self.editor_button)
        tool_row = QHBoxLayout()
        self.tool_selector = QComboBox()
        self.tool_selector.setObjectName('authorRecoveryToolSelector')
        for label, target in _TARGETS:
            self.tool_selector.addItem(label, target)
        self.tool_button = QPushButton('선택한 기존 검수·재작성·중단 화면 열기')
        self.tool_button.setObjectName('authorRecoveryOpenTool')
        tool_row.addWidget(self.tool_selector)
        tool_row.addWidget(self.tool_button)
        layout.addLayout(tool_row)
        self.handoff_button = QPushButton('확인한 범위를 기존 AI 배치 설정에 입력 (실행 안 함)')
        self.handoff_button.setObjectName('authorRecoveryHandoffBatch')
        layout.addWidget(self.handoff_button)
        self.preview_button.clicked.connect(self.refresh)
        self.through.valueChanged.connect(self.invalidate)
        self.editor_button.clicked.connect(self.open_editor)
        self.tool_button.clicked.connect(self.open_tool)
        self.handoff_button.clicked.connect(self.handoff_batch)
        self.invalidate()

    def invalidate(self, *_args):
        self._snapshot = None
        self._identity = None
        self._batch_snapshot = None
        self._reference_lease = None
        self.table.setRowCount(0)
        self.editor_button.setEnabled(False)
        self.tool_button.setEnabled(False)
        self.handoff_button.setEnabled(False)
        self.status.setText('현재 작품·범위의 저장 기록을 다시 직접 조회하세요.')

    def _current(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None or session.path is None:
            raise AuthorRecoveryMatrixError('먼저 기존 작품 SQLite를 여세요.')
        if _busy(self.authoring):
            raise AuthorRecoveryMatrixError('모델·배치 실행 중에는 작업 범위를 이동할 수 없습니다.')
        try:
            if _unsaved(self.authoring):
                raise AuthorRecoveryMatrixError('미저장 원고·장면·최종본을 먼저 직접 정리하세요.')
        except (ValueError, OSError, LookupError):
            raise AuthorRecoveryMatrixError('현재 편집 원고를 확인할 수 없습니다.') from None
        return session, (str(session.path), str(session.project_id))

    def refresh(self):
        self.invalidate()
        try:
            session, identity = self._current()
            snapshot = preview_author_recovery_matrix(
                session.store, session.path, str(session.project_id),
                through_episode=self.through.value(),
                checkpoint_root=default_scene_checkpoint_directory(),
                journal_root=default_batch_journal_directory())
            batch_identity, batch_snapshot, reference_lease = preview_author_batch_scope(
                self.authoring, through_episode=self.through.value())
            if identity != batch_identity:
                raise AuthorRecoveryMatrixError('작품이 변경됐습니다. 다시 조회하세요.')
        except (AuthorRecoveryMatrixError, BatchScopeBridgeError, ValueError, OSError):
            self.status.setText('현재 원고·임시 장면·중단 기록 또는 참고작 선택을 조회하지 못했습니다.')
            return
        self._identity = identity
        self._snapshot = snapshot
        self._batch_snapshot = batch_snapshot
        self._reference_lease = reference_lease
        self.table.setRowCount(len(snapshot.chapters))
        for row_index, chapter in enumerate(snapshot.chapters):
            for col, value in enumerate((
                chapter.episode, chapter.saved_state,
                chapter.revision if chapter.revision is not None else '없음',
                chapter.checkpoint_sets, chapter.unverified_stage_files,
            )):
                self.table.setItem(row_index, col, QTableWidgetItem(str(value)))
        self.editor_button.setEnabled(True)
        self.tool_button.setEnabled(True)
        self.handoff_button.setEnabled(True)
        self.status.setText(
            f'1~{snapshot.through_episode}화: 미생성 {snapshot.missing}화, '
            f'초고만 저장 {snapshot.draft_only}화, 최종본 저장 {snapshot.final_count}화, '
            f'기존 배치 기록 {snapshot.journal_count}건, 최근 기록 '
            f'{snapshot.last_recorded_state} / 현재 {snapshot.last_current_state}. '
            '임시 파일 개수는 재개 가능 여부나 품질 합격 증명이 아닙니다.')

    def _require_current(self):
        session, identity = self._current()
        if self._snapshot is None or identity != self._identity:
            raise AuthorRecoveryMatrixError('작품이 변경됐습니다. 다시 조회하세요.')
        require_current_author_recovery_matrix(
            self._snapshot, session.store, session.path, str(session.project_id),
            checkpoint_root=default_scene_checkpoint_directory(),
            journal_root=default_batch_journal_directory())
        return session, identity

    def _selected(self):
        if self._snapshot is None:
            return None
        index = self.table.currentRow()
        if index < 0 or index >= len(self._snapshot.chapters):
            return None
        return self._snapshot.chapters[index]

    def open_editor(self):
        chapter = self._selected()
        if chapter is None or not chapter.can_open_saved_editor:
            self.status.setText('저장된 회차를 선택하세요. 미생성 회차는 자동 생성하지 않습니다.')
            return
        try:
            self._require_current()
            decision = select_saved_episode(
                self.authoring, project_identity=self._identity,
                episode=chapter.episode)
            self.status.setText(decision.message)
        except (AuthorRecoveryMatrixError, ValueError, OSError):
            self.invalidate()

    def open_tool(self):
        chapter = self._selected()
        target = self.tool_selector.currentData()
        if chapter is None or target not in {key for _, key in _TARGETS}:
            self.status.setText('먼저 회차와 기존 도구를 직접 선택하세요.')
            return
        try:
            self._require_current()
            if target not in ('scene_checkpoint_panel', 'batch_recovery_panel'):
                if not chapter.can_open_saved_editor:
                    self.status.setText('이 작업은 먼저 SQLite에 저장된 회차가 필요합니다.')
                    return
                decision = select_saved_episode(
                    self.authoring, project_identity=self._identity,
                    episode=chapter.episode)
                if not decision.allowed:
                    self.status.setText(decision.message)
                    return
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    target, episode_number=chapter.episode,
                    project_identity=self._identity):
                self.status.setText('기존 기능 화면을 열지 못했습니다.')
                return
            self.status.setText(
                f'{chapter.episode}화 관련 기존 화면을 열었습니다. '
                '검수·재작성 저장·모델 실행은 별도 직접 버튼에서만 수행됩니다.')
        except (AuthorRecoveryMatrixError, ValueError, OSError):
            self.invalidate()

    def handoff_batch(self):
        snapshot = self._batch_snapshot
        lease = self._reference_lease
        identity = self._identity
        self._batch_snapshot = None
        self._reference_lease = None
        self.handoff_button.setEnabled(False)
        if snapshot is None or lease is None or identity is None:
            self.status.setText('현재 회차와 참고작을 먼저 직접 조회하세요.')
            return
        try:
            self._require_current()
            message = handoff_author_batch_scope(
                self.authoring, project_identity=identity,
                snapshot=snapshot, reference_lease=lease)
            self.status.setText(message + ' 임시 장면은 자동 재개하지 않습니다.')
        except (AuthorRecoveryMatrixError, BatchScopeBridgeError, ValueError, OSError):
            self.invalidate()
