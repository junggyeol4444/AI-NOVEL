"""Offline read-only resume preview; never reuses approval or launches a model."""
from __future__ import annotations
from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout
from ai_novel_factory.auto_resume_plan import preview_resume


class ResumePreviewWidget(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('8. 장편 중단 후 재개 범위 미리보기', parent)
        self.authoring = authoring
        root = QVBoxLayout(self)
        self.notice = QLabel(
            '기존 회차는 덮어쓰지 않습니다. 새 회차 후보만 보여 줍니다. '
            '재개 시에도 모델·작품·회차 범위에 대한 새로운 실행 승인이 필요합니다.')
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)
        self.preview_button = QPushButton('현재 설정 회차까지 미완성 범위 확인 (실행 안 함)')
        self.preview_button.setObjectName('previewNovelResume')
        self.preview_button.clicked.connect(self.refresh)
        root.addWidget(self.preview_button)
        self.status = QLabel('작품을 열고 자동 집필 목표 회차를 설정하세요.')
        self.status.setObjectName('novelResumePreviewStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def refresh(self):
        session = self.authoring.session
        if session is None or session.store is None or session.project_id is None:
            self.status.setText('현재 열린 작품이 없습니다.')
            return
        if self.authoring.auto_panel.is_running():
            self.status.setText('집필 중에는 재개 범위를 변경하지 않습니다.')
            return
        try:
            plan = preview_resume(
                session.store, session.project_id,
                through_episode=self.authoring.auto_panel.through.value())
        except (ValueError, OSError):
            self.status.setText('현재 작품의 회차 범위를 확인할 수 없습니다.')
            return
        first = f'{plan.next_missing}화' if plan.next_missing is not None else '없음'
        self.status.setText(
            f'목표 {plan.through_episode}화 · 기존 {len(plan.existing_episodes)}화 '
            f'· 신규 작성 후보 {len(plan.missing_episodes)}화 '
            f'· 초고 없는 기존 회차 {len(plan.existing_without_draft)}화 '
            f'· 수동 검수 초고 {len(plan.existing_draft_only)}화 '
            f'· 최종본 {len(plan.existing_final)}화 · 다음 빈 회차 {first}. '
            '기존 회차는 자동 수정하지 않으며 실행 승인도 부여되지 않았습니다.')
