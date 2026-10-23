"""Windows GUI: explicit opt-in and read-only scene checkpoint counts."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout

from ..scene_checkpoint_store import (
    SceneCheckpointError, list_checkpoint_overviews,
)


def default_scene_checkpoint_directory() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation)
    if not base:
        raise SceneCheckpointError('로컬 장면 임시 저장 위치를 찾지 못했습니다.')
    return Path(base).resolve() / 'unapproved_scene_checkpoints'


class SceneCheckpointPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장면 단위 중단·재개 임시 저장 현황', parent)
        self.authoring = authoring
        layout = QVBoxLayout(self)
        notice = QLabel(
            '사용자가 별도 승인한 실행에서만 생성된 AI 장면 초안을 로컬 임시 폴더에 저장합니다. '
            '저장된 원고 SQLite와 분리되며, 현재 설정·모델·작가 저장 자료가 같을 때만 재사용 후보입니다. '
            '임시 파일은 검수 합격·출판 승인이나 다음 모델 실행 승인이 아닙니다.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.refresh_button = QPushButton('현재 작품 임시 장면 개수 조회')
        self.refresh_button.setObjectName('sceneCheckpointRefresh')
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.status = QLabel('작품을 열고 조회하세요.')
        self.status.setWordWrap(True)
        self.status.setObjectName('sceneCheckpointStatus')
        layout.addWidget(self.status)

    def refresh(self) -> None:
        session = self.authoring.session
        if session.store is None or session.path is None or session.project_id is None:
            self.status.setText('기존 작품 DB를 먼저 열어야 합니다.')
            return
        try:
            rows = list_checkpoint_overviews(
                default_scene_checkpoint_directory(),
                database_path=session.path, project_id=str(session.project_id))
            if not rows:
                self.status.setText('현재 작품에 기록된 장면 임시 파일이 없습니다.')
                return
            self.status.setText('\n'.join(
                f'{row.episode}화: 설정별 임시 기록 {row.checkpoint_sets}묶음 / '
                f'미검증 단계 파일 {row.unverified_stage_files}개'
                for row in rows[:30]) +
                ('\n이하 생략' if len(rows) > 30 else '') +
                '\n원고 내용은 표시하지 않습니다. 모델 실행은 기존 화면에서 매번 새로 승인하세요.')
        except (SceneCheckpointError, OSError, ValueError):
            self.status.setText('임시 기록을 신뢰할 수 없습니다. 자동 재개하지 않습니다.')
