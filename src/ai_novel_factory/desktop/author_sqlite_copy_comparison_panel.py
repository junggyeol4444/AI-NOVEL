"""기존 Windows PySide6 작가 GUI의 SQLite 원본·새 복원 사본 읽기 전용 대조."""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QGroupBox, QLabel, QPushButton, QVBoxLayout

from ai_novel_factory.author_sqlite_copy_comparison import (
    AuthorCopyComparisonError, compare_author_sqlite_copy,
    require_current_author_copy_comparison,
)
from ai_novel_factory.project_local_handoff import (
    LocalHandoffError, require_idle_authoring,
)


class AuthorSqliteCopyComparisonPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('기존 SQLite 원본 · 새 복원 사본 내용 직접 대조', parent)
        self.authoring = authoring
        self._copy = ''
        self._receipt = ''
        self._snapshot = None
        self._identity = None
        layout = QVBoxLayout(self)
        info = QLabel('기존 SQLite와 작가가 선택한 별도 복원 사본의 bible_ 테이블 실제 행을 '
                      '로컬에서 읽기 전용 대조합니다. 원고 본문은 표시하지 않습니다. '
                      '같은 내용이라도 실제 Windows 재열기 검증·품질 합격·출판 승인이 아닙니다.')
        info.setWordWrap(True)
        layout.addWidget(info)
        choose_copy = QPushButton('기존 새 복원 SQLite 사본 직접 선택')
        choose_copy.setObjectName('authorSqliteCopyChoose')
        choose_copy.clicked.connect(self.choose_copy)
        layout.addWidget(choose_copy)
        choose_receipt = QPushButton('해당 사본의 SHA 기록 JSON 직접 선택')
        choose_receipt.setObjectName('authorSqliteCopyReceipt')
        choose_receipt.clicked.connect(self.choose_receipt)
        layout.addWidget(choose_receipt)
        compare = QPushButton('원본·사본 저장 내용 읽기 전용 전수 대조 (첫 클릭)')
        compare.setObjectName('authorSqliteCopyCompare')
        compare.clicked.connect(self.compare)
        layout.addWidget(compare)
        self.handoff = QPushButton('확인한 사본을 기존 SQLite 재열기 화면에 선택만 전달 (두 번째 클릭)')
        self.handoff.setObjectName('authorSqliteCopyHandoff')
        self.handoff.setEnabled(False)
        self.handoff.clicked.connect(self.open_reopen_stage)
        layout.addWidget(self.handoff)
        self.status = QLabel('현재 작품을 연 뒤 로컬 사본과 SHA 기록을 직접 선택하세요.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def invalidate(self, *_args):
        self._snapshot = self._identity = None
        self.handoff.setEnabled(False)
        self.status.setText('현재 원본·사본·기록을 다시 직접 조회하세요.')

    def choose_copy(self):
        path, _ = QFileDialog.getOpenFileName(self, '새 복원 사본 선택', '', 'SQLite (*.sqlite *.db)')
        if path:
            self._copy = path
            self.invalidate()

    def choose_receipt(self):
        path, _ = QFileDialog.getOpenFileName(self, '새 사본 SHA 기록 선택', '', 'JSON (*.json)')
        if path:
            self._receipt = path
            self.invalidate()

    def compare(self):
        self.invalidate()
        try:
            session = self.authoring.session
            if session.path is None or session.project_id is None:
                raise AuthorCopyComparisonError('현재 작품을 먼저 열어 주세요.')
            project_id = str(session.project_id)
            require_idle_authoring(self.authoring, project_id)
            identity = (str(session.path), project_id)
            snapshot = compare_author_sqlite_copy(
                session.path, self._copy, self._receipt, project_id)
        except (AuthorCopyComparisonError, LocalHandoffError, ValueError, OSError):
            self.status.setText('원본·사본·SHA 기록을 읽기 전용으로 대조하지 못했습니다.')
            return
        self._snapshot, self._identity = snapshot, identity
        self.handoff.setEnabled(True)
        self.status.setText(
            f'원본 테이블 {snapshot.source_tables}개 · 사본 {snapshot.copy_tables}개 · '
            f'내용 동일 테이블 {snapshot.matched_tables}개 · 차이 후보 '
            f'{len(snapshot.differing_tables)}개 · 원본 저장 회차 {snapshot.source_episode_rows}개 · '
            f'사본 저장 회차 {snapshot.copy_episode_rows}개. '
            '원본과 사본의 생성 시점 차이는 정상일 수 있습니다. '
            '재열기·검수·출판은 별도 실행입니다.')

    def open_reopen_stage(self):
        snapshot, identity = self._snapshot, self._identity
        self.invalidate()  # 한 번 인계 후 이전 조회·승인 재사용 금지
        if snapshot is None or identity is None:
            return
        try:
            session = self.authoring.session
            if (str(session.path), str(session.project_id)) != identity:
                raise AuthorCopyComparisonError('현재 작품이 변경됐습니다.')
            require_idle_authoring(self.authoring, identity[1])
            require_current_author_copy_comparison(snapshot)
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature('sqlite_reopen_panel', project_identity=identity):
                raise AuthorCopyComparisonError('기존 재열기 화면을 열지 못했습니다.')
            panel = getattr(self.authoring, 'sqlite_reopen_panel', None)
            if panel is None or not panel.accept_author_copy_comparison(snapshot):
                raise AuthorCopyComparisonError('사본 선택 인계가 취소됐습니다.')
        except (AuthorCopyComparisonError, LocalHandoffError, ValueError, OSError):
            self.status.setText('현재 원고·SQLite·사본이 변경됐습니다. 다시 직접 조회하세요.')
            return
        self.status.setText('기존 SQLite 재열기에 사본 선택만 전달했습니다. 실제 열기는 별도 직접 클릭입니다.')
