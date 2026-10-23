"""Read-only GUI preview of time-scoped author facts, omissions and conflicts."""
from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QSpinBox, QVBoxLayout
from ai_novel_factory.author_fact_context import build_author_fact_context


class AuthorFactContextPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('회차별 작가 사실 문맥 미리보기 (AI 실행 없음)', parent)
        self.authoring = authoring
        root = QVBoxLayout(self)
        self.episode = QSpinBox()
        self.episode.setRange(1, 1000)
        root.addWidget(self.episode)
        self.status = QLabel('과거 최종본 근거·충돌·누락만 확인합니다. 품질 합격 아님.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        refresh = QPushButton('선택 회차의 구조화 사실 범위 조회 (읽기 전용)')
        refresh.setObjectName('authorFactContextPreview')
        refresh.clicked.connect(self.refresh)
        root.addWidget(refresh)

    def invalidate(self):
        self.status.setText('작품이 변경되었습니다. 다시 조회하세요.')

    def refresh(self):
        try:
            session = self.authoring.session
            panel = self.authoring.author_fact_panel
            if session.store is None or session.project_id is None or not panel.folder.text():
                raise ValueError
            report = build_author_fact_context(
                session.store, str(session.project_id),
                next_episode=self.episode.value(), folder=panel.folder.text())
            self.status.setText(
                f'{report.episode}화: 포함 {report.included}건 / 근거 변경 {report.stale_source}건 / '
                f'서로 충돌 {report.conflicting}종 / 미래·범위 외 {report.future_or_inactive}건 / '
                f'철회 {report.retracted}건 / 문맥 길이로 미포함 {report.truncated}건. '
                '검사 합격·출판 승인이 아닙니다.')
        except (ValueError, OSError):
            self.status.setText('현재 작품의 구조화 사실 문맥을 조회할 수 없습니다.')
