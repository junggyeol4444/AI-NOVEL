"""Windows GUI: explicit opt-in and read-only scene checkpoint counts."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from ..author_scene_checkpoint_integrity import (
    SceneIntegrityError, audit_scene_checkpoints,
    require_current_scene_checkpoint_audit,
)
from .author_batch_scope_bridge import (
    BatchScopeBridgeError, _current_author_state,
    preview_author_batch_scope, handoff_author_batch_scope,
)
from .author_navigation_contract import select_saved_episode

from ..scene_checkpoint_store import (
    SceneCheckpointError, list_checkpoint_overviews,
)


def default_scene_checkpoint_directory() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation)
    if not base:
        raise SceneCheckpointError('로컬 장면 임시 저장 위치를 찾지 못했습니다.')
    return Path(base).resolve() / 'unapproved_scene_checkpoints'


class SceneCheckpointPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장면 단위 중단·재개 임시 저장 현황', parent)
        self.authoring = authoring
        self._audit = None
        self._audit_identity = None
        self._batch_scope = None
        self._reference_lease = None
        layout = QVBoxLayout(self)
        notice = QLabel(
            '사용자가 별도 승인한 실행에서만 생성된 AI 장면 초안을 로컬 임시 폴더에 저장합니다. '
            '저장된 원고 SQLite와 분리되며, 현재 설정·모델·작가 저장 자료가 같을 때만 재사용 후보입니다. '
            '임시 파일은 검수 합격·출판 승인이나 다음 모델 실행 승인이 아닙니다.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.refresh_button = QPushButton('현재 작품 임시 장면 개수 조회')
        self.refresh_button.setObjectName('sceneCheckpointRefresh')
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.status = QLabel('작품을 열고 조회하세요.')
        self.status.setWordWrap(True)
        self.status.setObjectName('sceneCheckpointStatus')
        layout.addWidget(self.status)
        audit_row = QHBoxLayout()
        audit_row.addWidget(QLabel('무결성 확인 마지막 회차'))
        self.audit_through = QSpinBox()
        self.audit_through.setRange(1, 1000)
        self.audit_through.setValue(30)
        self.audit_through.setObjectName('sceneIntegrityThrough')
        audit_row.addWidget(self.audit_through)
        self.audit_button = QPushButton('저장 원고·임시 장면 실제 파일 전수 조회')
        self.audit_button.setObjectName('sceneIntegrityPreview')
        audit_row.addWidget(self.audit_button)
        layout.addLayout(audit_row)
        self.audit_table = QTableWidget(0, 5)
        self.audit_table.setObjectName('sceneIntegrityTable')
        self.audit_table.setHorizontalHeaderLabels(
            ('회차', '저장 원고', '임시 묶음', '형식 일치 파일', '손상·불일치'))
        self.audit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.audit_table.setMaximumHeight(240)
        layout.addWidget(self.audit_table)
        self.audit_status = QLabel(
            '파일 형식 확인은 현재 모델 승인·작가 자료 일치·재개 가능 판정이 아닙니다.')
        self.audit_status.setWordWrap(True)
        layout.addWidget(self.audit_status)
        tool_row = QHBoxLayout()
        self.audit_target = QComboBox()
        for caption, key in (
            ('장면·배치 통합 현황', 'author_recovery_matrix_panel'),
            ('이전 배치 기록', 'batch_recovery_panel'),
            ('저장 초고 직접 재작성', 'manual_rewrite_panel'),
            ('회차 QC·검수', 'review_dashboard_panel'),
        ):
            self.audit_target.addItem(caption, key)
        tool_row.addWidget(self.audit_target)
        self.audit_open_button = QPushButton('선택 회차의 기존 화면 열기')
        self.audit_open_button.setObjectName('sceneIntegrityOpenExisting')
        tool_row.addWidget(self.audit_open_button)
        layout.addLayout(tool_row)
        self.audit_handoff_button = QPushButton(
            '전수 조회한 범위를 기존 AI 배치 설정에 입력 (실행 안 함)')
        self.audit_handoff_button.setObjectName('sceneIntegrityHandoffBatch')
        layout.addWidget(self.audit_handoff_button)
        self.audit_through.valueChanged.connect(self.invalidate_audit)
        self.audit_button.clicked.connect(self.preview_audit)
        self.audit_open_button.clicked.connect(self.open_audit_tool)
        self.audit_handoff_button.clicked.connect(self.handoff_audit_batch)
        self.invalidate_audit()

    def invalidate_audit(self, *_args):
        self._audit = self._audit_identity = None
        self._batch_scope = self._reference_lease = None
        self.audit_table.setRowCount(0)
        self.audit_open_button.setEnabled(False)
        self.audit_handoff_button.setEnabled(False)
        self.audit_status.setText('현재 작품·회차의 실제 파일을 다시 직접 조회하세요.')

    def preview_audit(self):
        self.invalidate_audit()
        try:
            session, identity = _current_author_state(self.authoring)
            audit = audit_scene_checkpoints(
                session.store, session.path, identity[1],
                through_episode=self.audit_through.value(),
                checkpoint_root=default_scene_checkpoint_directory())
            self._audit, self._audit_identity = audit, identity
            self.audit_table.setRowCount(len(audit.chapters))
            for i, row in enumerate(audit.chapters):
                values = (row.episode, row.stored_state, row.checkpoint_sets,
                          row.format_valid_files, row.invalid_files)
                for col, value in enumerate(values):
                    self.audit_table.setItem(i, col, QTableWidgetItem(str(value)))
            self.audit_open_button.setEnabled(True)
            try:
                scope_identity, scope, reference_lease = preview_author_batch_scope(
                    self.authoring, through_episode=self.audit_through.value())
                if scope_identity == identity:
                    self._batch_scope, self._reference_lease = scope, reference_lease
            except (BatchScopeBridgeError, ValueError, OSError):
                pass
            self.audit_handoff_button.setEnabled(
                audit.stage_files > 0 and audit.invalid_files == 0
                and self._batch_scope is not None)
            self.audit_status.setText(
                f'1~{audit.through_episode}화: 임시 장면 파일 {audit.stage_files}개, '
                f'형식·내용 SHA 불일치 {audit.invalid_files}개. '
                '정상 형식도 작가 원본/실행 동의 일치나 재개 승인 아님. '
                '이전 모델 실행 동의는 인계하지 않습니다.')
        except (SceneIntegrityError, BatchScopeBridgeError, OSError, ValueError):
            self.invalidate_audit()
            self.audit_status.setText('현재 원고 또는 임시 장면 파일을 신뢰할 수 없어 조회를 중단했습니다.')

    def _require_audit(self):
        session, identity = _current_author_state(self.authoring)
        if self._audit is None or identity != self._audit_identity:
            raise SceneIntegrityError('작품·원고 선택이 변경됐습니다.')
        require_current_scene_checkpoint_audit(
            self._audit, session.store, session.path, identity[1])
        return session, identity

    def open_audit_tool(self):
        audit = self._audit
        row_index = self.audit_table.currentRow()
        target = self.audit_target.currentData()
        if (audit is None or not 0 <= row_index < len(audit.chapters)
                or target not in ('author_recovery_matrix_panel',
                                  'batch_recovery_panel', 'manual_rewrite_panel',
                                  'review_dashboard_panel')):
            self.audit_status.setText('조회한 회차와 기존 화면을 직접 선택하세요.')
            return
        chapter = audit.chapters[row_index]
        try:
            _session, identity = self._require_audit()
            if target in ('manual_rewrite_panel', 'review_dashboard_panel'):
                if chapter.revision is None:
                    self.audit_status.setText('저장되지 않은 회차는 편집기로 이동할 수 없습니다.')
                    return
                decision = select_saved_episode(
                    self.authoring, project_identity=identity, episode=chapter.episode)
                if not decision.allowed:
                    self.audit_status.setText(decision.message)
                    return
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    target, episode_number=chapter.episode,
                    project_identity=identity):
                raise SceneIntegrityError('기존 기능 화면을 열지 못했습니다.')
            self.audit_status.setText(
                f'{chapter.episode}화 기존 화면을 열었습니다. 모델·검수·저장·출판은 별도 승인입니다.')
        except (SceneIntegrityError, BatchScopeBridgeError, ValueError, OSError):
            self.invalidate_audit()
            self.audit_status.setText('원고·임시 파일이 변경됐습니다. 다시 직접 조회하세요.')

    def handoff_audit_batch(self):
        audit, identity = self._audit, self._audit_identity
        scope, lease = self._batch_scope, self._reference_lease
        self._batch_scope = self._reference_lease = None
        self.audit_handoff_button.setEnabled(False)
        if (audit is None or identity is None or scope is None or lease is None
                or audit.stage_files == 0 or audit.invalid_files):
            self.audit_status.setText('임시 파일 형식 불일치·미선택 또는 배치 범위 미확인입니다.')
            return
        try:
            self._require_audit()
            message = handoff_author_batch_scope(
                self.authoring, project_identity=identity,
                snapshot=scope, reference_lease=lease)
            self.audit_status.setText(message + ' 임시 장면은 자동 재개하지 않습니다.')
        except (SceneIntegrityError, BatchScopeBridgeError, ValueError, OSError):
            self.invalidate_audit()
            self.audit_status.setText('원고·참고작·임시 파일 변경으로 인계를 차단했습니다.')

    def refresh(self) -> None:
        self.invalidate_audit()
        session = self.authoring.session
        if session.store is None or session.path is None or session.project_id is None:
            self.status.setText('기존 작품 DB를 먼저 열어야 합니다.')
            return
        try:
            rows = list_checkpoint_overviews(
                default_scene_checkpoint_directory(),
                database_path=session.path, project_id=str(session.project_id))
            if not rows:
                self.status.setText('현재 작품에 기록된 장면 임시 파일이 없습니다.')
                return
            self.status.setText('\n'.join(
                f'{row.episode}화: 설정별 임시 기록 {row.checkpoint_sets}묶음 / '
                f'미검증 단계 파일 {row.unverified_stage_files}개'
                for row in rows[:30]) +
                ('\n이하 생략' if len(rows) > 30 else '') +
                '\n원고 내용은 표시하지 않습니다. 모델 실행은 기존 화면에서 매번 새로 승인하세요.')
        except (SceneCheckpointError, OSError, ValueError):
            self.status.setText('임시 기록을 신뢰할 수 없습니다. 자동 재개하지 않습니다.')
