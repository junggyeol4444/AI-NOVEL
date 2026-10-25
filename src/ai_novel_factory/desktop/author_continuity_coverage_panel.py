"""Windows PySide6 장편 아크·장면·사실·말투·기억 다섯 기록의 직접 대조 화면."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog, QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..author_continuity_coverage import (
    ContinuityCoverageError, build_continuity_coverage,
    read_continuity_episode_evidence, require_current_continuity_coverage,
)
from ..author_continuity_context_handoff import (
    ContinuityContextHandoffError, preview_continuity_context,
    require_current_continuity_context,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import check_author_navigation


_FOLDERS = ('아크', '장면 설계', '인물·복선·시간선', '표기·말투', '장편 기억')
_TARGETS = (
    ('아크 직접 기록', 'author_arc_panel'),
    ('장면 계획 직접 기록', 'author_scene_plan_panel'),
    ('인물·복선·시간선 직접 기록', 'author_fact_panel'),
    ('고유명사·말투 직접 기록', 'author_language_panel'),
    ('기억 변화 직접 기록', 'author_memory_panel'),
    ('다섯 기록 통합 집필 문맥 미리보기', 'author_context_composer_panel'),
    ('기존 원고 QC 기록', 'review_dashboard_panel'),
    ('최종본 참고작 전수 검사', 'final_reference_audit_panel'),
    ('작가 수동 검수', 'review_worklist'),
)


class AuthorContinuityCoveragePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 5종 작가 기록 · 저장 원고 연속성 범위', parent)
        self.authoring = authoring
        self._identity = None
        self._snapshot = None
        self._context_lease = None
        self._context_identity = None
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            '작가가 선택한 기존 기록만 읽습니다. 빈 기록·과거 근거는 자동 보완하지 않으며 '
            '연속성 합격, QC PASS, 저작권·출판 승인이 아닙니다.'))
        self.paths = []
        for index, title in enumerate(_FOLDERS):
            row = QHBoxLayout()
            entry = QLineEdit()
            entry.setReadOnly(True)
            entry.setObjectName(f'authorContinuityFolder{index}')
            self.paths.append(entry)
            choose = QPushButton(f'{title} 기록 폴더 직접 선택')
            choose.clicked.connect(lambda _checked=False, i=index: self.choose_folder(i))
            row.addWidget(entry)
            row.addWidget(choose)
            root.addLayout(row)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('조회할 마지막 회차'))
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.setObjectName('authorContinuityThrough')
        self.through.valueChanged.connect(self.invalidate)
        controls.addWidget(self.through)
        refresh = QPushButton('5종 기록·저장 원고 직접 대조')
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        root.addLayout(controls)
        self.status = QLabel('현재 작품과 기존 로컬 기록 폴더 5개를 직접 선택하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.table = QTableWidget(0, 9)
        self.table.setObjectName('authorContinuityCoverageTable')
        self.table.setHorizontalHeaderLabels((
            '회차', '최종본 글자', '아크', '장면', '사실', '말투', '기억', '근거 변경', '미등록 기록'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        self.table.currentCellChanged.connect(self.invalidate_detail)
        self.detail_button = QPushButton('선택 회차의 다섯 기록 전체 근거 열람 (별도 클릭)')
        self.detail_button.setObjectName('authorContinuityEpisodeEvidence')
        self.detail_button.clicked.connect(self.show_episode_evidence)
        root.addWidget(self.detail_button)
        self.detail_table = QTableWidget(0, 4)
        self.detail_table.setObjectName('authorContinuityEpisodeEvidenceTable')
        self.detail_table.setHorizontalHeaderLabels(('기록 종류', '작가 기록', '근거 회차', '근거 상태'))
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_table.currentCellChanged.connect(self.show_evidence_record)
        root.addWidget(self.detail_table)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setObjectName('authorContinuityEpisodeEvidenceText')
        self.detail_text.setReadOnly(True)
        root.addWidget(self.detail_text)
        self._detail = None
        actions = QHBoxLayout()
        self.stage = QComboBox()
        for label, target in _TARGETS:
            self.stage.addItem(label, target)
        actions.addWidget(self.stage)
        self.open_button = QPushButton('선택한 회차의 기존 화면 열기 (별도 클릭)')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_stage)
        actions.addWidget(self.open_button)
        root.addLayout(actions)
        context_actions = QHBoxLayout()
        context_actions.addWidget(QLabel('문맥 장면 수'))
        self.context_scenes = QSpinBox()
        self.context_scenes.setRange(1, 20)
        self.context_scenes.setValue(3)
        self.context_scenes.setObjectName('authorContinuityContextScenes')
        self.context_scenes.valueChanged.connect(self.invalidate_context)
        context_actions.addWidget(self.context_scenes)
        self.context_preview_button = QPushButton('선택 회차의 5종 실제 집필 문맥 확인')
        self.context_preview_button.setObjectName('authorContinuityContextPreview')
        self.context_preview_button.clicked.connect(self.preview_context)
        context_actions.addWidget(self.context_preview_button)
        self.context_handoff_button = QPushButton('확인한 5종 문맥을 기존 집필 화면에 선택만 인계')
        self.context_handoff_button.setObjectName('authorContinuityContextHandoff')
        self.context_handoff_button.setEnabled(False)
        self.context_handoff_button.clicked.connect(self.handoff_context)
        context_actions.addWidget(self.context_handoff_button)
        root.addLayout(context_actions)

    def invalidate_context(self, *_args):
        self._context_lease = None
        self._context_identity = None
        self.context_handoff_button.setEnabled(False)

    def invalidate(self, *_args):
        self.invalidate_context()
        self.invalidate_detail()
        self._identity = self._snapshot = None
        self.table.setRowCount(0)
        self.open_button.setEnabled(False)
        self.status.setText('현재 작품·저장 원고·다섯 기록을 다시 직접 조회하세요.')

    def choose_folder(self, index):
        folder = QFileDialog.getExistingDirectory(self, f'{_FOLDERS[index]} 기존 기록 폴더 선택')
        if folder:
            self.invalidate()
            self.paths[index].setText(folder)

    def refresh(self):
        self.invalidate()
        try:
            session, identity = _current_author_state(self.authoring)
            snapshot = build_continuity_coverage(
                session.store, identity[1], through_episode=self.through.value(),
                folders=tuple(p.text() for p in self.paths))
        except (ContinuityCoverageError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('기존 작품·원고·다섯 기록을 읽지 못했습니다. 다시 선택하세요.')
            return
        self._identity, self._snapshot = identity, snapshot
        self.table.setRowCount(len(snapshot.rows))
        for index, row in enumerate(snapshot.rows):
            values = (str(row.episode), str(row.final_chars), str(row.arcs),
                      str(row.scene_plans), str(row.facts), str(row.language_rules),
                      str(row.memory_deltas), str(row.stale_sources),
                      ', '.join(row.missing_sources) or '없음')
            for col, value in enumerate(values):
                self.table.setItem(index, col, QTableWidgetItem(value))
        self.open_button.setEnabled(bool(snapshot.rows))
        self.status.setText(
            f'{snapshot.through_episode}화 중 최종본 미비 {snapshot.missing_final}화, '
            f'작가 기록의 과거 근거·설정 지문 변경 {snapshot.stale_source_count}건. '
            '기록이 존재해도 내용의 정확성·품질·출판 가능성은 확인되지 않았습니다.')

    def open_stage(self):
        identity, snapshot = self._identity, self._snapshot
        index, target = self.table.currentRow(), self.stage.currentData()
        self.invalidate()  # 이전 미리보기 재사용 불가
        if (identity is None or snapshot is None or
                not 0 <= index < len(snapshot.rows) or
                target not in {name for _, name in _TARGETS}):
            self.status.setText('먼저 현재 범위를 조회하고 회차를 선택하세요.')
            return
        row = snapshot.rows[index]
        if row.revision is None:
            self.status.setText('저장되지 않은 회차입니다. 기존 편집기에서 직접 작성하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise ContinuityCoverageError('작품이 변경됐습니다.')
            require_current_continuity_coverage(snapshot, session.store, identity[1])
            decision = check_author_navigation(
                self.authoring, project_identity=identity, episode=row.episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    target, episode_number=row.episode, project_identity=identity):
                raise ContinuityCoverageError('기존 기능 화면을 열지 못했습니다.')
        except (ContinuityCoverageError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('원고·기록·작품이 변경됐거나 화면을 열지 못했습니다. 다시 조회하세요.')
            return
        self.status.setText(f'{row.episode}화 기존 화면을 열었습니다. 검수·저장·승인은 별도 클릭입니다.')
    def preview_context(self):
        """작가 첫 클릭: 저장 원고·5종 기록·장면별 문맥을 실제 조합해 확인."""
        self.invalidate_context()
        identity, snapshot = self._identity, self._snapshot
        row_index = self.table.currentRow()
        if identity is None or snapshot is None or not 0 <= row_index < len(snapshot.rows):
            self.status.setText('현재 작품의 기록을 조회하고 저장 회차를 선택하세요.')
            return
        episode = snapshot.rows[row_index].episode
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise ContinuityContextHandoffError('작품이 변경됐습니다.')
            decision = check_author_navigation(
                self.authoring, project_identity=identity, episode=episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            lease = preview_continuity_context(
                session.store, identity[1], coverage=snapshot,
                episode=episode, scene_count=self.context_scenes.value())
        except (ContinuityContextHandoffError, BatchScopeBridgeError,
                OSError, ValueError, LookupError):
            self.status.setText(
                '저장 최종본·작가 기록·근거·문맥 길이가 유효하지 않습니다. '
                '원본을 직접 정리하고 다시 조회하세요.')
            return
        self._context_lease, self._context_identity = lease, identity
        self.context_handoff_button.setEnabled(True)
        self.status.setText(
            f'{episode}화 {lease.scene_count}장면의 기존 5종 문맥 조합 확인: '
            f'공통 {lease.outline_chars}자, 장면별 추가 {lease.scene_chars}자. '
            '원고 내용은 전송하지 않았고 AI 실행·문맥 사용 승인도 하지 않았습니다.')

    def handoff_context(self):
        """작가 두 번째 클릭: 같은 기록 지문만 기존 통합 문맥 GUI에 전달."""
        lease, identity = self._context_lease, self._context_identity
        self.invalidate_context()
        if lease is None or identity is None:
            self.status.setText('먼저 저장 회차의 문맥을 직접 확인하세요.')
            return
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise ContinuityContextHandoffError('작품이 변경됐습니다.')
            require_current_continuity_context(lease, session.store, identity[1])
            decision = check_author_navigation(
                self.authoring, project_identity=identity, episode=lease.episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    'author_context_composer_panel',
                    episode_number=lease.episode, project_identity=identity):
                raise ContinuityContextHandoffError('기존 통합 문맥 화면을 열지 못했습니다.')
            composer = getattr(self.authoring, 'author_context_composer_panel', None)
            if composer is None:
                raise ContinuityContextHandoffError('기존 문맥 화면을 찾지 못했습니다.')
            composer.accept_existing_continuity_sources(lease)
        except (ContinuityContextHandoffError, BatchScopeBridgeError,
                OSError, ValueError, LookupError):
            self.status.setText(
                '기록·작품·원고가 변경됐거나 인계하지 못했습니다. 다시 직접 확인하세요.')
            return
        self.status.setText(
            f'{lease.episode}화 5종 기록 폴더만 기존 문맥 화면에 선택했습니다. '
            '문맥 미리보기·1회 모델 문맥 동의·배치 실행은 모두 별도 직접 클릭입니다.')

    def invalidate_detail(self, *_args):
        self._detail = None
        self.detail_table.setRowCount(0)
        self.detail_text.clear()

    def show_episode_evidence(self):
        """별도 클릭: 저장 최종본과 다섯 기록 전체 근거를 표시."""
        self.invalidate_detail()
        identity, snapshot = self._identity, self._snapshot
        index = self.table.currentRow()
        if identity is None or snapshot is None or not 0 <= index < len(snapshot.rows):
            self.status.setText('다섯 기록을 조회한 뒤 저장 회차를 선택하세요.')
            return
        episode = snapshot.rows[index].episode
        try:
            session, current = _current_author_state(self.authoring)
            if current != identity:
                raise ContinuityCoverageError('작품이 변경됐습니다.')
            decision = check_author_navigation(
                self.authoring, project_identity=identity, episode=episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            evidence = read_continuity_episode_evidence(
                session.store, identity[1], coverage=snapshot, episode=episode)
        except (ContinuityCoverageError, BatchScopeBridgeError,
                OSError, ValueError, LookupError):
            self.status.setText('원고·작품·기록이 변경됐거나 저장 최종본이 없습니다. 다시 조회하세요.')
            return
        self._detail = evidence
        self.detail_table.setRowCount(len(evidence.rows))
        for i, item in enumerate(evidence.rows):
            values = (item.category, item.label,
                      str(item.source_episode) if item.source_episode is not None else '작품 설정',
                      '현재 일치' if item.source_current else '과거 근거 변경')
            for col, value in enumerate(values):
                self.detail_table.setItem(i, col, QTableWidgetItem(value))
        self.detail_text.setPlainText(evidence.final_text)
        self.status.setText(
            f'{episode}화 저장 최종본 {len(evidence.final_text)}자, '
            f'작가 기록 {len(evidence.rows)}건, 과거 근거 불일치 {evidence.changed_sources}건. '
            '자동 품질 판정·QC PASS·출판 승인이 아닙니다.')

    def show_evidence_record(self, row, _column, *_args):
        detail = self._detail
        if detail is None or not 0 <= row < len(detail.rows):
            return
        item = detail.rows[row]
        self.detail_text.setPlainText(
            f'[작가 기록: {item.category} / {item.label}]\n'
            f'[근거: {"현재 일치" if item.source_current else "과거 근거 변경"}]\n\n'
            + item.author_text + '\n\n'
            + f'[저장 최종본 전체: {detail.episode}화 / revision {detail.revision}]\n'
            + detail.final_text)
