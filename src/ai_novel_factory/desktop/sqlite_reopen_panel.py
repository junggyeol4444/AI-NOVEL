"""Windows read-only existing-project preview, then explicit classic Open."""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QGroupBox, QLabel, QPushButton, QVBoxLayout

from ..sqlite_reopen_preview import (
    SqliteReopenError, preview_existing_sqlite, require_current_sqlite,
)
from ..project_local_handoff import (
    LocalHandoffError, NewCopyHandoff, require_idle_authoring,
    require_new_copy_handoff,
)


class SqliteReopenPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('기존 작품 SQLite 안전 재열기', parent)
        self.authoring = authoring
        self._preview = None
        self._copy_handoff = None
        layout = QVBoxLayout(self)
        self.status = QLabel('기존 작품 파일을 선택하면 읽기 전용으로 작품 개수만 미리 확인합니다.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.choose = QPushButton('기존 SQLite 선택·읽기 전용 미리보기')
        self.choose.setObjectName('sqliteReopenPreview')
        self.choose.clicked.connect(self.choose_database)
        layout.addWidget(self.choose)
        self.open = QPushButton('선택한 기존 작품 실제 열기 (사용자 명시 실행)')
        self.open.setObjectName('sqliteReopenOpen')
        self.open.clicked.connect(self.open_database)
        layout.addWidget(self.open)

    def invalidate(self):
        self._preview = None
        self._copy_handoff = None

    def choose_database(self):
        self.invalidate()
        if self.authoring.auto_panel.is_running() or self.authoring.is_generating():
            self.status.setText('로컬 AI 작업이 끝난 뒤 다른 작품을 선택하세요.')
            return
        path, _ = QFileDialog.getOpenFileName(
            self, '기존 작품 SQLite 선택', '', 'SQLite (*.db *.sqlite)')
        if not path:
            return
        try:
            plan = preview_existing_sqlite(path)
        except (SqliteReopenError, OSError, ValueError):
            self.status.setText('기존 작품 DB의 읽기 전용 미리보기를 완료하지 못했습니다.')
            return
        self._preview = plan
        self.status.setText(
            f'작품 {len(plan.projects)}개 확인. 원고·설정은 표시하거나 수정하지 않았습니다. '
            '열기를 누르면 기존 작품 열기 기능으로 이동합니다.')

    def accept_new_copy_handoff(self, handoff: NewCopyHandoff) -> bool:
        try:
            require_new_copy_handoff(handoff)
            require_idle_authoring(self.authoring, handoff.project_id)
            preview = preview_existing_sqlite(handoff.copy)
            require_current_sqlite(preview)
            self.invalidate()
            self._preview = preview
            self._copy_handoff = handoff
            self.status.setText('검사한 새 사본만 선택했습니다. 실제 작품 열기는 아래 버튼을 별도로 눌러야 합니다.')
            return True
        except (LocalHandoffError, SqliteReopenError, OSError, ValueError):
            self.invalidate()
            return False

    def open_database(self):
        plan = self._preview
        lease = self._copy_handoff
        self.invalidate()
        if plan is None:
            self.status.setText('기존 SQLite를 먼저 선택해 주세요.')
            return
        if self.authoring.auto_panel.is_running() or self.authoring.is_generating():
            self.status.setText('진행 중인 AI 작업이 있어 다른 작품을 열 수 없습니다.')
            return
        try:
            require_idle_authoring(self.authoring, str(self.authoring.session.project_id))
            require_current_sqlite(plan)
            if lease is not None:
                if lease.copy != plan.path or lease.project_id != str(self.authoring.session.project_id):
                    raise LocalHandoffError('인계된 작품이 변경되었습니다.')
                require_new_copy_handoff(lease)
            self.authoring._revoke_project_approvals()
            self.authoring._set('db', str(plan.path))
            self.authoring._open()
            self.authoring._sync()
        except (SqliteReopenError, LocalHandoffError, ValueError, OSError):
            self.status.setText('작품이 변경되었거나 열 수 없습니다. 다시 선택하세요.')
            return
        self.status.setText('기존 작품을 열었습니다. 새 모델 실행과 출판은 별도 승인 필요.')
