"""Explicit Windows UI for private backup-to-NEW-SQLite copy; never overwrites."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QLabel, QPushButton, QVBoxLayout,
)

from ai_novel_factory.project_restore_copy import (
    ProjectRestoreError, create_restore_copy, plan_restore_copy,
)


class ProjectRestorePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('기존 백업 → 새 SQLite 사본 (자동 복원 없음)', parent)
        self.authoring = authoring
        self._backup = ''
        self._manifest = ''
        self._destination = ''
        self._plan = None
        self._receipt = None
        layout = QVBoxLayout(self)
        description = QLabel('기존 로컬 백업과 SHA 기록을 확인한 뒤 다른 폴더에 새 파일만 생성합니다. '
                             '기존 작품 DB·백업은 수정하지 않으며 자동으로 열지 않습니다.')
        description.setWordWrap(True)
        layout.addWidget(description)
        choose_backup = QPushButton('기존 로컬 백업 SQLite 선택')
        choose_backup.clicked.connect(self.choose_backup)
        layout.addWidget(choose_backup)
        choose_manifest = QPushButton('해당 백업의 SHA 기록 JSON 선택')
        choose_manifest.clicked.connect(self.choose_manifest)
        layout.addWidget(choose_manifest)
        preview = QPushButton('현재 작품 기준 백업 읽기 전용 확인')
        preview.setObjectName('restoreCopyPreview')
        preview.clicked.connect(self.preview)
        layout.addWidget(preview)
        choose_target = QPushButton('백업 폴더와 다른 기존 로컬 사본 저장 폴더 선택')
        choose_target.clicked.connect(self.choose_target)
        layout.addWidget(choose_target)
        self.approved = QCheckBox('현재 확인한 백업을 새 SQLite 파일로 복사하는 이번 1회를 직접 승인합니다')
        layout.addWidget(self.approved)
        save = QPushButton('새 SQLite 사본 생성 (기존 파일 덮어쓰기 금지)')
        save.setObjectName('restoreCopyExplicit')
        save.clicked.connect(self.copy)
        layout.addWidget(save)
        self.status = QLabel('백업 파일·기록을 직접 선택하세요. 출판·자동 복원 없음.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def invalidate(self, *_args):
        self._plan = None
        self._receipt = None
        self.approved.setChecked(False)
        self.status.setText('작품 또는 파일 선택이 변경되어 이전 승인과 계획을 폐기했습니다.')

    def choose_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, '로컬 백업 선택', '', 'SQLite (*.sqlite *.db)')
        if path:
            self._backup = path
            self.invalidate()

    def choose_manifest(self):
        path, _ = QFileDialog.getOpenFileName(self, '백업 SHA 기록 선택', '', 'JSON (*.json)')
        if path:
            self._manifest = path
            self.invalidate()

    def choose_target(self):
        path = QFileDialog.getExistingDirectory(self, '새 사본을 저장할 기존 로컬 폴더')
        if path:
            self._destination = path
            self.approved.setChecked(False)
            self.status.setText('저장 폴더가 변경되었습니다. 현재 계획을 확인하고 다시 승인하세요.')

    def _idle_project(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            raise ProjectRestoreError('기존 작품을 먼저 열어야 합니다.')
        if self.authoring.auto_panel.is_running() or self.authoring.is_generating():
            raise ProjectRestoreError('AI 집필 중에는 사본을 만들 수 없습니다.')
        return str(session.project_id)

    def preview(self):
        self.invalidate()
        try:
            project_id = self._idle_project()
            self._plan = plan_restore_copy(self._backup, self._manifest, project_id)
            self.status.setText(f'백업에 작품 {self._plan.project_count}개 확인. '
                                '새 저장 폴더 선택과 별도 1회 승인이 필요합니다.')
        except (ProjectRestoreError, OSError, ValueError):
            self.status.setText('현재 작품과 일치하는 백업을 확인하지 못했습니다.')

    def copy(self):
        plan = self._plan
        approved = self.approved.isChecked()
        self._plan = None
        self.approved.setChecked(False)
        if plan is None or not approved:
            self.status.setText('백업 읽기 전용 확인과 별도 1회 승인이 필요합니다.')
            return
        try:
            if self._idle_project() != plan.project_id:
                raise ProjectRestoreError('작품이 변경되었습니다.')
            self._receipt = create_restore_copy(
                plan, self._destination, explicit_author_copy=True)
            self.status.setText('새 로컬 SQLite 사본과 SHA 기록을 생성했습니다. '
                                '기존 작품 변경 없음 · 자동 열기/복원/출판 없음. '
                                '열려면 기존 SQLite 재열기에서 직접 선택하세요.')
        except (ProjectRestoreError, OSError, ValueError):
            self.status.setText('새 사본 생성을 완료하지 못했습니다. 기존 작품은 변경하지 않았습니다.')
