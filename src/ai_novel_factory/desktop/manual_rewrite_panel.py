"""Existing Windows GUI: explicit in-memory manual draft rewrite."""
from __future__ import annotations
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit, QCheckBox
from ai_novel_factory.manual_rewrite_workspace import begin_manual_rewrite, commit_manual_rewrite


class ManualRewritePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('저장된 초고 수동 재작성 · 기존 최종본 보호', parent)
        self.authoring = authoring
        self.lease = None
        root = QVBoxLayout(self)
        label = QLabel('현재 회차 저장 초고를 별도 편집합니다. 직접 저장 버튼 전에는 SQLite 변경 없음. '
                       '최종 원고는 덮어쓰지 않으며 재작성 후 검수/품질 판정은 다시 필요합니다.')
        label.setWordWrap(True)
        root.addWidget(label)
        load = QPushButton('현재 저장 초고를 재작성 편집기로 불러오기')
        load.setObjectName('manualRewriteLoad')
        load.clicked.connect(self.load_current)
        root.addWidget(load)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName('manualRewriteEditor')
        self.editor.setPlaceholderText('작가가 직접 수정한 초고를 입력합니다.')
        root.addWidget(self.editor)
        self.consent = QCheckBox('현재 회차의 초고만 수정 저장하며 재검수해야 함을 확인합니다')
        self.consent.setObjectName('manualRewriteConsent')
        root.addWidget(self.consent)
        save = QPushButton('수동 재작성 초고 저장 (기존 최종본 유지)')
        save.setObjectName('manualRewriteSave')
        save.clicked.connect(self.save_current)
        root.addWidget(save)
        self.status = QLabel('재작성 미시작')
        self.status.setObjectName('manualRewriteStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.editor.textChanged.connect(lambda: self.consent.setChecked(False))

    def invalidate(self, *_args):
        self.lease = None
        self.editor.clear()
        self.consent.setChecked(False)
        self.status.setText('현재 회차를 다시 불러와야 합니다.')

    def load_current(self):
        self.invalidate()
        session = self.authoring.session
        if not session.store or not session.project_id or not session.episode_number:
            self.status.setText('먼저 작품과 회차를 선택하세요.')
            return
        try:
            lease, draft = begin_manual_rewrite(
                session.store, session.project_id, session.episode_number)
        except (ValueError, OSError):
            self.status.setText('현재 저장 초고를 불러오지 못했습니다.')
            return
        self.editor.setPlainText(draft)
        self.lease = lease
        self.status.setText(f'{lease.episode}화 저장 초고를 편집 중 · 미저장')

    def save_current(self):
        session = self.authoring.session
        lease = self.lease
        if (lease is None or session.store is None or session.project_id != lease.project_id
                or session.episode_number != lease.episode or not self.consent.isChecked()):
            self.status.setText('현재 회차와 저장 승인을 다시 확인해야 합니다.')
            return
        self.consent.setChecked(False)
        try:
            revision = commit_manual_rewrite(
                session.store, lease, self.editor.toPlainText(), explicit_author_save=True)
        except (ValueError, OSError):
            self.status.setText('원고 변경 또는 저장 실패. 기존 최종본을 유지했습니다.')
            self.lease = None
            return
        self.lease = None
        self.authoring._invalidate_author_review_snapshots()
        self.authoring._sync()
        self.status.setText(f'{lease.episode}화 초고 revision {revision} 저장 · 검수/검사 재실행 필요')
