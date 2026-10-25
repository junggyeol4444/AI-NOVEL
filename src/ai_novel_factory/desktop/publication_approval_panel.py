"""Windows author-only publication consent ledger; NEVER launches publication."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QLineEdit, QSpinBox, QCheckBox,
    QFileDialog,
)
from ai_novel_factory.author_editorial_readiness import (
    build_editorial_readiness_matrix, require_current_editorial_readiness,
)
from ai_novel_factory.project_local_handoff import require_idle_authoring
from .author_batch_scope_bridge import _current_author_state
from ai_novel_factory.publication_release_gate import (
    publication_readiness, publication_authorization_state,
    authorize_publication_snapshot, revoke_publication_authorization,
)


class PublicationApprovalPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('최종 출판 별도 승인 · 실제 게시/업로드 기능과 분리', parent)
        self.authoring = authoring
        self.plan = None
        self._editorial_snapshot = None
        self._editorial_identity = None
        self._editorial_folder = None
        root = QVBoxLayout(self)
        notice = QLabel('이 화면은 로컬 출판 승인 기록만 관리합니다. 실제 출판·원격 업로드는 '
                        '실행하지 않습니다. 비공개 EPUB 생성은 출판 승인이 아닙니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        self.count = QSpinBox()
        self.count.setObjectName('publicationThroughEpisode')
        self.count.setRange(1, 1000)
        root.addWidget(self.count)
        self.issue_folder = QLineEdit()
        self.issue_folder.setReadOnly(True)
        self.issue_folder.setObjectName('publicationIssueFolder')
        self.issue_folder.setPlaceholderText('기존 편집 이슈 기록 폴더를 직접 선택하세요')
        root.addWidget(self.issue_folder)
        select_folder = QPushButton('출판 전 확인할 기존 편집 이슈 기록 폴더 선택')
        select_folder.setObjectName('publicationChooseIssueFolder')
        select_folder.clicked.connect(self.choose_issue_folder)
        root.addWidget(select_folder)
        preview = QPushButton('출판 대상 원고·검수·검사 누락 확인')
        preview.setObjectName('publicationReadiness')
        preview.clicked.connect(self.refresh_plan)
        root.addWidget(preview)
        self.status = QLabel('별도 출판 미승인')
        self.status.setObjectName('publicationApprovalStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.human = QCheckBox('대상 전체 원고를 직접 확인했습니다')
        self.human.setObjectName('publicationHumanReviewed')
        self.scope = QCheckBox('로컬 승인 기록이며 자동 게시/업로드가 아님을 확인합니다')
        self.scope.setObjectName('publicationSeparateConsent')
        root.addWidget(self.human)
        root.addWidget(self.scope)
        self.confirm = QLineEdit()
        self.confirm.setObjectName('publicationConfirmationPhrase')
        self.confirm.setPlaceholderText('출판 승인 작품제목 30화')
        root.addWidget(self.confirm)
        approve = QPushButton('별도 출판 승인 기록 (자동 출판 없음)')
        approve.setObjectName('publicationAuthorizeLocal')
        approve.clicked.connect(self.authorize)
        root.addWidget(approve)
        revoke = QPushButton('기존 출판 승인 철회 기록')
        revoke.setObjectName('publicationRevokeLocal')
        revoke.clicked.connect(self.revoke)
        root.addWidget(revoke)
        self.count.valueChanged.connect(self.invalidate)

    def choose_issue_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, '기존 로컬 편집 이슈 기록 폴더 선택')
        if path:
            self.invalidate()
            self.issue_folder.setText(path)

    def invalidate(self, *_args):
        self.plan = None
        self._editorial_snapshot = None
        self._editorial_identity = None
        self._editorial_folder = None
        self.human.setChecked(False)
        self.scope.setChecked(False)
        self.confirm.clear()
        self.status.setText('원고 상태를 다시 확인해야 합니다. 출판 승인 아님.')

    def _current(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            raise ValueError('먼저 로컬 작품을 열어 주세요.')
        return session, session.project_id

    def refresh_plan(self):
        self.invalidate()
        try:
            session, identity = _current_author_state(self.authoring)
            pid = str(session.project_id)
            require_idle_authoring(self.authoring, pid)
            folder = self.issue_folder.text().strip()
            if not folder:
                raise ValueError('기존 편집 기록 폴더를 선택해야 합니다.')
            snapshot = build_editorial_readiness_matrix(
                session.store, pid, through_episode=self.count.value(),
                issue_folder=folder)
            plan = publication_authorization_state(
                session.store, pid, through_episode=self.count.value())
            if (snapshot.project_id != plan.project_id
                    or snapshot.through_episode != plan.through_episode
                    or len(snapshot.chapters) != plan.through_episode):
                raise ValueError('편집 기록과 출판 대상 회차가 일치하지 않습니다.')
        except (ValueError, OSError):
            self.status.setText(
                '현재 작품·미저장 원고·편집 이슈 기록 폴더·검수 현황을 다시 확인하세요.')
            return
        self.plan = plan
        self._editorial_snapshot = snapshot
        self._editorial_identity = identity
        self._editorial_folder = folder
        self.status.setText(
            f'{plan.through_episode}화 중 검수·QC 누락 {len(plan.incomplete_episodes)}화 / '
            f'미해결 또는 과거 종료 편집 이슈 {snapshot.pending_issues}건 / '
            f'최종본 누락 {snapshot.missing_final}화 / '
            f'별도 승인 {"있음" if plan.publication_approved else "없음"}. '
            '편집 이슈와 원고가 변경되면 현재 승인은 다시 확인해야 합니다.')

    def authorize(self):
        session = self.authoring.session
        plan = self.plan
        snapshot = self._editorial_snapshot
        identity = self._editorial_identity
        folder = self._editorial_folder
        if (plan is None or snapshot is None or identity is None or folder is None
                or session.store is None or str(session.project_id) != plan.project_id):
            self.status.setText('현재 작품의 원고·편집 이슈·출판 준비 상태를 다시 확인하세요.')
            return
        try:
            require_idle_authoring(self.authoring, plan.project_id)
            _, current_identity = _current_author_state(self.authoring)
            if (identity != current_identity
                    or folder != self.issue_folder.text().strip()
                    or snapshot.project_id != plan.project_id
                    or snapshot.through_episode != plan.through_episode
                    or snapshot.pending_issues or snapshot.missing_final
                    or len(snapshot.chapters) != plan.through_episode):
                raise ValueError('편집 기록이 미완료 또는 변경되었습니다.')
            require_current_editorial_readiness(
                snapshot, session.store, plan.project_id, issue_folder=folder)
            authorize_publication_snapshot(
                session.store, plan.project_id, through_episode=plan.through_episode,
                expected_source_sha256=plan.source_sha256,
                confirmation=self.confirm.text(), human_checked=self.human.isChecked(),
                publication_scope_understood=self.scope.isChecked())
        except (ValueError, OSError):
            self.status.setText('출판 승인 기록 거부: 미해결 편집 이슈·검수 누락·원고 변경 또는 별도 승인 문구 불일치.')
            self.invalidate()
            return
        self.invalidate()
        self.status.setText('현재 로컬 원고 스냅샷에 별도 승인 기록 완료. 실제 출판/업로드 없음.')

    def revoke(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('먼저 로컬 작품을 열어 주세요.')
            return
        try:
            revoke_publication_authorization(
                session.store, session.project_id, through_episode=self.count.value(),
                confirmation=self.confirm.text())
        except (ValueError, OSError):
            self.status.setText('철회 기록 실패: 회차와 명시적 철회 문구를 확인하세요.')
            return
        self.invalidate()
        self.status.setText('로컬 출판 승인 철회 기록 완료. 외부 출판 작업 없음.')
