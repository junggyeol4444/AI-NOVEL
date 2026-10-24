"""기존 Windows PySide6 장편 회차 간 반복 문단·장문 겹침 검토 화면."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_cross_chapter_repetition import (
    CrossChapterRepetitionError, build_cross_chapter_repetition,
    require_current_cross_chapter_repetition,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import check_author_navigation, select_saved_episode


_TARGETS = (
    ('기존 저장 원고 편집기', '__EDITOR__'),
    ('기존 수동 재작성', 'manual_rewrite_panel'),
    ('기존 QC 기록 확인', 'review_dashboard_panel'),
    ('기존 작가 수동 검수', 'review_worklist'),
    ('기존 최종본 참고작 전수 검사', 'final_reference_audit_panel'),
    ('기존 편집 이슈 기록', 'editorial_issue_panel'),
    ('기존 장편 수정 영향 검토', 'longform_revision_impact_panel'),
)


class AuthorCrossChapterRepetitionPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('저장 장편 회차 간 동일 문단·장문 반복 후보 검토', parent)
        self.authoring = authoring
        self._identity = None
        self._snapshot = None
        root = QVBoxLayout(self)
        description = QLabel(
            '현재 SQLite 저장 최종본을 로컬에서만 대조합니다. 80자 이상 동일 문단과 '
            '120자 장문 표본 겹침은 직접 검토할 후보이며, 표본에 없는 반복은 놓칠 수 있습니다. '
            '반복 발견도 표절·문학 품질 불합격 확정이 아니며 QC PASS·출판 승인도 아닙니다.')
        description.setWordWrap(True)
        root.addWidget(description)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('마지막 회차'))
        self.through = QSpinBox()
        self.through.setObjectName('authorCrossChapterThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.valueChanged.connect(self.invalidate)
        controls.addWidget(self.through)
        preview = QPushButton('1화부터 저장 최종본 반복 후보 직접 조회')
        preview.setObjectName('authorCrossChapterPreview')
        preview.clicked.connect(self.refresh)
        controls.addWidget(preview)
        root.addLayout(controls)
        self.status = QLabel('기존 작품을 열고 작가가 직접 조회하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName('authorCrossChapterTable')
        self.table.setHorizontalHeaderLabels((
            '회차', '원고 revision', '공백 제외 글자', '동일 장문 문단',
            '120자 표본 겹침', '관련 회차', '작가 검토 상태'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        actions = QHBoxLayout()
        self.target = QComboBox()
        for title, key in _TARGETS:
            self.target.addItem(title, key)
        actions.addWidget(self.target)
        self.open_button = QPushButton('선택 회차의 기존 검토 화면 열기 (두 번째 직접 클릭)')
        self.open_button.setObjectName('authorCrossChapterOpen')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_stage)
        actions.addWidget(self.open_button)
        root.addLayout(actions)

    def invalidate(self, *_args):
        self._identity = self._snapshot = None
        self.table.setRowCount(0)
        self.open_button.setEnabled(False)
        self.status.setText('현재 원고·QC·참고작 기록을 다시 직접 조회하세요.')

    def refresh(self):
        self.invalidate()
        try:
            session, identity = _current_author_state(self.authoring)
            snapshot = build_cross_chapter_repetition(
                session.store, identity[1], through_episode=self.through.value())
        except (CrossChapterRepetitionError, BatchScopeBridgeError, ValueError, OSError):
            self.status.setText('저장 원고·검수 기록을 조회하지 못했습니다. 자동 판정하지 않습니다.')
            return
        self._identity, self._snapshot = identity, snapshot
        self.table.setRowCount(len(snapshot.rows))
        for i, row in enumerate(snapshot.rows):
            related = ', '.join(f'{ep}화' for ep in row.related_episodes[:12])
            if len(row.related_episodes) > 12:
                related += f' 외 {len(row.related_episodes) - 12}화'
            values = (str(row.episode), str(row.revision or '미저장'),
                      str(row.nonspace_chars), str(row.identical_long_paragraphs),
                      str(row.repeated_long_windows), related or '없음', row.action)
            for col, value in enumerate(values):
                self.table.setItem(i, col, QTableWidgetItem(value))
        self.open_button.setEnabled(bool(snapshot.rows))
        self.status.setText(
            f'{snapshot.through_episode}화 조회 · 최종본 없음 {snapshot.missing_final}화 · '
            f'동일 문단 검토 {snapshot.paragraph_review_chapters}화 · '
            f'장문 표본 겹침 검토 {snapshot.window_review_chapters}화. '
            '문학 품질·저작권·출판 승인과 무관한 수동 검토 후보입니다.')

    def open_stage(self):
        identity, snapshot = self._identity, self._snapshot
        index = self.table.currentRow()
        target = self.target.currentData()
        self.invalidate()  # 미리보기·승인 재사용 금지
        if (identity is None or snapshot is None
                or not 0 <= index < len(snapshot.rows)
                or target not in {key for _, key in _TARGETS}):
            self.status.setText('현재 조회한 회차와 검토 화면을 다시 선택하세요.')
            return
        row = snapshot.rows[index]
        if row.revision is None:
            self.status.setText('저장되지 않은 회차입니다. 기존 편집기에서 직접 작성하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise CrossChapterRepetitionError('작품이 변경됐습니다.')
            require_current_cross_chapter_repetition(
                snapshot, session.store, identity[1])
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
                    raise CrossChapterRepetitionError('기존 화면을 열지 못했습니다.')
        except (CrossChapterRepetitionError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.status.setText('원고·검수 기록이 변경됐거나 기존 화면을 열지 못했습니다.')
            return
        self.status.setText(
            f'{row.episode}화 기존 검토 화면을 열었습니다. '
            '원고 수정·QC·참고작 검사·출판은 별도 직접 실행입니다.')
