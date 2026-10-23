"""Author-click-only local SQLite backup/preview UI, never restores automatically."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QLabel, QPushButton, QVBoxLayout,
)

from ai_novel_factory.project_backup_snapshot import (
    ProjectBackupError, create_project_backup, plan_project_backup,
    preview_project_backup,
)


class ProjectBackupPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('기존 작품 SQLite 로컬 사본 백업 · 자동 복원 없음', parent)
        self.authoring = authoring
        self._plan = None
        self._receipt = None
        self._directory = ''
        root = QVBoxLayout(self)
        info = QLabel('현재 작품을 읽기 전용으로 확인한 뒤 새 백업 파일만 만듭니다. '
                      '원본 SQLite·WAL·원고·모델은 변경하지 않습니다. '
                      '백업 생성은 실제 Windows 재열기/품질 검증이 아닙니다.')
        info.setWordWrap(True)
        root.addWidget(info)
        plan = QPushButton('현재 작품 백업 계획 읽기 전용 조회')
        plan.setObjectName('projectBackupPlan')
        plan.clicked.connect(self.preview_plan)
        root.addWidget(plan)
        choose = QPushButton('원본과 다른 기존 로컬 백업 폴더 선택')
        choose.clicked.connect(self.choose_folder)
        root.addWidget(choose)
        self.consent = QCheckBox('현재 작품 SQLite를 새 파일로 백업하는 이번 1회를 직접 승인합니다')
        root.addWidget(self.consent)
        create = QPushButton('현재 작품 새 SQLite 백업 생성 (덮어쓰기 없음)')
        create.setObjectName('projectBackupCreate')
        create.clicked.connect(self.create_backup)
        root.addWidget(create)
        verify = QPushButton('방금 생성한 백업과 SHA 기록 읽기 전용 미리보기')
        verify.setObjectName('projectBackupPreview')
        verify.clicked.connect(self.preview_backup)
        root.addWidget(verify)
        self.status = QLabel('백업 계획 조회 전 · 자동 백업/복원/외부 전송 없음')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def invalidate(self, *_args):
        self._plan = None
        self._receipt = None
        self.consent.setChecked(False)
        self.status.setText('작품 선택이 변경되었습니다. 현재 작품 백업 계획을 다시 조회하세요.')

    def preview_plan(self):
        self.invalidate()
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('기존 작품을 먼저 열어야 합니다.')
            return
        if self.authoring.auto_panel.is_running() or self.authoring.is_generating():
            self.status.setText('AI 집필이 끝난 뒤 백업 계획을 조회하세요.')
            return
        try:
            self._plan = plan_project_backup(
                self.authoring._text('db'), str(session.project_id))
        except (ProjectBackupError, OSError, ValueError):
            self.status.setText('현재 작품 SQLite 백업 계획을 읽지 못했습니다.')
            return
        self.status.setText(f'현재 SQLite에 작품 {self._plan.projects_count}개 확인. '
                            '백업 위치 선택 및 1회 승인이 필요합니다.')

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '기존 로컬 백업 폴더')
        if folder:
            self._directory = folder
            self.consent.setChecked(False)
            self.status.setText('백업 폴더가 선택되었습니다. 현재 작품을 다시 확인하고 승인하세요.')

    def create_backup(self):
        plan = self._plan
        self._plan = None
        approved = self.consent.isChecked()
        self.consent.setChecked(False)
        if plan is None or not approved:
            self.status.setText('현재 작품 계획과 이번 백업의 명시적 승인이 필요합니다.')
            return
        if self.authoring.auto_panel.is_running() or self.authoring.is_generating():
            self.status.setText('진행 중인 AI 작업이 있어 백업을 시작하지 않았습니다.')
            return
        try:
            self._receipt = create_project_backup(
                plan, self._directory, explicit_author_backup=True)
        except (ProjectBackupError, OSError, ValueError):
            self.status.setText('새 백업 생성이 완료되지 않았습니다. 원본은 변경하지 않았습니다.')
            return
        self.status.setText(
            '새 로컬 SQLite 백업과 SHA 기록을 생성했습니다. '
            + ('백업 중 원본 변경 없음.' if self._receipt.source_current_after_backup
               else '백업 중 원본 변경 감지: 이 사본은 현재 버전 인증이 아닙니다.')
            + ' 자동 복원/출판 없음.')

    def preview_backup(self):
        receipt = self._receipt
        if receipt is None:
            self.status.setText('이번 화면에서 생성한 백업이 없습니다.')
            return
        try:
            result = preview_project_backup(
                receipt.backup_file, receipt.manifest_file, receipt.project_id)
        except (ProjectBackupError, OSError, ValueError):
            self.status.setText('백업 파일 또는 SHA 기록이 달라 읽기 전용 확인을 완료하지 못했습니다.')
            return
        self.status.setText(
            f'백업 파일 SHA 일치 · 작품 {result.project_count}개 읽기 전용 확인. '
            '실제 Windows 재열기·전체 검증·자동 복원·출판 승인 아님.')
