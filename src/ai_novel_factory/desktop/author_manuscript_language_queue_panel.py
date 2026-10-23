"""Windows PySide6 저장 최종본 한국어·5000자·반복 표현 직접 검토 화면."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_manuscript_language_queue import (
    ManuscriptLanguageQueueError, build_manuscript_language_queue,
    require_current_manuscript_language_queue,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import check_author_navigation


_TARGETS = (
    ('기존 원고 수동 재작성', 'manual_rewrite_panel'),
    ('기존 QC 기록 확인', 'review_dashboard_panel'),
    ('작가 수동 검수', 'review_worklist'),
    ('최종본 참고작 전수 검사', 'final_reference_audit_panel'),
    ('고유명사·말투 검토', 'author_language_review_panel'),
    ('출판 별도 승인 화면', 'publication_approval_panel'),
)


class AuthorManuscriptLanguageQueuePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('저장 최종본 한국어·5000자·반복 표현 검토 대기열', parent)
        self.authoring = authoring
        self._identity = None
        self._snapshot = None
        root = QVBoxLayout(self)
        notice = QLabel(
            '저장된 최종본의 실제 글자 수·문자 종류·반복 후보만 읽기 전용 조회합니다. '
            '자연스러운 한국어 품질, QC 합격, 참고작 검사, 출판 승인을 자동 판정하지 않습니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('마지막 회차'))
        self.through = QSpinBox()
        self.through.setObjectName('authorManuscriptLanguageThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.valueChanged.connect(self.invalidate)
        controls.addWidget(self.through)
        preview = QPushButton('저장 최종본 1화부터 직접 전수 조회')
        preview.setObjectName('authorManuscriptLanguagePreview')
        preview.clicked.connect(self.refresh)
        controls.addWidget(preview)
        root.addLayout(controls)
        self.status = QLabel('기존 작품을 열고 직접 조회하세요. 자동 수정하지 않습니다.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName('authorManuscriptLanguageTable')
        self.table.setHorizontalHeaderLabels((
            '회차', '원고 revision', '공백 제외 글자', '한글 음절',
            '비한국 문자/깨짐', '12자 반복 후보', '다음 작가 검토'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        actions = QHBoxLayout()
        self.target = QComboBox()
        for title, key in _TARGETS:
            self.target.addItem(title, key)
        actions.addWidget(self.target)
        self.open_button = QPushButton('선택 회차의 기존 검토 화면 열기 (별도 클릭)')
        self.open_button.setObjectName('authorManuscriptLanguageOpen')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_stage)
        actions.addWidget(self.open_button)
        root.addLayout(actions)

    def invalidate(self, *_args):
        self._identity = self._snapshot = None
        self.table.setRowCount(0)
        self.open_button.setEnabled(False)
        self.status.setText('현재 저장 원고·검수 기록을 다시 직접 조회하세요.')

    def refresh(self):
        self.invalidate()
        try:
            session, identity = _current_author_state(self.authoring)
            snapshot = build_manuscript_language_queue(
                session.store, identity[1], through_episode=self.through.value())
        except (ManuscriptLanguageQueueError, BatchScopeBridgeError,
                ValueError, OSError):
            self.status.setText('원고·QC·참고작 기록 조회에 실패했습니다. 자동 합격 처리하지 않습니다.')
            return
        self._identity, self._snapshot = identity, snapshot
        self.table.setRowCount(len(snapshot.rows))
        for i, row in enumerate(snapshot.rows):
            values = (str(row.episode), str(row.revision or '미저장'),
                      str(row.nonspace_chars), str(row.hangul_syllables),
                      f'{row.non_korean_script_chars}/{row.replacement_chars}',
                      str(row.repeated_12grams), row.action)
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
        self.open_button.setEnabled(bool(snapshot.rows))
        self.status.setText(
            f'{snapshot.through_episode}화 전수 · 최종본 누락 {snapshot.missing_final}화 · '
            f'5000자 미달 {snapshot.below_target}화 · '
            f'한자/가나/키릴/깨진 문자 검토 {snapshot.script_review}화 · '
            f'반복 표현 후보 {snapshot.repetition_review}화. '
            '표시가 없어도 문학 품질 합격이 아닙니다.')

    def open_stage(self):
        identity, snapshot = self._identity, self._snapshot
        row_index = self.table.currentRow()
        target = self.target.currentData()
        self.invalidate()  # 이전 미리보기 재사용 및 승인 재사용 금지
        if (identity is None or snapshot is None
                or not 0 <= row_index < len(snapshot.rows)
                or target not in {key for _, key in _TARGETS}):
            self.status.setText('현재 조회한 회차와 검토 화면을 다시 선택하세요.')
            return
        row = snapshot.rows[row_index]
        if row.revision is None:
            self.status.setText('저장되지 않은 회차입니다. 기존 편집기에서 직접 작성하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise ManuscriptLanguageQueueError('작품이 변경됐습니다.')
            require_current_manuscript_language_queue(
                snapshot, session.store, identity[1])
            decision = check_author_navigation(
                self.authoring, project_identity=identity, episode=row.episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    target, episode_number=row.episode, project_identity=identity):
                raise ManuscriptLanguageQueueError('기존 화면을 열지 못했습니다.')
        except (ManuscriptLanguageQueueError, BatchScopeBridgeError,
                ValueError, OSError, LookupError):
            self.status.setText('원고·검수 기록이 변경됐거나 기존 화면을 열지 못했습니다.')
            return
        self.status.setText(
            f'{row.episode}화 기존 검토 화면을 열었습니다. 수정·검수·출판은 별도 직접 승인입니다.')