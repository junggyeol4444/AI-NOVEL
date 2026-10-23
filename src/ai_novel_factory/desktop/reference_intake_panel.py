"""Windows GUI: explicit reference preflight and local statistical analysis."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QPushButton, QVBoxLayout

from ..reference_intake_plan import (
    ReferenceIntakeError, plan_reference_intake, require_current_intake,
)
from ..reference_batch_context import ReferenceBatchError, prepare_reference_batch
from .reference_profile_browser import default_local_catalog_path


class ReferenceIntakePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('선택 참고작 5종 · 등록·로컬 분석 (원문 AI 입력 없음)', parent)
        self.authoring = authoring
        self._plan = None
        self._bound_project = None
        root = QVBoxLayout(self)
        self.status = QLabel('자동 집필 영역에서 TXT/MD/EPUB/DOCX/PDF 파일을 먼저 선택하세요.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.preview = QPushButton('현재 선택 파일 1~100개 읽기 전용 확인')
        self.preview.setObjectName('referenceIntakePreview')
        self.preview.clicked.connect(self.preview_selection)
        root.addWidget(self.preview)
        self.consent = QCheckBox('이번 선택 참고작을 로컬에서 분석하고 별도 통계 DB에 등록합니다')
        self.consent.setObjectName('referenceIntakeConsent')
        root.addWidget(self.consent)
        self.analyze = QPushButton('선택 참고작 전부 로컬 등록·분석')
        self.analyze.setObjectName('referenceIntakeAnalyze')
        self.analyze.clicked.connect(self.analyze_selected)
        root.addWidget(self.analyze)

    def invalidate(self):
        self._plan = None
        self._bound_project = None
        self.consent.setChecked(False)
        self.status.setText('선택·작품·파일 변경 시 이전 분석 승인을 재사용하지 않습니다.')

    def _current(self):
        session = self.authoring.session
        if session.path is None or session.project_id is None or session.store is None:
            raise ReferenceIntakeError('먼저 기존 작품 SQLite를 열어야 합니다.')
        paths = tuple(self.authoring.auto_panel.reference_paths)
        return session, paths

    def preview_selection(self):
        self.invalidate()
        try:
            session, paths = self._current()
            plan = plan_reference_intake(paths)
        except (ReferenceIntakeError, OSError, ValueError):
            self.status.setText('참고작을 확인할 수 없습니다. 작품·선택 파일을 다시 확인하세요.')
            return
        self._plan = plan
        self._bound_project = (str(session.path), str(session.project_id))
        formats = ', '.join(f'{fmt.upper()} {count}' for fmt, count in plan.formats)
        self.status.setText(
            f'선택 {len(plan.entries)}개 / {plan.total_bytes}바이트 / {formats}. '
            '현재는 파일 식별만 확인, 본문 분석·유사성 검사·AI 집필·출판은 아직 하지 않았습니다.')

    def analyze_selected(self):
        plan = self._plan
        bound = self._bound_project
        if plan is None or bound is None or not self.consent.isChecked():
            self.status.setText('현재 작품과 참고작을 미리 확인하고 이번 로컬 분석을 직접 승인하세요.')
            return
        # Consume consent before any parser or catalog write.
        self.consent.setChecked(False)
        try:
            session, paths = self._current()
            if (str(session.path), str(session.project_id)) != bound:
                raise ReferenceIntakeError('작품이 변경되었습니다.')
            require_current_intake(plan, paths)
            result = prepare_reference_batch(
                paths, catalog_path=default_local_catalog_path(),
                manuscript_database_path=session.path)
            if len(result.references) != len(plan.entries):
                raise ReferenceIntakeError('참고작 분석 범위가 일치하지 않습니다.')
        except (ReferenceIntakeError, ReferenceBatchError, OSError, ValueError):
            self.status.setText('참고작 전수 로컬 분석을 완료하지 못했습니다. 합격으로 표시하지 않습니다.')
            self.invalidate()
            return
        self._plan = None
        self._bound_project = None
        self.status.setText(
            f'선택 참고작 {len(result.references)}개 로컬 통계 분석 기록 완료. '
            '원문은 원고 SQLite·AI 프롬프트·로그에 저장하지 않습니다. '
            '집필 실행 승인과 회차별 전수 유사성 검사는 별개이며 아직 PASS가 아닙니다.')
