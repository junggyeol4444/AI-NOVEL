"""Native PySide6 author work queue; no model, QC or publish actions."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..author_workflow_dependencies import (
    AuthorWorkflowDependenciesError, build_author_workflow_dependencies,
    require_current_workflow_chapter,
)
from .author_navigation_contract import select_saved_episode
from .author_batch_scope_bridge import (
    BatchScopeBridgeError, preview_author_batch_scope, handoff_author_batch_scope,
)
from .author_export_handoff_bridge import (
    ExportHandoffBridgeError, preview_author_export_scope, open_author_export_stage,
)


_ACTION_TARGETS = {
    'COMPLETE_OR_REFRESH_QC': 'review_dashboard_panel',
    'REVIEW_REFERENCES': 'final_reference_audit_panel',
    'CONFIRM_HUMAN_REVIEW': 'review_worklist',
    'SEPARATE_PUBLICATION_APPROVAL': 'publication_approval_panel',
}

_QUICK_TOOLS = (
    ('기존 SQLite 재열기', 'sqlite_reopen_panel'),
    ('SQLite 안전 백업', 'project_backup_panel'),
    ('SQLite 별도 복원 사본', 'project_restore_panel'),
    ('편집 이슈·인계 보류', 'editorial_handoff_panel'),
    ('비공개 EPUB3 다권 생성', 'epub_volume_panel'),
    ('비공개 EPUB3 원고 대조', 'epub_source_alignment_panel'),
    ('비공개 EPUB3 여러 권 Reader', 'private_volume_reader_panel'),
    ('EPUB3 검색·책갈피', 'epub_private_bookmarks_panel'),
    ('작가 장편 아크 문맥', 'author_arc_context_panel'),
    ('회차별 장면 설계 문맥', 'author_scene_context_panel'),
    ('인물·복선·시간선 검토표', 'author_fact_review_panel'),
    ('고유명사·말투 검토', 'author_language_review_panel'),
    ('아크·장면·사실·언어 통합 문맥', 'author_context_composer_panel'),
    ('회차별 집필 중단·재개', 'scene_checkpoint_panel'),
    ('참고작 5종 직접 선택·등록', 'reference_intake_panel'),
    ('참고작 회차별 검사 범위', 'reference_coverage_panel'),
    ('최종 원고 참고작 전수 비교', 'final_reference_audit_panel'),
    ('30·100·250화 저장 기록 현황', 'author_workflow_milestones_panel'),
    ('장편 권별 원고·검수·EPUB3 현황', 'author_volume_review_matrix_panel'),
    ('장편 편집 이슈·QC·검수 연결 현황', 'author_editorial_readiness_panel'),
)

_ACTION_LABELS = {
    'CREATE_EPISODE': '회차 직접 생성',
    'PREPARE_DRAFT': 'AI 초고 또는 직접 초고 준비',
    'WRITE_OR_REVIEW_FINAL': '작가 최종 원고 직접 검수·저장',
    'COMPLETE_OR_REFRESH_QC': '현재 원고 QC 기록 확인',
    'REVIEW_REFERENCES': '참고작 선택 범위 검사 확인',
    'CONFIRM_HUMAN_REVIEW': '현재 원고 직접 검수',
    'SEPARATE_PUBLICATION_APPROVAL': '출판은 별도 승인 필요',
}


class AuthorWorkflowDependenciesPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 집필 · 회차별 실제 남은 작업', parent)
        self.authoring = authoring
        self._bound_project = None
        self._report = None
        body = QVBoxLayout(self)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('확인할 마지막 회차'))
        self.through = QSpinBox()
        self.through.setObjectName('authorWorkflowThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        tools.addWidget(self.through)
        self.filter = QComboBox()
        self.filter.addItems(('전체', '출판 별도 승인 제외 미완료', '최종본 없음', '참고작 검사 필요', '수동 검수 필요'))
        tools.addWidget(self.filter)
        reload_button = QPushButton('기존 저장 기록에서 새로 읽기')
        reload_button.clicked.connect(self.refresh)
        tools.addWidget(reload_button)
        body.addLayout(tools)
        self.status = QLabel('프로젝트를 연 뒤 직접 조회하세요. 검수 합격·출판 승인 화면이 아닙니다.')
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(('회차', '원고 revision', '직접 검수 기록', '참고작 범위', '다음 작가 작업'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setObjectName('authorWorkflowDependencyTable')
        body.addWidget(self.table)
        self.open_button = QPushButton('선택한 저장 회차를 기존 편집기로 열기')
        self.open_button.clicked.connect(self.open_selected)
        body.addWidget(self.open_button)
        navigation = QHBoxLayout()
        self.action_selector = QComboBox()
        self.action_selector.setObjectName('authorWorkflowActionSelector')
        self.action_button = QPushButton('선택한 회차의 작가 작업 화면 열기')
        self.action_button.setObjectName('authorWorkflowActionOpen')
        self.action_button.setEnabled(False)
        self.action_button.clicked.connect(self.open_action)
        navigation.addWidget(self.action_selector)
        navigation.addWidget(self.action_button)
        body.addLayout(navigation)
        utilities = QHBoxLayout()
        self.utility_selector = QComboBox()
        self.utility_selector.setObjectName('authorWorkflowUtilitySelector')
        for title, target in _QUICK_TOOLS:
            self.utility_selector.addItem(title, target)
        self.utility_button = QPushButton('선택한 기존 SQLite·EPUB 도구 열기')
        self.utility_button.setObjectName('authorWorkflowUtilityOpen')
        self.utility_button.clicked.connect(self.open_utility)
        utilities.addWidget(self.utility_selector)
        utilities.addWidget(self.utility_button)
        body.addLayout(utilities)
        # 이미 존재하는 자동 집필 배치의 설정 화면으로 범위만 인계한다.
        # 사용자가 직접 누르기 전에는 SQLite/참고작/모델을 읽지 않는다.
        scope_controls = QHBoxLayout()
        self.scope_preview_button = QPushButton('현재 30·100·250화 범위·참고작 상태 확인')
        self.scope_preview_button.setObjectName('authorWorkflowScopePreview')
        self.scope_preview_button.clicked.connect(self.preview_batch_scope)
        self.scope_handoff_button = QPushButton('확인한 범위를 기존 AI 배치 설정에 입력')
        self.scope_handoff_button.setObjectName('authorWorkflowScopeHandoff')
        self.scope_handoff_button.setEnabled(False)
        self.scope_handoff_button.clicked.connect(self.handoff_batch_scope)
        scope_controls.addWidget(self.scope_preview_button)
        scope_controls.addWidget(self.scope_handoff_button)
        body.addLayout(scope_controls)
        self._batch_scope_identity = None
        self._batch_scope_snapshot = None
        self._batch_reference_lease = None
        export_row = QHBoxLayout()
        self.export_preview_button = QPushButton('현재 저장 최종본·검수·EPUB3 다권 계획 확인')
        self.export_preview_button.setObjectName('authorExportScopePreview')
        self.export_preview_button.clicked.connect(self.preview_export_scope)
        self.export_stage = QComboBox()
        self.export_stage.setObjectName('authorExportStageSelector')
        for label, target in (
            ('최종본 참고작 전수 검사', 'final_reference_audit_panel'),
            ('작가 수동 검수', 'review_worklist'),
            ('비공개 EPUB3 다권 계획·생성', 'epub_volume_panel'),
            ('EPUB3 저장 원고 대조', 'epub_source_alignment_panel'),
            ('EPUB3 다권 Reader', 'private_volume_reader_panel'),
            ('EPUB3 검색·책갈피', 'epub_private_bookmarks_panel'),
            ('SQLite 별도 백업', 'project_backup_panel'),
            ('장면 중단·재개 현황', 'scene_checkpoint_panel'),
            ('출판 별도 승인 화면', 'publication_approval_panel'),
        ):
            self.export_stage.addItem(label, target)
        self.export_open_button = QPushButton('확인한 범위의 기존 화면 열기')
        self.export_open_button.setObjectName('authorExportScopeOpen')
        self.export_open_button.setEnabled(False)
        self.export_open_button.clicked.connect(self.open_export_stage)
        export_row.addWidget(self.export_preview_button)
        export_row.addWidget(self.export_stage)
        export_row.addWidget(self.export_open_button)
        body.addLayout(export_row)
        self._export_scope_identity = None
        self._export_scope_snapshot = None
        self.table.itemSelectionChanged.connect(self._populate_actions)
        self.through.valueChanged.connect(self.invalidate)
        self.filter.currentIndexChanged.connect(self._render)

    def invalidate(self, *_args):
        self._report = None
        self._bound_project = None
        self._batch_scope_identity = None
        self._batch_scope_snapshot = None
        self._batch_reference_lease = None
        self._export_scope_identity = None
        self._export_scope_snapshot = None
        self.export_open_button.setEnabled(False)
        self.scope_handoff_button.setEnabled(False)
        self.table.setRowCount(0)
        self.action_selector.clear()
        self.action_button.setEnabled(False)
        self.status.setText('작품이나 범위 변경 후 현재 저장 기록을 다시 읽으세요.')

    def refresh(self):
        self.invalidate()
        session = self.authoring.session
        if session.store is None or session.project_id is None or session.path is None:
            self.status.setText('기존 작품을 먼저 생성하거나 열어 주세요.')
            return
        try:
            report = build_author_workflow_dependencies(
                session.store, str(session.project_id),
                through_episode=self.through.value())
        except (ValueError, OSError):
            self.status.setText('현재 작품 작업 기록을 읽지 못했습니다. 합격 처리하지 않습니다.')
            return
        self._bound_project = (str(session.path), str(session.project_id))
        self._report = report
        self._render()

    def _render(self, *_args):
        report = self._report
        self.table.setRowCount(0)
        if report is None:
            return
        category = self.filter.currentIndex()
        rows = []
        for item in report.chapters:
            if category == 1 and not any(a != 'SEPARATE_PUBLICATION_APPROVAL' for a in item.remaining_actions):
                continue
            if category == 2 and item.final_present:
                continue
            if category == 3 and item.reference_status == 'CHECKED_SCOPE_ONLY':
                continue
            if category == 4 and item.review_status == 'REVIEWED_QC_RECORDED_NOT_PUBLISHED':
                continue
            rows.append(item)
        self.table.setRowCount(len(rows))
        for i, item in enumerate(rows):
            values = (str(item.episode), str(item.revision or '미작성'),
                      item.review_status, item.reference_status,
                      _ACTION_LABELS.get(item.next_action, '작가 직접 확인'))
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 0:
                    cell.setData(256, item.episode)
                self.table.setItem(i, col, cell)
        self.status.setText(
            f'조회 {report.through_episode}화 / 미작성 {report.missing_episodes}화 / '
            f'최종본 미비 {report.missing_final_manuscripts}화 / '
            f'검수 확인 필요 {report.review_action_count}화 / '
            f'참고작 범위 확인 필요 {report.reference_action_count}화. '
            '모든 결과는 기존 저장 기록 표시이며 AI·QC 합격 및 출판 승인이 아닙니다.')
        self._populate_actions()

    def _selected_chapter(self):
        if self._report is None or self.table.currentRow() < 0:
            return None
        cell = self.table.item(self.table.currentRow(), 0)
        if cell is None:
            return None
        try:
            number = int(cell.text())
        except (TypeError, ValueError):
            return None
        return next((row for row in self._report.chapters
                     if row.episode == number), None)

    def _populate_actions(self):
        selected = self._selected_chapter()
        self.action_selector.clear()
        if selected is not None:
            for action in selected.remaining_actions:
                self.action_selector.addItem(
                    _ACTION_LABELS.get(action, '작가 직접 확인'), action)
        self.action_button.setEnabled(self.action_selector.count() > 0)

    def open_action(self):
        """회차 지문 재확인 후 기존 화면으로 이동. 모델·검수·출판 자동 실행 없음."""
        session = self.authoring.session
        cached = self._selected_chapter()
        action = self.action_selector.currentData()
        identity = (str(session.path), str(session.project_id))
        if (cached is None or action not in cached.remaining_actions
                or identity != self._bound_project or session.store is None):
            self.invalidate()
            return
        if cached.revision is None:
            self.status.setText(
                f'{cached.episode}화는 아직 저장되지 않았습니다. '
                '기존 집필 화면에서 회차를 직접 생성하세요. 자동 생성하지 않습니다.')
            return
        if self.authoring.is_generating() or self.authoring.auto_panel.is_running():
            self.status.setText('진행 중인 집필이 끝난 뒤 회차 작업 화면을 여세요.')
            return
        try:
            require_current_workflow_chapter(
                session.store, str(session.project_id), cached)
            latest = build_author_workflow_dependencies(
                session.store, str(session.project_id),
                through_episode=cached.episode).chapters[-1]
            if (latest.revision != cached.revision
                    or latest.manuscript_sha256 != cached.manuscript_sha256
                    or latest.remaining_actions != cached.remaining_actions
                    or action not in latest.remaining_actions):
                raise AuthorWorkflowDependenciesError('기존 작업 기록이 변경됐습니다.')
            decision = select_saved_episode(
                self.authoring, project_identity=self._bound_project,
                episode=cached.episode, snapshot=cached)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
        except (AuthorWorkflowDependenciesError, OSError, ValueError):
            self.invalidate()
            self.status.setText('현재 원고·검수 기록이 변경됐습니다. 다시 조회 후 선택하세요.')
            return
        if action in ('PREPARE_DRAFT', 'WRITE_OR_REVIEW_FINAL'):
            self.status.setText(
                f'{cached.episode}화 기존 집필 편집기를 선택했습니다. '
                '초고 작성·모델 실행·최종본 저장은 작가가 직접 실행해야 합니다.')
            return
        target = _ACTION_TARGETS.get(action)
        hub = getattr(self.authoring, 'feature_workspace_hub', None)
        if target is None or hub is None or not hub.open_feature(
                target, episode_number=cached.episode,
                project_identity=self._bound_project):
            self.status.setText('해당 기능 화면을 열지 못했습니다. 기능 목록에서 직접 선택하세요.')
            return
        self.status.setText(
            f'{cached.episode}화 관련 화면을 열었습니다. '
            '검수 실행·승인·출판은 자동 수행되지 않습니다.')

    def open_utility(self):
        """작가가 클릭한 기존 SQLite/EPUB 도구의 화면만 표시한다."""
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('기존 작품을 먼저 열어 주세요.')
            return
        if self.authoring.is_generating() or self.authoring.auto_panel.is_running():
            self.status.setText('집필 작업이 끝난 후 별도 도구를 여세요.')
            return
        hub = getattr(self.authoring, 'feature_workspace_hub', None)
        target = self.utility_selector.currentData()
        if hub is None or target not in {key for _, key in _QUICK_TOOLS}:
            self.status.setText('등록된 기존 도구를 다시 선택하세요.')
            return
        selected = self._selected_chapter()
        identity = (str(session.path), str(session.project_id))
        if self._bound_project is not None and identity != self._bound_project:
            self.invalidate()
            return
        if not hub.open_feature(
                target, episode_number=selected.episode if selected else None,
                project_identity=identity):
            self.status.setText('도구를 열지 못했습니다. 기능 목록에서 직접 확인하세요.')
            return
        self.status.setText('기존 도구 화면을 열었습니다. 백업·생성·승인은 직접 클릭해야 합니다.')

    def preview_batch_scope(self):
        """작가가 직접 클릭한 현재 저장 범위/참고작 확장자 개수만 표시."""
        self._batch_scope_identity = None
        self._batch_scope_snapshot = None
        self._batch_reference_lease = None
        self.scope_handoff_button.setEnabled(False)
        try:
            identity, scope, reference_lease = preview_author_batch_scope(
                self.authoring, through_episode=self.through.value())
        except (BatchScopeBridgeError, ValueError, OSError):
            self.status.setText('집필 범위·원고 상태를 확인하지 못했습니다. 직접 다시 조회하세요.')
            return
        self._batch_scope_identity = identity
        self._batch_scope_snapshot = scope
        self._batch_reference_lease = reference_lease
        self.scope_handoff_button.setEnabled(True)
        formats = ', '.join(f'{ext[1:].upper()} {count}개'
                            for ext, count in scope.reference_type_counts)
        self.status.setText(
            f'{scope.through_episode}화 범위: 저장 {scope.stored_episodes}화, '
            f'미작성 {scope.missing_episodes}화, 최종본 미비 '
            f'{scope.missing_final_manuscripts}화, 직접 검수 필요 '
            f'{scope.human_review_needed}화, 참고작 범위 확인 필요 '
            f'{scope.reference_review_needed}화. 참고작 형식: {formats}. '
            '실제 참고작 본문 검사·한국어 품질·출판 승인은 여기서 수행하지 않습니다.')

    def handoff_batch_scope(self):
        """작가의 두 번째 클릭에서만 기존 AI 배치 QSpinBox에 범위를 전달."""
        scope = self._batch_scope_snapshot
        identity = self._batch_scope_identity
        reference_lease = self._batch_reference_lease
        self._batch_scope_snapshot = None
        self._batch_scope_identity = None
        self._batch_reference_lease = None
        self.scope_handoff_button.setEnabled(False)
        if scope is None or identity is None or reference_lease is None:
            self.status.setText('먼저 범위를 직접 미리보기 하세요.')
            return
        try:
            message = handoff_author_batch_scope(
                self.authoring, project_identity=identity, snapshot=scope,
                reference_lease=reference_lease)
        except (BatchScopeBridgeError, ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.status.setText(message)

    def open_selected(self):
        cached = self._selected_chapter()
        if cached is None or self._bound_project is None:
            self.invalidate()
            return
        if cached.revision is None:
            self.status.setText('아직 저장되지 않은 회차입니다. 자동 생성하지 않습니다.')
            return
        decision = select_saved_episode(
            self.authoring, project_identity=self._bound_project,
            episode=cached.episode, snapshot=cached)
        if not decision.allowed:
            self.status.setText(decision.message)
            return
        self.status.setText(decision.message)

    def preview_export_scope(self):
        """명시적 클릭으로 저장 최종본·검수·EPUB 분할 범위만 읽는다."""
        self._export_scope_identity = None
        self._export_scope_snapshot = None
        self.export_open_button.setEnabled(False)
        try:
            identity, snapshot = preview_author_export_scope(
                self.authoring, through_episode=self.through.value())
        except (ExportHandoffBridgeError, ValueError, OSError):
            self.status.setText('저장 최종본·검수·EPUB3 범위를 조회하지 못했습니다.')
            return
        self._export_scope_identity = identity
        self._export_scope_snapshot = snapshot
        self.export_open_button.setEnabled(True)
        volumes = ', '.join(
            f'{index}권 {start}~{end}화'
            for index, start, end in snapshot.volume_ranges[:8])
        self.status.setText(
            f'{snapshot.through_episode}화 범위: 저장 {snapshot.stored_episodes}화, '
            f'최종본 누락 {snapshot.missing_final}화, 권당 용량 초과 '
            f'{snapshot.oversized_final}화, 직접 검수 확인 필요 '
            f'{snapshot.review_action_count}화, 참고작 검사 범위 확인 필요 '
            f'{snapshot.reference_action_count}화. EPUB3 분할: {volumes}. '
            '이는 읽기 전용 계획이며 실제 Reader 검증·출판 승인이 아닙니다.')

    def open_export_stage(self):
        """두 번째 클릭 시 현재 지문 재확인 후 기존 GUI만 연다."""
        snapshot = self._export_scope_snapshot
        identity = self._export_scope_identity
        target = self.export_stage.currentData()
        self._export_scope_snapshot = None
        self._export_scope_identity = None
        self.export_open_button.setEnabled(False)
        if snapshot is None or identity is None:
            self.status.setText('현재 저장 원고·EPUB 범위를 먼저 직접 확인하세요.')
            return
        try:
            message = open_author_export_stage(
                self.authoring, project_identity=identity,
                snapshot=snapshot, target=target)
        except (ExportHandoffBridgeError, ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self.status.setText(message)
