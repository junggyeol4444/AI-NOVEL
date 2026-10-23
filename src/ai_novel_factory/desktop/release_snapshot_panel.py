"""Windows GUI for in-memory publication snapshot readiness; never publishes."""
from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QSpinBox, QVBoxLayout

from ..release_snapshot_manifest import plan_release_snapshot


class ReleaseSnapshotPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('최종 출판 별도 승인 상태 · 로컬 스냅샷 확인', parent)
        self.authoring = authoring
        layout = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.setObjectName('releaseSnapshotThrough')
        layout.addWidget(self.through)
        self.refresh_button = QPushButton('현재 최종본·QC·작가 출판 승인 상태 확인')
        self.refresh_button.setObjectName('releaseSnapshotRefresh')
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button)
        self.status = QLabel('승인 기록이 있어도 실제 출판·업로드·공개는 실행하지 않습니다.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def invalidate(self):
        self.status.setText('원고/작품 변경 후 다시 확인해야 합니다. 출판·업로드 없음.')

    def refresh(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('기존 작품을 먼저 열어야 합니다.')
            return
        try:
            manifest = plan_release_snapshot(
                session.store, str(session.project_id),
                through_episode=self.through.value())
        except (OSError, ValueError):
            self.status.setText('현재 최종본·검수·승인 기록을 확인하지 못했습니다.')
            return
        self.status.setText(
            f'{manifest.through_episode}화 / 상태 {manifest.status} / '
            f'스냅샷 포함 {len(manifest.chapters)}화 / '
            f'미완료 {len(manifest.missing_or_unreviewed)}화. '
            '승인된 로컬 스냅샷이어도 실제 출판·원격 전송은 별도 작업이며 실행하지 않습니다.')
