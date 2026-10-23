"""Explicit offline multi-volume EPUB3 reading in the existing PySide6 UI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QListWidget, QPlainTextEdit,
)

from ai_novel_factory.private_volume_reader import (
    build_private_volume_catalog, read_selected_volume_chapter,
)
from ai_novel_factory.epub_reader_selection_handoff import (
    ReaderSelectionHandoffError, preview_reader_selection,
    require_current_reader_selection,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError


class PrivateVolumeReaderPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('비공개 EPUB3 여러 권 로컬 이어읽기', parent)
        self.authoring = authoring
        self._catalog = None
        self._handoff_lease = None
        self._handoff_identity = None
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
        self.bookmark_preview = QPushButton('현재 권·회차의 검색·책갈피 인계 준비')
        self.bookmark_preview.setObjectName('privateReaderBookmarkHandoffPreview')
        self.bookmark_preview.clicked.connect(self.preview_bookmark_handoff)
        layout.addWidget(self.bookmark_preview)
        self.bookmark_handoff = QPushButton('확인한 권·회차를 기존 검색·책갈피 화면으로 이동')
        self.bookmark_handoff.setObjectName('privateReaderBookmarkHandoff')
        self.bookmark_handoff.setEnabled(False)
        self.bookmark_handoff.clicked.connect(self.open_bookmark_handoff)
        layout.addWidget(self.bookmark_handoff)

    def invalidate(self, *_args):
        self._revoke_handoff()
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

    def _revoke_handoff(self):
        self._handoff_lease = None
        self._handoff_identity = None
        if hasattr(self, 'bookmark_handoff'):
            self.bookmark_handoff.setEnabled(False)

    def preview_bookmark_handoff(self):
        self._revoke_handoff()
        try:
            _, identity = _current_author_state(self.authoring)
            lease = preview_reader_selection(
                self._catalog, identity,
                volume_index=self.volumes.currentRow() + 1,
                chapter_index=self.chapters.currentRow() + 1)
        except (ReaderSelectionHandoffError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('현재 작품·미저장 원고·EPUB3 권과 회차를 확인하세요.')
            return
        self._handoff_identity, self._handoff_lease = identity, lease
        self.bookmark_handoff.setEnabled(True)
        self.status.setText(
            f'{lease.volume_index}권 {lease.chapter_index}회차 확인. '
            '다음 별도 클릭에서 검색·책갈피 화면에 선택만 전달합니다.')

    def open_bookmark_handoff(self):
        identity, lease = self._handoff_identity, self._handoff_lease
        self._revoke_handoff()
        if lease is None or identity is None:
            self.status.setText('현재 권·회차 인계를 먼저 준비하세요.')
            return
        try:
            _, current = _current_author_state(self.authoring)
            if current != identity:
                raise ReaderSelectionHandoffError('작품이 변경됐습니다.')
            require_current_reader_selection(lease, self._catalog, current)
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    'epub_private_bookmarks_panel', project_identity=identity):
                raise ReaderSelectionHandoffError('기존 검색·책갈피 화면을 열지 못했습니다.')
            panel = getattr(self.authoring, 'epub_private_bookmarks_panel', None)
            if panel is None or not hasattr(panel, 'accept_reader_selection'):
                raise ReaderSelectionHandoffError('기존 검색·책갈피 인계 기능이 없습니다.')
            panel.accept_reader_selection(self._catalog, lease, identity)
        except (ReaderSelectionHandoffError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('원고·EPUB3가 변경됐거나 인계에 실패했습니다. 다시 준비하세요.')
            return
        self.status.setText('기존 검색·책갈피 화면에 권·회차 선택만 전달했습니다. '
                            '검색·책갈피 저장은 별도 직접 클릭해야 합니다.')

    def accept_bookmark_selection(self, catalog, lease, identity):
        _, current = _current_author_state(self.authoring)
        if current != identity:
            raise ReaderSelectionHandoffError('작품이 변경됐습니다.')
        require_current_reader_selection(lease, catalog, identity)
        paths = tuple(str(volume.file_path) for volume in catalog.volumes)
        if not self.load_selected_volumes(paths):
            raise ReaderSelectionHandoffError('기존 Reader에서 EPUB3를 다시 열지 못했습니다.')
        require_current_reader_selection(lease, self._catalog, identity)
        self.volumes.setCurrentRow(lease.volume_index - 1)
        self.chapters.setCurrentRow(lease.chapter_index - 1)
        self.status.setText('기존 Reader에서 선택 회차를 열었습니다. 검수·출판 승인 아님.')

    def _volume_changed(self, row):
        self._revoke_handoff()
        self.chapters.clear()
        self.reader.clear()
        if self._catalog is None or not 0 <= row < len(self._catalog.volumes):
            return
        volume = self._catalog.volumes[row]
        for number in range(1, volume.chapters + 1):
            self.chapters.addItem(f'{volume.first_display_episode + number - 1}번째 회차')
        self.chapters.setCurrentRow(0)

    def show_chapter(self, row):
        self._revoke_handoff()
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
