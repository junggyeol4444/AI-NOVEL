"""로컬 출판 스냅샷과 회차별 검수 근거를 조회하는 Windows GUI.

원고/검수 근거와 별도 출판 승인을 혼동하지 않는다. 모델 실행·출판 없음.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QLabel, QPushButton, QSpinBox, QVBoxLayout,
    QTableWidget, QTableWidgetItem,
)

from ..release_snapshot_manifest import plan_release_snapshot
from ..episode_review_dashboard import build_review_dashboard
from .author_navigation_contract import check_author_navigation, select_saved_episode


class ReleaseSnapshotPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('최종 출판 별도 승인 상태 · 로컬 스냅샷 확인', parent)
        self.authoring = authoring
        self._identity = None
        self._lease = None
        self._chapters = ()
        layout = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.setObjectName('releaseSnapshotThrough')
        layout.addWidget(self.through)
        self.refresh_button = QPushButton('현재 최종본·QC·작가 출판 승인 상태 확인')
        self.refresh_button.setObjectName('releaseSnapshotRefresh')
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.status = QLabel('승인 기록이 있어도 실제 출판·업로드·공개는 실행하지 않습니다.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.detail = QTableWidget(0, 6)
        self.detail.setObjectName('releaseSnapshotChapterEvidence')
        self.detail.setHorizontalHeaderLabels((
            '회차', '최종본', 'QC 근거', '참고작 비교', '작가 검수', '상태'))
        self.detail.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail.setMaximumHeight(240)
        layout.addWidget(self.detail)
        self.editor_button = QPushButton('선택 회차 기존 원고 편집기 열기 (저장·승인 없음)')
        self.editor_button.setObjectName('releaseSnapshotOpenChapter')
        self.editor_button.clicked.connect(self.open_editor)
        layout.addWidget(self.editor_button)
        self.review_button = QPushButton('회차별 기존 QC·작가 검수 화면 열기')
        self.review_button.setObjectName('releaseSnapshotOpenReview')
        self.review_button.clicked.connect(self.open_review)
        layout.addWidget(self.review_button)
        self.approval_button = QPushButton('기존 별도 출판 승인 기록 화면 열기 (승인 실행 없음)')
        self.approval_button.setObjectName('releaseSnapshotOpenApproval')
        self.approval_button.clicked.connect(self.open_approval)
        layout.addWidget(self.approval_button)
        self.through.valueChanged.connect(self.invalidate)

    def invalidate(self, *_args):
        self._lease = None
        self._identity = None
        self._chapters = ()
        self.detail.setRowCount(0)
        self.status.setText('원고/작품 변경 후 다시 확인해야 합니다. 출판·업로드 없음.')

    def _read_snapshot(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None or session.path is None:
            raise ValueError('기존 작품을 먼저 열어야 합니다.')
        project_id = str(session.project_id)
        through = self.through.value()
        manifest = plan_release_snapshot(
            session.store, project_id, through_episode=through)
        report = build_review_dashboard(
            session.store, project_id, through_episode=through)
        # 출판 승인/검수/참고작 근거가 하나라도 바뀌면 앞선 화면 인계를 폐기.
        lease = (
            manifest.snapshot_sha256, manifest.status, manifest.approved,
            tuple((chapter.episode, chapter.revision, chapter.manuscript,
                   chapter.qc_state, chapter.reference_scope,
                   chapter.human_review) for chapter in report.chapters),
        )
        return (str(session.path), project_id), manifest, report, lease

    def refresh(self):
        self.invalidate()
        try:
            identity, manifest, report, lease = self._read_snapshot()
        except (OSError, ValueError, LookupError):
            self.status.setText('현재 작품의 최종본·QC·작가 검수 기록을 읽지 못했습니다.')
            return
        self._identity = identity
        self._lease = lease
        self._chapters = report.chapters
        # 실제 범위는 전부 읽고, 표에는 최대 200화만 표시한다.
        visible = report.chapters[:200]
        self.detail.setRowCount(len(visible))
        for index, chapter in enumerate(visible):
            values = (
                str(chapter.episode), chapter.manuscript, chapter.qc_state,
                chapter.reference_scope, chapter.human_review,
                '재검토 필요' if (
                    chapter.manuscript != 'FINAL_SAVED_NOT_PUBLISHED'
                    or chapter.qc_state != 'RECORDED_SCOPE_ONLY'
                    or chapter.reference_scope in ('NOT_RUN', 'STALE', 'INCOMPLETE')
                    or not chapter.human_review.startswith('REVIEWED_')
                ) else '근거 기록 존재',
            )
            for column, value in enumerate(values):
                self.detail.setItem(index, column, QTableWidgetItem(value))
        self.status.setText(
            f'{manifest.through_episode}화 / {manifest.status} / '
            f'스냅샷 포함 {len(manifest.chapters)}화 / '
            f'미완료 {len(manifest.missing_or_unreviewed)}화 / '
            f'QC 미완료 {report.qc_incomplete}화 / '
            f'참고작 범위 재검토 {report.reference_not_examined}화 / '
            f'작가 검수 미완료 {report.unreviewed_or_stale}화. '
            f'표에는 앞 {len(visible)}화만 표시합니다. '
            '근거 존재는 품질·저작권 PASS나 출판 승인 아님.')

    def _selected_episode(self):
        row = self.detail.currentRow()
        if row < 0 or row >= len(self._chapters):
            raise ValueError('표에서 기존 회차를 먼저 선택하세요.')
        return self._chapters[row].episode

    def _current_selection(self):
        if self._lease is None or self._identity is None:
            raise ValueError('현재 작품을 다시 직접 조회하세요.')
        identity, _manifest, _report, lease = self._read_snapshot()
        if identity != self._identity or lease != self._lease:
            self.invalidate()
            raise ValueError('원고·검수·승인 기록이 바뀌었습니다. 다시 조회하세요.')
        episode = self._selected_episode()
        decision = check_author_navigation(
            self.authoring, project_identity=self._identity, episode=episode)
        if not decision.allowed:
            raise ValueError(decision.message)
        return episode

    def open_editor(self):
        try:
            episode = self._current_selection()
            decision = select_saved_episode(
                self.authoring, project_identity=self._identity, episode=episode)
        except (ValueError, OSError, LookupError) as error:
            self.status.setText(str(error))
            return
        self.status.setText(decision.message)

    def _open_existing(self, feature):
        try:
            episode = self._current_selection()
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    feature, episode_number=self.through.value(),
                    project_identity=self._identity):
                self.status.setText('기존 기능 화면을 열지 못했습니다. 다시 직접 선택하세요.')
                return
        except (ValueError, OSError, LookupError) as error:
            self.status.setText(str(error))
            return
        self.status.setText(
            f'{episode}화 선택 후 기존 화면을 열었습니다. '
            '조회·검수·출판 승인 실행은 해당 화면에서 별도 직접 클릭해야 합니다.')

    def open_review(self):
        self._open_existing('review_dashboard_panel')

    def open_approval(self):
        self._open_existing('publication_approval_panel')
