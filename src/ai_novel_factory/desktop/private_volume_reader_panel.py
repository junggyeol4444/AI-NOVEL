"""Explicit offline multi-volume EPUB3 reading in the existing PySide6 UI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QListWidget, QPlainTextEdit,
)

from ai_novel_factory.private_volume_reader import (
    build_private_volume_catalog, read_selected_volume_chapter,
)


class PrivateVolumeReaderPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('비공개 EPUB3 여러 권 로컬 이어읽기', parent)
        self.authoring = authoring
        self._catalog = None
        layout = QVBoxLayout(self)
        notice = QLabel('작가가 직접 고른 EPUB 파일 순서대로 열람합니다. '
                        '권/회차 번호는 화면 표시 순서이며 원본 작품 번호 인증이 아닙니다. '
                        '실제 Windows Reader 인수·품질·출판 승인 아님.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        select = QPushButton('기존 로컬 EPUB3 여러 권 순서대로 선택')
        select.setObjectName('privateVolumeReaderSelect')
        select.clicked.connect(self.choose_volumes)
        layout.addWidget(select)
        self.volumes = QListWidget()
        self.volumes.setObjectName('privateVolumeReaderVolumes')
        self.volumes.currentRowChanged.connect(self._volume_changed)
        layout.addWidget(self.volumes)
        self.chapters = QListWidget()
        self.chapters.setObjectName('privateVolumeReaderChapters')
        self.chapters.currentRowChanged.connect(self.show_chapter)
        layout.addWidget(self.chapters)
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self.reader.setObjectName('privateVolumeReaderText')
        self.reader.setMaximumHeight(240)
        layout.addWidget(self.reader)
        self.status = QLabel('EPUB3 파일 미선택')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def invalidate(self, *_args):
        self._catalog = None
        self.volumes.clear()
        self.chapters.clear()
        self.reader.clear()
        self.status.setText('작품 또는 EPUB 선택이 변경되었습니다. 다시 선택하세요.')

    def choose_volumes(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, '읽을 EPUB3 권들을 순서대로 선택', '', 'EPUB3 (*.epub)')
        if paths:
            self.load_selected_volumes(tuple(paths))

    def load_selected_volumes(self, paths: tuple[str, ...]) -> bool:
        """기존 대조 화면의 명시적 인계 또는 직접 파일 선택만 허용."""
        self.invalidate()
        if type(paths) is not tuple:
            self.status.setText('EPUB3 권을 직접 선택해야 합니다.')
            return False
        try:
            catalog = build_private_volume_catalog(paths)
        except (ValueError, OSError):
            self.status.setText('선택한 EPUB3 권의 로컬 읽기 목록을 만들지 못했습니다.')
            return False
        self._catalog = catalog
        for entry in catalog.volumes:
            self.volumes.addItem(
                f'{entry.index}권 · 표시 {entry.first_display_episode}~'
                f'{entry.last_display_episode}번째 · {entry.chapters}개 회차')
        self.status.setText(
            f'{len(catalog.volumes)}권 / {catalog.total_chapters}회차 로컬 열람 준비. '
            '실제 EPUB Reader 통합 검증·출판 승인 아님.')
        self.volumes.setCurrentRow(0)
        return True

    def _volume_changed(self, row):
        self.chapters.clear()
        self.reader.clear()
        if self._catalog is None or not 0 <= row < len(self._catalog.volumes):
            return
        volume = self._catalog.volumes[row]
        for number in range(1, volume.chapters + 1):
            self.chapters.addItem(f'{volume.first_display_episode + number - 1}번째 회차')
        self.chapters.setCurrentRow(0)

    def show_chapter(self, row):
        self.reader.clear()
        volume_row = self.volumes.currentRow()
        if (self._catalog is None or not 0 <= volume_row < len(self._catalog.volumes)
                or row < 0):
            return
        volume = self._catalog.volumes[volume_row]
        try:
            title, text = read_selected_volume_chapter(
                self._catalog, volume_index=volume_row + 1,
                chapter_index=row + 1, expected_file_sha256=volume.file_sha256)
        except (ValueError, OSError):
            self.status.setText('EPUB3 원본이 변경되었거나 읽지 못했습니다. 다시 선택하세요.')
            return
        self.reader.setPlainText(text)
        self.status.setText(f'{volume.index}권 / {title[:90]} · 비공개 로컬 열람만 가능')
