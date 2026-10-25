"""Explicit offline multi-volume EPUB3 reading in the existing PySide6 UI."""
from __future__ import annotations

from hashlib import sha256
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QListWidget, QPlainTextEdit, QSpinBox, QFormLayout, QCheckBox,
)
from ai_novel_factory.private_reading_receipt import (
    PrivateReadingReceiptError, save_private_reading_receipt,
    load_private_reading_receipt,
)
from ai_novel_factory.private_volume_navigation import (
    PrivateVolumeNavigationError, open_private_reading_position,
    jump_private_reading_position, move_private_reading_position,
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
        self._position = None
        self._navigation_busy = False
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
        navigation = QGroupBox('선택한 여러 권의 회차 이어읽기 · 메모리 전용')
        nav_layout = QFormLayout(navigation)
        self.previous_chapter = QPushButton('이전 회차 (권 경계 자동 이동)')
        self.previous_chapter.setObjectName('privateVolumeReaderPreviousChapter')
        self.previous_chapter.clicked.connect(self.read_previous)
        nav_layout.addRow(self.previous_chapter)
        self.next_chapter = QPushButton('다음 회차 (권 경계 자동 이동)')
        self.next_chapter.setObjectName('privateVolumeReaderNextChapter')
        self.next_chapter.clicked.connect(self.read_next)
        nav_layout.addRow(self.next_chapter)
        self.jump_episode = QSpinBox()
        self.jump_episode.setRange(1, 1000)
        self.jump_episode.setObjectName('privateVolumeReaderJumpDisplayEpisode')
        nav_layout.addRow('전체 표시 회차 번호', self.jump_episode)
        self.jump_button = QPushButton('직접 입력한 전체 표시 회차로 이동')
        self.jump_button.setObjectName('privateVolumeReaderJump')
        self.jump_button.clicked.connect(self.read_jump)
        nav_layout.addRow(self.jump_button)
        self.reading_progress = QLabel('현재 열람 위치 없음 · 원고/DB 자동 저장 없음')
        self.reading_progress.setObjectName('privateVolumeReaderProgress')
        self.reading_progress.setWordWrap(True)
        nav_layout.addRow(self.reading_progress)
        layout.addWidget(navigation)
        self.receipt_consent = QCheckBox(
            '현재 열람 위치를 새로운 로컬 JSON으로 보관하는 이번 한 번만 승인')
        self.receipt_consent.setObjectName('privateReaderReceiptConsent')
        layout.addWidget(self.receipt_consent)
        self.receipt_save = QPushButton('현재 읽는 회차 위치를 새 JSON에 직접 보관 (기존 파일 덮어쓰기 금지)')
        self.receipt_save.setObjectName('privateReaderReceiptSave')
        self.receipt_save.clicked.connect(self.save_reading_receipt)
        layout.addWidget(self.receipt_save)
        self.receipt_open = QPushButton('직접 선택한 위치 JSON으로 현재 EPUB3 권에서 이어읽기')
        self.receipt_open.setObjectName('privateReaderReceiptOpen')
        self.receipt_open.clicked.connect(self.open_reading_receipt)
        layout.addWidget(self.receipt_open)
        self._update_navigation()
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
        self._position = None
        self.receipt_consent.setChecked(False)
        self._update_navigation()
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
        self.jump_episode.setMaximum(catalog.total_chapters)
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

    def accept_bookmark_selection(self, catalog, lease, identity, *,
                                  bookmark_position=None):
        _, current = _current_author_state(self.authoring)
        if current != identity:
            raise ReaderSelectionHandoffError('작품이 변경됐습니다.')
        require_current_reader_selection(lease, catalog, identity)
        if bookmark_position is not None:
            if (type(bookmark_position) is not tuple or len(bookmark_position) != 4
                    or bookmark_position[:2] != (lease.volume_index, lease.chapter_index)
                    or type(bookmark_position[2]) is not int
                    or type(bookmark_position[3]) is not str):
                raise ReaderSelectionHandoffError('책갈피 위치 정보가 변경되었습니다.')
        paths = tuple(str(volume.file_path) for volume in catalog.volumes)
        if not self.load_selected_volumes(paths):
            raise ReaderSelectionHandoffError('기존 Reader에서 EPUB3를 다시 열지 못했습니다.')
        require_current_reader_selection(lease, self._catalog, identity)
        self.volumes.setCurrentRow(lease.volume_index - 1)
        self.chapters.setCurrentRow(lease.chapter_index - 1)
        if bookmark_position is not None:
            vi, ci, offset, digest = bookmark_position
            _, prose = read_selected_volume_chapter(
                self._catalog, volume_index=vi, chapter_index=ci,
                expected_file_sha256=self._catalog.volumes[vi-1].file_sha256)
            if (not 0 <= offset <= len(prose)
                    or sha256(prose.encode('utf-8')).hexdigest() != digest
                    or self.reader.toPlainText() != prose):
                self.reader.clear()
                raise ReaderSelectionHandoffError('책갈피 원문 위치가 변경되었습니다.')
            cursor = self.reader.textCursor()
            cursor.setPosition(len(prose[:offset].encode('utf-16-le')) // 2)
            self.reader.setTextCursor(cursor)
            self.reader.ensureCursorVisible()
            self.status.setText(
                '기존 Reader에서 저장된 책갈피의 정확한 본문 위치로 이동했습니다. '
                '검수·출판 승인 아님.')
        else:
            self.status.setText('기존 Reader에서 선택 회차를 열었습니다. 검수·출판 승인 아님.')

    def save_reading_receipt(self):
        approved = self.receipt_consent.isChecked()
        self.receipt_consent.setChecked(False)
        if not approved or self._catalog is None or self._position is None:
            self.status.setText('현재 회차를 연 뒤 새 JSON 보관을 이번 한 번만 별도로 승인하세요.')
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, '새 비공개 EPUB3 이어읽기 위치 JSON', '', 'JSON (*.json)')
        if not destination:
            self.status.setText('열람 위치 보관이 취소됐습니다. 원고/DB 변경 없음.')
            return
        try:
            save_private_reading_receipt(
                self._catalog, self._position, destination,
                explicit_author_save=True)
        except (PrivateReadingReceiptError, ValueError, OSError):
            self.status.setText('현재 EPUB3 지문이 변경됐거나 새 JSON을 생성하지 못했습니다.')
            return
        self.status.setText(
            '작가가 직접 선택한 새 로컬 JSON에 현재 회차 위치만 보관했습니다. '
            'EPUB 원문·파일 경로·원고·DB·출판 상태는 기록하지 않았습니다.')

    def open_reading_receipt(self):
        self.receipt_consent.setChecked(False)
        if self._catalog is None:
            self.status.setText('먼저 기록 당시와 동일한 EPUB3 권을 순서대로 직접 선택하세요.')
            return
        source, _ = QFileDialog.getOpenFileName(
            self, '기존 비공개 이어읽기 위치 JSON 선택', '', 'JSON (*.json)')
        if not source:
            return
        try:
            result = load_private_reading_receipt(self._catalog, source)
        except (PrivateReadingReceiptError, ValueError, OSError):
            self.status.setText('선택한 위치 JSON과 현재 EPUB3 원본/권 순서가 일치하지 않습니다.')
            return
        self._show_navigation_result(result)
        self.status.setText(
            '기존 위치 JSON에서 동일 EPUB3 권·회차를 확인해 다시 열었습니다. '
            '원고·DB·출판 상태 변경 없음.')

    def _update_navigation(self):
        position = self._position
        valid = position is not None and self._catalog is not None
        if hasattr(self, 'previous_chapter'):
            self.previous_chapter.setEnabled(valid and position.display_episode > 1)
            self.next_chapter.setEnabled(
                valid and position.display_episode < position.total_chapters)
            self.jump_button.setEnabled(self._catalog is not None)
            if valid:
                self.reading_progress.setText(
                    f'{position.volume_index}권 {position.chapter_index}회차 · '
                    f'전체 표시 {position.display_episode}/{position.total_chapters}회차. '
                    '현재 위치는 메모리에서만 유지하며 자동 저장하지 않습니다.')
            else:
                self.reading_progress.setText(
                    '현재 열람 위치 없음 · 원고/DB 자동 저장 없음')

    def _show_navigation_result(self, result):
        position, title, prose = result
        self._revoke_handoff()
        self._navigation_busy = True
        try:
            self.volumes.setCurrentRow(position.volume_index - 1)
            self.chapters.setCurrentRow(position.chapter_index - 1)
        finally:
            self._navigation_busy = False
        self._position = position
        self.reader.setPlainText(prose)
        self.jump_episode.setValue(position.display_episode)
        self._update_navigation()
        self.status.setText(
            f'{position.volume_index}권 / {title[:90]} · '
            f'전체 표시 {position.display_episode}/{position.total_chapters}회차. '
            '로컬 비공개 열람 · 품질 검증/출판 승인 아님.')

    def _navigate(self, *, step=None, display_episode=None):
        if self._catalog is None:
            self.status.setText('먼저 기존 로컬 EPUB3 권을 직접 선택하세요.')
            return
        try:
            if step is not None:
                if self._position is None:
                    raise PrivateVolumeNavigationError('먼저 읽을 회차를 선택하세요.')
                result = move_private_reading_position(
                    self._catalog, self._position, step=step)
            else:
                result = jump_private_reading_position(
                    self._catalog, display_episode)
        except (PrivateVolumeNavigationError, ValueError, OSError):
            self._position = None
            self.reader.clear()
            self._update_navigation()
            self._revoke_handoff()
            self.status.setText(
                'EPUB3 원본/선택 위치가 변경됐거나 이동 범위를 벗어났습니다. '
                '현재 권과 회차를 다시 선택하세요.')
            return
        self._show_navigation_result(result)

    def read_previous(self):
        self._navigate(step=-1)

    def read_next(self):
        self._navigate(step=1)

    def read_jump(self):
        self._navigate(display_episode=self.jump_episode.value())

    def _volume_changed(self, row):
        self._revoke_handoff()
        self.chapters.clear()
        self.reader.clear()
        if not self._navigation_busy:
            self._position = None
            self._update_navigation()
        if self._catalog is None or not 0 <= row < len(self._catalog.volumes):
            return
        volume = self._catalog.volumes[row]
        for number in range(1, volume.chapters + 1):
            self.chapters.addItem(f'{volume.first_display_episode + number - 1}번째 회차')
        if not self._navigation_busy:
            self.chapters.setCurrentRow(0)

    def show_chapter(self, row):
        if self._navigation_busy:
            return
        self._revoke_handoff()
        self.reader.clear()
        self._position = None
        self._update_navigation()
        volume_row = self.volumes.currentRow()
        if (self._catalog is None or not 0 <= volume_row < len(self._catalog.volumes)
                or row < 0):
            return
        try:
            result = open_private_reading_position(
                self._catalog, volume_index=volume_row + 1,
                chapter_index=row + 1)
        except (PrivateVolumeNavigationError, ValueError, OSError):
            self.status.setText('EPUB3 원본이 변경되었거나 읽지 못했습니다. 다시 선택하세요.')
            return
        self._show_navigation_result(result)
