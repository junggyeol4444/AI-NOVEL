"""Windows author-only publication consent ledger; NEVER launches publication."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QLineEdit, QSpinBox, QCheckBox,
)
from ai_novel_factory.publication_release_gate import (
    publication_readiness, publication_authorization_state,
    authorize_publication_snapshot, revoke_publication_authorization,
)


class PublicationApprovalPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('최종 출판 별도 승인 · 실제 게시/업로드 기능과 분리', parent)
        self.authoring = authoring
        self.plan = None
        root = QVBoxLayout(self)
        notice = QLabel('이 화면은 로컬 출판 승인 기록만 관리합니다. 실제 출판·원격 업로드는 '
                        '실행하지 않습니다. 비공개 EPUB 생성은 출판 승인이 아닙니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        self.count = QSpinBox()
        self.count.setObjectName('publicationThroughEpisode')
        self.count.setRange(1, 1000)
        root.addWidget(self.count)
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

    def invalidate(self, *_args):
        self.plan = None
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
            session, pid = self._current()
            plan = publication_authorization_state(
                session.store, pid, through_episode=self.count.value())
        except (ValueError, OSError):
            self.status.setText('현재 작품의 검수 상태를 읽지 못했습니다.')
            return
        self.plan = plan
        self.status.setText(
            f'{plan.through_episode}화 중 검수·QC 누락 {len(plan.incomplete_episodes)}화 / '
            f'별도 승인 {"있음" if plan.publication_approved else "없음"} / {plan.status}. '
            '현재 원고와 검사 기록이 바뀌면 기존 승인 무효.')

    def authorize(self):
        session = self.authoring.session
        plan = self.plan
        if plan is None or session.store is None or session.project_id != plan.project_id:
            self.status.setText('현재 작품의 출판 준비 상태를 다시 확인하세요.')
            return
        try:
            outcome = authorize_publication_snapshot(
                session.store, plan.project_id, through_episode=plan.through_episode,
                expected_source_sha256=plan.source_sha256,
                confirmation=self.confirm.text(), human_checked=self.human.isChecked(),
                publication_scope_understood=self.scope.isChecked())
        except (ValueError, OSError):
            self.status.setText('출판 승인 기록 거부: 검사 누락·원고 변경 또는 승인 문구 불일치.')
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
