"""Project-scoped GUI worklist for human-reviewed novel chapters.

Displays ONLY chapter numbers and inspection coverage, not source manuscript
passages or reference works. Clicking a row opens the existing authoring
selector; it cannot approve, publish, revise or overwrite an episode.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QGroupBox, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from ai_novel_factory.review_worklist import get_review_worklist
from ai_novel_factory.manual_review_gate import (
    ManualReviewError, acknowledge_review, revoke_review, review_state,
    project_review_readiness,
)


class ReviewWorklistWidget(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('7. 장편 회차 검수 대기 및 미완료 검사', parent)
        self.authoring = authoring
        self._selected_snapshot = None
        root = QVBoxLayout(self)
        self.notice = QLabel(
            '저장된 회차의 실제 검사 기록을 표시합니다. 검사가 누락되었거나 '
            '초고만 존재하면 수동 검수가 필요합니다. '
            '목록 열람/이동은 원고 확정 또는 출판 승인이 아닙니다.')
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)
        self.rows = QListWidget()
        self.rows.setObjectName('authoringReviewWorklist')
        root.addWidget(self.rows)
        self.refresh_button = QPushButton('현재 작품의 검수 대기 목록 새로고침')
        self.refresh_button.setObjectName('refreshAuthoringReviewWorklist')
        self.refresh_button.clicked.connect(self.refresh)
        root.addWidget(self.refresh_button)
        self.open_button = QPushButton('선택한 회차를 기존 편집 화면에서 열기')
        self.open_button.setObjectName('openAuthoringReviewEpisode')
        self.open_button.clicked.connect(self.open_selected)
        root.addWidget(self.open_button)
        self.summary = QLabel('작품을 열어야 회차 검수 대기 상태를 확인할 수 있습니다.')
        self.summary.setObjectName('authoringReviewWorklistStatus')
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.human_read = QCheckBox('선택한 회차 최종 원고를 제가 직접 읽고 검수했습니다')
        self.human_read.setObjectName('manualReviewHumanRead')
        root.addWidget(self.human_read)
        self.qc_understood = QCheckBox('누락·실패·보류 검사 및 출판 미승인 상태를 확인했습니다')
        self.qc_understood.setObjectName('manualReviewQCUnderstood')
        root.addWidget(self.qc_understood)
        self.record_button = QPushButton('선택 회차의 현재 원고 검수 사실 기록 (출판 승인 아님)')
        self.record_button.setObjectName('recordManualNovelReview')
        self.record_button.clicked.connect(self.record_selected_review)
        root.addWidget(self.record_button)
        self.revoke_checkbox = QCheckBox('선택 회차 검수 기록 철회를 확인합니다')
        self.revoke_checkbox.setObjectName('manualReviewRevokeConfirm')
        root.addWidget(self.revoke_checkbox)
        self.revoke_button = QPushButton('선택 회차의 검수 기록 철회')
        self.revoke_button.setObjectName('revokeManualNovelReview')
        self.revoke_button.clicked.connect(self.revoke_selected_review)
        root.addWidget(self.revoke_button)
        self.readiness_button = QPushButton('현재 자동 집필 목표까지 검수 준비 현황 확인 (출판 아님)')
        self.readiness_button.setObjectName('manualReviewReadiness')
        self.readiness_button.clicked.connect(self.show_readiness)
        root.addWidget(self.readiness_button)
        self.manual_status = QLabel('검수 기록은 현재 원고와 검사 기록에만 유효합니다.')
        self.manual_status.setObjectName('manualReviewStatus')
        self.manual_status.setWordWrap(True)
        root.addWidget(self.manual_status)
        self.rows.currentItemChanged.connect(self._selection_changed)

    def _selection_changed(self, current, _previous):
        self._selected_snapshot = None
        self.human_read.setChecked(False)
        self.qc_understood.setChecked(False)
        self.revoke_checkbox.setChecked(False)
        if current is None:
            return
        session = self.authoring.session
        number = current.data(Qt.ItemDataRole.UserRole)
        if session.store is None or session.project_id is None or type(number) is not int:
            return
        try:
            state = review_state(session.store, session.project_id, number)
        except (ValueError, OSError):
            self.manual_status.setText('현재 회차 검수 상태를 읽을 수 없습니다.')
            return
        self._selected_snapshot = (
            session.project_id, number, state.revision, state.snapshot_sha256)
        self.manual_status.setText(
            f'{number}화 검수 상태: {state.status} · '
            f'미완료 검사 {len(state.incomplete_checks)}개 · 출판 미승인')

    def record_selected_review(self):
        snapshot = self._selected_snapshot
        session = self.authoring.session
        if (snapshot is None or session.store is None
                or session.project_id != snapshot[0]):
            self.manual_status.setText('현재 작품의 회차를 다시 선택하세요.')
            return
        try:
            result = acknowledge_review(
                session.store, snapshot[0], snapshot[1],
                expected_revision=snapshot[2], expected_snapshot_sha256=snapshot[3],
                human_read=self.human_read.isChecked(),
                incomplete_qc_understood=self.qc_understood.isChecked())
        except (ManualReviewError, ValueError, OSError):
            self.manual_status.setText('원고가 변경되었거나 직접 검수 확인이 부족합니다. 다시 확인하세요.')
            self.human_read.setChecked(False)
            self.qc_understood.setChecked(False)
            return
        self.human_read.setChecked(False)
        self.qc_understood.setChecked(False)
        self.manual_status.setText(
            f'{result.episode}화 검수 사실 기록: {result.status}. 출판 승인이 아닙니다.')
        self.authoring._invalidate_author_review_snapshots()
        self.refresh()

    def revoke_selected_review(self):
        snapshot = self._selected_snapshot
        session = self.authoring.session
        if (snapshot is None or session.store is None
                or session.project_id != snapshot[0]
                or not self.revoke_checkbox.isChecked()):
            self.manual_status.setText('철회할 현재 회차와 철회 확인을 선택하세요.')
            return
        try:
            result = revoke_review(session.store, snapshot[0], snapshot[1],
                                   confirmation=f'REVOKE_REVIEW {snapshot[1]}')
        except (ManualReviewError, ValueError, OSError):
            self.manual_status.setText('검수 기록을 철회할 수 없습니다. 현재 작품을 확인하세요.')
            return
        self.revoke_checkbox.setChecked(False)
        self.manual_status.setText(f'{result.episode}화 검수 기록 철회됨. 출판 승인 없음.')
        self.authoring._invalidate_author_review_snapshots()
        self.refresh()

    def show_readiness(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.manual_status.setText('작품을 먼저 여세요.')
            return
        try:
            report = project_review_readiness(
                session.store, session.project_id,
                through_episode=self.authoring.auto_panel.through.value())
        except (ManualReviewError, ValueError, OSError):
            self.manual_status.setText('현재 작품 검수 준비 상태를 확인할 수 없습니다.')
            return
        self.manual_status.setText(
            f'대상 {report.total}화 / 현재 검수 기록 {report.reviewed_current}화 / '
            f'검사 기록 모두 PASS {report.qc_complete}화 / '
            f'추가 확인 필요 {len(report.pending_episodes)}화. '
            '문학 품질·출판 승인·외부 업로드는 별도입니다.')

    def refresh(self):
        self._selected_snapshot = None
        self.rows.clear()
        session = self.authoring.session
        if session is None or session.project_id is None or session.store is None:
            self.summary.setText('열린 작품이 없어 검수 대기 목록은 표시되지 않습니다.')
            return
        try:
            report = get_review_worklist(session.store, session.project_id)
        except (ValueError, OSError):
            self.summary.setText('현재 작품의 검수 기록을 읽을 수 없습니다.')
            return
        for chapter in report.chapters:
            note = (
                f'{chapter.episode}화 · {chapter.review_label} · '
                f'검사 누락 {len(chapter.missing_checks)} · '
                f'이전 본문 검사 {len(chapter.stale_checks)} · '
                f'보류 {len(chapter.pending_checks)} · '
                f'실패 {len(chapter.failed_checks)}')
            item = QListWidgetItem(note)
            item.setData(Qt.ItemDataRole.UserRole, chapter.episode)
            self.rows.addItem(item)
        self.summary.setText(
            f'현재 작품 총 {len(report.chapters)}화 / '
            f'본문 미완성 {report.incomplete_count}화 / '
            f'검수 필요 {report.review_required_count}화. '
            '출판 승인: 없음. 실제 모델 문학 품질 인증이 아닙니다.')

    def open_selected(self):
        item = self.rows.currentItem()
        if item is None:
            self.summary.setText('이동할 회차를 선택하세요.')
            return
        number = item.data(Qt.ItemDataRole.UserRole)
        session = self.authoring.session
        selector = self.authoring.episodes
        if (session is None or session.project_id is None
                or type(number) is not int):
            self.summary.setText('기존 작품과 회차가 일치하지 않습니다.')
            return
        # Resolve selection ONLY against the current project's real selector.
        index = selector.findData(number)
        if index < 0:
            self.summary.setText('현재 작품에 해당 회차가 없어 이동하지 않았습니다.')
            return
        selector.setCurrentIndex(index)
        self.summary.setText(
            f'{number}화를 기존 편집 화면에서 선택했습니다. '
            '수동 검수·최종본 저장은 별도 명시적 버튼으로 진행하세요.')
