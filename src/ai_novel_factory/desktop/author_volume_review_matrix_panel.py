"""기존 Windows PySide6 집필 화면에 붙는 권별 검수·EPUB3 읽기 전용 인계."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_volume_review_matrix import (
    VolumeReviewMatrixError, build_volume_review_matrix,
    require_current_volume_review_matrix,
)
from ai_novel_factory.author_reference_selection_lease import (
    ReferenceLeaseError, preview_reference_selection,
    require_current_reference_selection,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError


_STAGES = (
    ('저장 원고·QC 현황', 'review_dashboard_panel'),
    ('작가 직접 검수', 'review_worklist'),
    ('최종본 참고작 전수 검사', 'final_reference_audit_panel'),
    ('편집 이슈·재작성', 'manual_rewrite_panel'),
    ('EPUB3 다권 목차', 'epub_toc_panel'),
    ('EPUB3 다권 생성 화면', 'epub_volume_panel'),
    ('EPUB3 원고 대조', 'epub_source_alignment_panel'),
    ('EPUB3 여러 권 Reader', 'private_volume_reader_panel'),
    ('EPUB3 검색·책갈피', 'epub_private_bookmarks_panel'),
    ('SQLite 안전 백업', 'project_backup_panel'),
    ('SQLite 새 복원 사본', 'project_restore_panel'),
    ('출판 별도 승인 화면', 'publication_approval_panel'),
)


class AuthorVolumeReviewMatrixPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 권별 원고·검수·EPUB3 작업 현황', parent)
        self.authoring = authoring
        self._identity = None
        self._snapshot = None
        self._references = None
        self._reference_paths = ()
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            '작가 직접 조회 전용입니다. QC 합격·저작권 판단·출판 승인·EPUB 생성은 하지 않습니다.'))
        controls = QHBoxLayout()
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.setObjectName('authorVolumeReviewThrough')
        controls.addWidget(QLabel('마지막 회차'))
        controls.addWidget(self.through)
        self.preview_button = QPushButton('저장 최종본·검수·참고작·권별 현황 직접 조회')
        self.preview_button.clicked.connect(self.refresh)
        controls.addWidget(self.preview_button)
        root.addLayout(controls)
        self.status = QLabel('작품을 열고 조회 버튼을 누르세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.table = QTableWidget(0, 8)
        self.table.setObjectName('authorVolumeReviewTable')
        self.table.setHorizontalHeaderLabels((
            '권', '회차', '최종본', '누락', 'QC 확인', '수동 검수', '참고작 범위', '크기 초과'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        actions = QHBoxLayout()
        self.stage = QComboBox()
        for caption, target in _STAGES:
            self.stage.addItem(caption, target)
        actions.addWidget(self.stage)
        self.open_button = QPushButton('선택한 권의 기존 작업 화면 열기 (별도 클릭)')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_stage)
        actions.addWidget(self.open_button)
        root.addLayout(actions)
        self.through.valueChanged.connect(self.invalidate)

    def invalidate(self, *_args):
        self._identity = None
        self._snapshot = None
        self._references = None
        self._reference_paths = ()
        self.open_button.setEnabled(False)
        self.table.setRowCount(0)
        self.status.setText('현재 작품·원고·참고작 선택을 다시 조회하세요.')

    def refresh(self):
        self.invalidate()
        try:
            session, identity = _current_author_state(self.authoring)
            selected = tuple(self.authoring.auto_panel.reference_paths)
            references = preview_reference_selection(selected)
            snapshot = build_volume_review_matrix(
                session.store, identity[1], through_episode=self.through.value())
        except (BatchScopeBridgeError, VolumeReviewMatrixError,
                ReferenceLeaseError, OSError, ValueError):
            self.status.setText('기존 작품·원고·참고작을 조회하지 못했습니다. 다시 선택하세요.')
            return
        self._identity, self._snapshot = identity, snapshot
        self._references, self._reference_paths = references, selected
        self.table.setRowCount(len(snapshot.rows))
        for index, row in enumerate(snapshot.rows):
            values = (str(row.volume), f'{row.first_episode}~{row.last_episode}',
                      str(row.saved_final), str(row.missing_final),
                      str(row.qc_action_count), str(row.human_review_action_count),
                      str(row.reference_action_count), str(row.oversized_final))
            for col, value in enumerate(values):
                self.table.setItem(index, col, QTableWidgetItem(value))
        self.open_button.setEnabled(bool(snapshot.rows))
        self.status.setText(
            f'{snapshot.through_episode}화 · {len(snapshot.rows)}권 · '
            f'직접 선택한 참고작 {references.count}개. '
            '조회는 기록 현황일 뿐 QC·저작권·출판 승인이 아닙니다.')

    def open_stage(self):
        snapshot, identity = self._snapshot, self._identity
        references, paths = self._references, self._reference_paths
        target = self.stage.currentData()
        index = self.table.currentRow()
        # 클릭 후 과거 미리보기/파일 지문을 재사용하지 않는다.
        self._snapshot = self._identity = self._references = None
        self._reference_paths = ()
        self.open_button.setEnabled(False)
        if (snapshot is None or identity is None or references is None or
                not 0 <= index < len(snapshot.rows) or
                target not in {key for _, key in _STAGES}):
            self.status.setText('먼저 현황을 조회하고 한 권을 직접 선택하세요.')
            return
        row = snapshot.rows[index]
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise VolumeReviewMatrixError('작품이 변경됐습니다.')
            require_current_reference_selection(references, paths)
            if tuple(self.authoring.auto_panel.reference_paths) != paths:
                raise ReferenceLeaseError('참고작 선택이 변경됐습니다.')
            require_current_volume_review_matrix(snapshot, session.store, identity[1])
            if target == 'epub_volume_panel' and (row.missing_final or row.oversized_final):
                raise VolumeReviewMatrixError('최종본 누락·크기 초과로 권별 생성 인계를 보류합니다.')
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    target, episode_number=row.last_episode,
                    project_identity=identity):
                raise VolumeReviewMatrixError('기존 기능 화면을 열지 못했습니다.')
        except (BatchScopeBridgeError, VolumeReviewMatrixError,
                ReferenceLeaseError, ValueError, OSError):
            self.status.setText('원고·참고작·검수·작품이 변경됐거나 화면을 열지 못했습니다. 다시 조회하세요.')
            return
        self.status.setText(
            f'{row.volume}권 {row.first_episode}~{row.last_episode}화의 기존 화면을 열었습니다. '
            '검사·저장·EPUB 생성·출판 승인은 별도 클릭입니다.')
