"""Author-click-only GGUF/executable integrity approval in existing Windows UI."""
from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QPushButton

from ai_novel_factory.local_model_integrity import (
    ApprovedModelLaunch, ModelIntegrityError, capture_local_model_identity,
    verify_local_model_identity,
)


class LocalModelIntegrityPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('로컬 실행 파일·GGUF 바이트 승인 (이번 실행 1회)', parent)
        self.authoring = authoring
        self._identity = None
        self._lease = None
        root = QVBoxLayout(self)
        note = QLabel('모델은 자동 다운로드·교체·실행하지 않습니다. 직접 선택한 로컬 파일만 '
                      '버튼 클릭 시 SHA256으로 확인합니다. 큰 GGUF는 시간이 걸릴 수 있습니다.')
        note.setWordWrap(True)
        root.addWidget(note)
        inspect = QPushButton('선택한 로컬 실행 파일 + GGUF SHA256 확인')
        inspect.setObjectName('localModelIntegrityInspect')
        inspect.clicked.connect(self.inspect)
        root.addWidget(inspect)
        approve = QPushButton('현재 작품·모델 파일의 이번 실행 1회 승인')
        approve.setObjectName('localModelIntegrityApprove')
        approve.clicked.connect(self.approve)
        root.addWidget(approve)
        self.status = QLabel('미확인 · 미승인 · 모델 실행 없음')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        for key in ('executable', 'arguments'):
            self.authoring.fields[key].textChanged.connect(self.invalidate)

    def _configuration(self):
        session = self.authoring.session
        if session.path is None or session.project_id is None:
            raise ModelIntegrityError('기존 작품을 먼저 선택해야 합니다.')
        return (self.authoring._text('executable').strip(),
                self.authoring._text('arguments'), str(session.path),
                str(session.project_id))

    def invalidate(self, *_args):
        self._identity = None
        self._lease = None
        self.status.setText('작품·실행 파일·GGUF 설정이 변경되었습니다. 새 승인이 필요합니다.')

    def inspect(self):
        self.invalidate()
        try:
            executable, arguments, _, _ = self._configuration()
            self._identity = capture_local_model_identity(executable, arguments)
            self.status.setText('실행 파일·GGUF 실제 바이트 SHA256 확인됨. '
                                '품질/한국어 5000자/실제 집필 검증 아님. 별도 승인 필요.')
        except (ModelIntegrityError, OSError, ValueError):
            self.status.setText('선택한 로컬 GGUF/실행 파일을 확인하지 못했습니다.')

    def approve(self):
        self._lease = None
        try:
            if self._identity is None:
                raise ModelIntegrityError('모델 바이트 확인이 필요합니다.')
            executable, arguments, db_path, project_id = self._configuration()
            verify_local_model_identity(self._identity, executable, arguments)
            self._lease = ApprovedModelLaunch(self._identity, db_path, project_id)
            self.status.setText('현재 모델 바이트·작품에 한정한 이번 실행 1회 승인. '
                                '자동 실행/출판 승인 아님.')
        except (ModelIntegrityError, OSError, ValueError):
            self.invalidate()

    def current_identity(self):
        return self._identity if self._lease is not None and not self._lease.used else None

    def consume_for_launch(self):
        lease = self._lease
        if lease is None:
            raise ModelIntegrityError('이번 로컬 모델 실행의 별도 승인이 필요합니다.')
        executable, arguments, db_path, project_id = self._configuration()
        # Do not silently reuse the approval after a failed worker launch.
        self._lease = None
        lease.consume(executable, arguments, db_path, project_id)
        self.status.setText('모델 파일 1회 승인 소모. 재실행은 새 확인/승인 필요.')
