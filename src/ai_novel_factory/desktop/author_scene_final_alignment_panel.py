"""Windows PySide6 작가 직접 저장 장면·초고·최종본 대조 화면."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_scene_final_alignment import (
    SceneFinalAlignmentError, build_scene_final_alignment,
    require_current_scene_final_alignment,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import check_author_navigation, select_saved_episode


_TARGETS = (
    ('기존 저장 원고 편집기', '__EDITOR__'),
    ('기존 장면 설계표', 'author_scene_plan_panel'),
    ('기존 장면별 임시 초고', 'scene_checkpoint_panel'),
    ('기존 수동 재작성', 'manual_rewrite_panel'),
    ('기존 QC 검수 기록', 'review_dashboard_panel'),
    ('기존 작가 직접 검수', 'review_worklist'),
    ('기존 참고작 최종본 전수 검사', 'final_reference_audit_panel'),
    ('기존 인물·복선·시간선 검토', 'author_fact_review_panel'),
)


class AuthorSceneFinalAlignmentPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장면·초고·최종본 저장 내용 직접 대조', parent)
        self.authoring = authoring
        self._identity = None
        self._snapshot = None
        root = QVBoxLayout(self)
        notice = QLabel(
            '기존 SQLite 저장 장면이 최종본에 그대로 남았는지와 초고·최종본 문단의 '
            '변경 정도만 조회합니다. 재작성된 장면은 불일치할 수 있습니다. '
            '자동 품질 합격·검수 완료·출판 승인이 아닙니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('마지막 회차'))
        self.through = QSpinBox()
        self.through.setObjectName('authorSceneFinalThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.valueChanged.connect(self.invalidate)
        controls.addWidget(self.through)
        preview = QPushButton('저장 장면·초고·최종본 1화부터 직접 전수 대조')
        preview.setObjectName('authorSceneFinalPreview')
        preview.clicked.connect(self.refresh)
        controls.addWidget(preview)
        root.addLayout(controls)
        self.status = QLabel('현재 작품을 연 뒤 작가가 직접 조회하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.table = QTableWidget(0, 9)
        self.table.setObjectName('authorSceneFinalTable')
        self.table.setHorizontalHeaderLabels((
            '회차', '원고 revision', '저장 장면', '최종본 그대로 포함',
            '다른 표현·누락 후보', '순서 검토 후보', '초고 문단 유지율',
            '최종본 공백 제외 글자', '다음 작가 검토'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        actions = QHBoxLayout()
        self.target = QComboBox()
        for title, key in _TARGETS:
            self.target.addItem(title, key)
        actions.addWidget(self.target)
        self.open_button = QPushButton('선택 회차의 기존 화면 열기 (두 번째 직접 클릭)')
        self.open_button.setObjectName('authorSceneFinalOpen')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_stage)
        actions.addWidget(self.open_button)
        root.addLayout(actions)

    def invalidate(self, *_args):
        self._identity = self._snapshot = None
        self.table.setRowCount(0)
        self.open_button.setEnabled(False)
        self.status.setText('현재 원고·장면·검수 기록을 다시 직접 조회하세요.')

    def refresh(self):
        self.invalidate()
        try:
            session, identity = _current_author_state(self.authoring)
            snapshot = build_scene_final_alignment(
                session.store, identity[1], through_episode=self.through.value())
        except (SceneFinalAlignmentError, BatchScopeBridgeError, ValueError, OSError):
            self.status.setText('저장 원고·장면·검수 기록을 조회하지 못했습니다. 자동 합격 처리하지 않습니다.')
            return
        self._identity, self._snapshot = identity, snapshot
        self.table.setRowCount(len(snapshot.rows))
        for i, row in enumerate(snapshot.rows):
            values = (str(row.episode), str(row.revision or '미저장'),
                      str(row.saved_scene_count), str(row.exact_scene_count),
                      str(row.rewritten_or_missing_scene_count),
                      str(row.order_review_count), f'{row.draft_retained_percent}%',
                      str(row.final_nonspace_chars), row.next_action)
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
        self.open_button.setEnabled(bool(snapshot.rows))
        self.status.setText(
            f'{snapshot.through_episode}화 전수 · 최종본 미비 {snapshot.missing_final}화 · '
            f'장면 표현·순서 대조 후보 {snapshot.scenes_needing_comparison}건 · '
            f'저장 장면 없는 회차 {snapshot.chapters_without_scenes}화. '
            '이 결과는 실제 저장 기록의 편집 보조 지표이며 문학 품질·출판 승인이 아닙니다.')

    def open_stage(self):
        identity, snapshot = self._identity, self._snapshot
        row_index = self.table.currentRow()
        target = self.target.currentData()
        self.invalidate()  # 이전 미리보기 재사용·자동 인계 금지
        if (identity is None or snapshot is None
                or not 0 <= row_index < len(snapshot.rows)
                or target not in {key for _, key in _TARGETS}):
            self.status.setText('조회한 회차와 기존 검토 화면을 다시 직접 선택하세요.')
            return
        row = snapshot.rows[row_index]
        if row.revision is None:
            self.status.setText('저장되지 않은 회차입니다. 기존 편집기에서 직접 생성하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise SceneFinalAlignmentError('작품이 변경됐습니다.')
            require_current_scene_final_alignment(snapshot, session.store, identity[1])
            decision = check_author_navigation(
                self.authoring, project_identity=identity, episode=row.episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            if target == '__EDITOR__':
                moved = select_saved_episode(
                    self.authoring, project_identity=identity, episode=row.episode)
                if not moved.allowed:
                    self.status.setText(moved.message)
                    return
            else:
                hub = getattr(self.authoring, 'feature_workspace_hub', None)
                if hub is None or not hub.open_feature(
                        target, episode_number=row.episode, project_identity=identity):
                    raise SceneFinalAlignmentError('기존 검토 화면을 열지 못했습니다.')
        except (SceneFinalAlignmentError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.status.setText('원고·장면·검수 기록이 변경됐거나 화면을 열지 못했습니다.')
            return
        self.status.setText(
            f'{row.episode}화 기존 화면을 열었습니다. 원고 수정·검수·승인은 별도 직접 실행입니다.')
