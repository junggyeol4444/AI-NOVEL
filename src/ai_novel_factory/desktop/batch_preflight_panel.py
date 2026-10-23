"""Read-only, author-clicked 1~1000 episode launch scope overview."""
from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QPushButton, QSpinBox

from ai_novel_factory.batch_preflight_matrix import (
    BatchPreflightError, build_batch_preflight,
)
from ai_novel_factory.local_model_integrity import ModelIntegrityError
from ai_novel_factory.reference_intake_plan import ReferenceIntakeError
from .author_batch_scope_bridge import (
    BatchScopeBridgeError, preview_author_batch_scope, handoff_author_batch_scope,
)


class BatchPreflightPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('1~1000화 자동 집필 전 로컬 범위 확인 (실행 아님)', parent)
        self.authoring = authoring
        self._scope_identity = None
        self._scope_snapshot = None
        self._reference_lease = None
        root = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(250)
        self.through.valueChanged.connect(self.invalidate)
        root.addWidget(QLabel('읽기 전용으로 확인할 마지막 회차'))
        root.addWidget(self.through)
        action = QPushButton('현재 SQLite·선택 참고작·승인 GGUF 범위 확인')
        action.setObjectName('batchPreflightReadOnly')
        action.clicked.connect(self.preview)
        root.addWidget(action)
        self.status = QLabel('NOT_RUN: 실제 모델 실행/검증/출판 승인 없음')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.handoff_button = QPushButton('확인한 범위를 기존 AI 배치 설정에 입력 (실행 아님)')
        self.handoff_button.setObjectName('batchPreflightHandoff')
        self.handoff_button.setEnabled(False)
        self.handoff_button.clicked.connect(self.handoff)
        root.addWidget(self.handoff_button)

    def invalidate(self, *_args):
        self._scope_identity = None
        self._scope_snapshot = None
        self._reference_lease = None
        self.handoff_button.setEnabled(False)
        self.status.setText('작품·범위·파일 선택 변경: 새 읽기 전용 확인 필요')

    def preview(self):
        self.invalidate()
        session = self.authoring.session
        if session.path is None or session.project_id is None:
            self.status.setText('기존 작품을 먼저 선택해야 합니다.')
            return
        try:
            batch = self.authoring.auto_panel
            references = tuple(getattr(batch, 'reference_paths', ()))
            identity = self.authoring.local_model_integrity_panel.current_identity()
            report = build_batch_preflight(
                str(session.path), str(session.project_id),
                through_episode=self.through.value(), reference_paths=references,
                model_identity=identity,
                executable=self.authoring._text('executable').strip(),
                arguments=self.authoring._text('arguments'))
            identity, scope, lease = preview_author_batch_scope(
                self.authoring, through_episode=self.through.value())
            if scope.through_episode != report.through_episode:
                raise BatchPreflightError('현재 배치 범위를 다시 선택하세요.')
            self._scope_identity, self._scope_snapshot = identity, scope
            self._reference_lease = lease
            self.handoff_button.setEnabled(
                report.selected_references > 0 and scope.target_chars >= 5000
                and scope.unknown_reference_count == 0)
            formats = ', '.join(f'{ext}:{count}' for ext, count in report.reference_formats)
            self.status.setText(
                f'{report.through_episode}화 읽기 전용: 저장 최종본 {report.final_saved}화, '
                f'초고만 {report.draft_only}화, 미작성/빈 회차 {report.missing}화. '
                f'현재 revision QC 기록 {report.current_qc_records}개 '
                f'(품질 합격 아님), 과거 revision 기록 {report.stale_qc_records}개. '
                f'선택 참고작 {report.selected_references}개 ({formats or "NOT_SELECTED"}), '
                f'GGUF 승인 파일 지문 {"확인" if report.model_identity_checked else "NOT_CHECKED"}. '
                'AI 집필/참고작 전수 비교/Windows 검증/출판은 NOT_RUN.')
        except (BatchPreflightError, BatchScopeBridgeError, ModelIntegrityError,
                ReferenceIntakeError, OSError, ValueError):
            self.status.setText('현재 작품·선택 파일이 변경되었거나 읽기 전용 확인에 실패했습니다.')

    def handoff(self):
        """명시적 두 번째 클릭: 기존 배치 마지막 회차만 입력하고 승인 철회."""
        identity, scope, lease = (
            self._scope_identity, self._scope_snapshot, self._reference_lease)
        self._scope_identity = None
        self._scope_snapshot = None
        self._reference_lease = None
        self.handoff_button.setEnabled(False)
        if identity is None or scope is None or lease is None:
            self.status.setText('먼저 현재 SQLite·참고작·모델 범위를 직접 확인하세요.')
            return
        if scope.through_episode != self.through.value():
            self.status.setText('범위가 변경됐습니다. 다시 조회하세요.')
            return
        try:
            message = handoff_author_batch_scope(
                self.authoring, project_identity=identity,
                snapshot=scope, reference_lease=lease)
        except (BatchScopeBridgeError, ValueError, OSError):
            self.status.setText('현재 작품·원고·참고작이 변경됐습니다. 다시 조회하세요.')
            return
        self.status.setText(message)
