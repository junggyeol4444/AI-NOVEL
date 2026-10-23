"""Read-only recovery overview for explicit Windows desktop authoring.

There is deliberately NO resume/start button. The author must use the
existing batch form and grant a fresh one-time model execution approval.
"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout

from ..batch_session_journal import (
    BatchJournalError, list_project_sessions, preview_recovery,
)


def default_batch_journal_directory() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    if not location:
        raise BatchJournalError('로컬 작업 기록 폴더를 확인할 수 없습니다.')
    return Path(location).resolve() / 'batch_sessions'


class BatchRecoveryPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 집필 중단·재개 현황 (읽기 전용)', parent)
        self.authoring = authoring
        layout = QVBoxLayout(self)
        notice = QLabel('이전 실행 기록은 재실행 승인이나 원고 저장 성공 증명이 아닙니다. '
                        '항상 현재 SQLite 회차를 기준으로 표시합니다. '
                        '재개하려면 기존 자동 집필 화면에서 모델과 범위를 확인하고 새로 승인하세요.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.refresh_button = QPushButton('현재 작품 중단 기록·저장 회차 다시 읽기')
        self.refresh_button.setObjectName('batchRecoveryRefresh')
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.status = QLabel('작품을 선택한 뒤 조회하세요.')
        self.status.setObjectName('batchRecoveryStatus')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def refresh(self):
        session = self.authoring.session
        if session.store is None or session.path is None or session.project_id is None:
            self.status.setText('기존 작품 DB를 먼저 열어야 합니다.')
            return
        try:
            receipts = list_project_sessions(
                default_batch_journal_directory(), database_path=session.path,
                project_id=str(session.project_id))
            if not receipts:
                self.status.setText('이 작품의 작업 기록 없음. 기존 SQLite 원고는 별도로 유지됩니다.')
                return
            preview = preview_recovery(session.store, session.path,
                                       str(session.project_id), receipts[0])
            self.status.setText(
                f'최근 기록: {preview.recorded_state} / 현재 판정: {preview.current_state}\n'
                f'대상: 1~{preview.through_episode}화 / 저장 회차 '
                f'{len(preview.already_saved)}개 / 미생성 회차 '
                f'{len(preview.missing_episodes)}개 / 본문 없는 회차 '
                f'{len(preview.existing_without_draft)}개\n'
                '중단 시 모델 실행 중이던 장면은 복원·자동 재실행하지 않습니다. '
                '기존 회차 덮어쓰기 없음. 새 실행 승인 필요. 출판 승인 없음.')
        except (BatchJournalError, OSError, ValueError):
            self.status.setText('작업 기록을 신뢰할 수 없습니다. 자동 재개하지 않습니다.')
