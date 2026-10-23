"""Local EPUB3 text lookup and opt-in bookmark recorder, Windows PySide6."""
from __future__ import annotations
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QFormLayout, QLineEdit,
    QLabel, QPushButton, QFileDialog, QListWidget, QPlainTextEdit, QSpinBox)
from ai_novel_factory.private_volume_reader import (
    build_private_volume_catalog, read_selected_volume_chapter)
from ai_novel_factory.epub_private_bookmarks import (
    find_private_epub_text, list_private_bookmarks, save_private_bookmark)
from ai_novel_factory.epub_reader_selection_handoff import (
    ReaderSelectionHandoffError, preview_reader_selection,
    require_current_reader_selection,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError


class EpubPrivateBookmarksPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('비공개 EPUB3 오프라인 검색·책갈피', parent)
        self.authoring = authoring
        self._catalog = None
        self._search = None
        self._marks = ()
        self._folder = ''
        self._handoff_lease = None
        self._handoff_identity = None
        root = QVBoxLayout(self)
        note = QLabel('작가가 직접 선택한 비공개 EPUB3만 열람합니다. 검색어/본문은 기록·전송하지 않습니다.')
        note.setWordWrap(True)
        root.addWidget(note)
        choose = QPushButton('기존 EPUB3 권들 직접 선택 (순서 유지)')
        root.addWidget(choose)
        choose.clicked.connect(self.choose)
        self.status = QLabel('기존 EPUB3 권 선택 전 · 검수/출판 승인 아님')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        form = QFormLayout()
        root.addLayout(form)
        self.query = QLineEdit()
        self.query.setObjectName('epubPrivateLocalQuery')
        form.addRow('본문 검색어', self.query)
        self.search_button = QPushButton('선택한 EPUB3 본문 검색')
        form.addRow(self.search_button)
        self.result_list = QListWidget()
        root.addWidget(self.result_list)
        self.volume = QSpinBox()
        self.volume.setRange(1,16)
        self.chapter = QSpinBox()
        self.chapter.setRange(1,250)
        form.addRow('권 번호', self.volume)
        form.addRow('권 내부 회차', self.chapter)
        preview_btn = QPushButton('현재 선택한 회차 읽기')
        form.addRow(preview_btn)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(225)
        root.addWidget(self.preview)
        folder_btn = QPushButton('책갈피용 기존 로컬 폴더 선택')
        form.addRow(folder_btn)
        self.folder_label = QLabel('책갈피 폴더 미선택')
        form.addRow(self.folder_label)
        add = QPushButton('현재 권·회차를 새 책갈피 파일로 저장 (별도 승인)')
        form.addRow(add)
        read_marks = QPushButton('이 EPUB 선택의 저장된 책갈피 목록 읽기')
        form.addRow(read_marks)
        self.marks = QListWidget()
        root.addWidget(self.marks)
        self.reader_preview = QPushButton('현재 권·회차의 기존 Reader 인계 준비')
        self.reader_preview.setObjectName('epubBookmarkReaderHandoffPreview')
        self.reader_preview.clicked.connect(self.preview_reader_handoff)
        root.addWidget(self.reader_preview)
        self.reader_handoff = QPushButton('확인한 권·회차를 기존 Reader로 이동')
        self.reader_handoff.setObjectName('epubBookmarkReaderHandoff')
        self.reader_handoff.setEnabled(False)
        self.reader_handoff.clicked.connect(self.open_reader_handoff)
        root.addWidget(self.reader_handoff)
        choose_folder = folder_btn.clicked.connect(self.choose_folder)
        add.clicked.connect(self.add_bookmark)
        read_marks.clicked.connect(self.read_bookmarks)
        self.marks.itemActivated.connect(self.open_bookmark)
        self.result_list.itemActivated.connect(self.open_search_hit)
        preview_btn.clicked.connect(self.open_current)
        self.search_button.clicked.connect(self.search)
        self.query.textChanged.connect(self._clear_search)
        self.volume.valueChanged.connect(self._change_volume)
        self.chapter.valueChanged.connect(self._revoke_reader_handoff)

    def _change_volume(self, value):
        self._revoke_reader_handoff()
        if self._catalog is not None and 1 <= value <= len(self._catalog.volumes):
            self.chapter.setMaximum(self._catalog.volumes[value-1].chapters)

    def invalidate(self, *_args):
        self._revoke_reader_handoff()
        self._catalog = None
        self._search = None
        self._marks = ()
        self._folder = ''
        self.result_list.clear()
        self.marks.clear()
        self.preview.clear()
        self.folder_label.setText('책갈피 폴더 미선택')
        self.status.setText('작품/선택이 바뀌어 이전 EPUB 책갈피 권 목록을 폐기했습니다.')

    def _revoke_reader_handoff(self, *_args):
        self._handoff_lease = None
        self._handoff_identity = None
        if hasattr(self, 'reader_handoff'):
            self.reader_handoff.setEnabled(False)

    def accept_reader_selection(self, catalog, lease, identity):
        _, current = _current_author_state(self.authoring)
        if current != identity:
            raise ReaderSelectionHandoffError('작품이 변경됐습니다.')
        require_current_reader_selection(lease, catalog, identity)
        self.invalidate()
        self._catalog = catalog
        self.volume.setMaximum(len(catalog.volumes))
        self.volume.setValue(lease.volume_index)
        self.chapter.setMaximum(catalog.volumes[lease.volume_index - 1].chapters)
        self.chapter.setValue(lease.chapter_index)
        self.status.setText(
            f'{lease.volume_index}권 {lease.chapter_index}회차 선택 인계 완료. '
            '본문 읽기·검색·책갈피 저장은 별도 직접 클릭하세요.')

    def preview_reader_handoff(self):
        self._revoke_reader_handoff()
        try:
            _, identity = _current_author_state(self.authoring)
            lease = preview_reader_selection(
                self._catalog, identity,
                volume_index=self.volume.value(),
                chapter_index=self.chapter.value())
        except (ReaderSelectionHandoffError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('현재 작품·원고·EPUB3 권·회차를 다시 확인하세요.')
            return
        self._handoff_identity, self._handoff_lease = identity, lease
        self.reader_handoff.setEnabled(True)
        self.status.setText('EPUB3 파일 지문 확인 완료. 별도 클릭으로 기존 Reader에 이동할 수 있습니다.')

    def open_reader_handoff(self):
        identity, lease = self._handoff_identity, self._handoff_lease
        self._revoke_reader_handoff()
        if lease is None or identity is None:
            self.status.setText('Reader 인계를 먼저 직접 준비하세요.')
            return
        try:
            _, current = _current_author_state(self.authoring)
            if current != identity:
                raise ReaderSelectionHandoffError('작품이 변경됐습니다.')
            require_current_reader_selection(lease, self._catalog, current)
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    'private_volume_reader_panel', project_identity=identity):
                raise ReaderSelectionHandoffError('기존 Reader를 열지 못했습니다.')
            panel = getattr(self.authoring, 'private_volume_reader_panel', None)
            if panel is None or not hasattr(panel, 'accept_bookmark_selection'):
                raise ReaderSelectionHandoffError('기존 Reader 인계 기능이 없습니다.')
            panel.accept_bookmark_selection(self._catalog, lease, identity)
        except (ReaderSelectionHandoffError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('원고·EPUB3 변경 또는 Reader 인계 실패. 다시 준비하세요.')
            return
        self.status.setText('기존 Reader로 선택 회차를 인계했습니다. 자동 저장·출판 없음.')

    def _clear_search(self):
        self._search = None
        self.result_list.clear()

    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '기존 로컬 EPUB3 권 선택','', 'EPUB3 (*.epub)')
        if not paths:
            return
        self.invalidate()
        try:
            self._catalog = build_private_volume_catalog(tuple(paths))
            self.volume.setMaximum(len(self._catalog.volumes))
            self.volume.setValue(1)
            self.chapter.setMaximum(self._catalog.volumes[0].chapters)
            self.status.setText(f'{len(self._catalog.volumes)}권 / {self._catalog.total_chapters}회차 로컬 선택')
        except (ValueError, OSError):
            self.status.setText('선택한 EPUB3 권을 로컬에서 열지 못했습니다.')

    def _chapter(self, vol:int, ch:int):
        if self._catalog is None:
            raise ValueError('EPUB 미선택')
        return read_selected_volume_chapter(self._catalog, volume_index=vol,
                chapter_index=ch, expected_file_sha256=self._catalog.volumes[vol-1].file_sha256)

    def open_current(self):
        self.preview.clear()
        try:
            title, prose = self._chapter(self.volume.value(), self.chapter.value())
            self.preview.setPlainText(prose)
            self.status.setText(f'로컬 비공개 열람: {title[:80]}')
        except (ValueError, OSError, IndexError):
            self.status.setText('EPUB3 권 또는 회차가 변경되어 다시 선택해야 합니다.')

    def search(self):
        self._clear_search()
        try:
            report = find_private_epub_text(self._catalog, self.query.text())
            self._search = report
            for hit in report.results:
                self.result_list.addItem(f'{hit.volume_index}권 {hit.chapter_index}회차: {hit.title[:45]} / {hit.excerpt[:60]}')
            self.status.setText(f'{report.total_hits}건 발견 · {len(report.results)}건 화면 표시 · 출판 검사 아님')
        except (ValueError, OSError):
            self.status.setText('EPUB3 검색을 완료하지 못했습니다. 원본 선택을 확인하세요.')

    def open_search_hit(self, item):
        if self._search is None:
            return
        index = self.result_list.row(item)
        if not 0 <= index < len(self._search.results):
            return
        hit = self._search.results[index]
        self.volume.setValue(hit.volume_index)
        self.chapter.setMaximum(self._catalog.volumes[hit.volume_index-1].chapters)
        self.chapter.setValue(hit.chapter_index)
        self.open_current()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, '기존 책갈피 저장 폴더 직접 선택')
        if path:
            self._folder = path
            self.folder_label.setText('책갈피 저장 폴더 직접 선택 완료')

    def add_bookmark(self):
        try:
            if self._catalog is None or not self._folder:
                raise ValueError('EPUB/폴더 미선택')
            save_private_bookmark(self._catalog, self._folder,
                volume_index=self.volume.value(), chapter_index=self.chapter.value(),
                explicit_author_save=True)
            self.status.setText('책갈피 새 파일을 로컬에 생성했습니다. 기존 파일은 변경하지 않았습니다.')
        except (ValueError, OSError):
            self.status.setText('책갈피를 저장하지 못했습니다. 권·회차·폴더를 확인하세요.')

    def read_bookmarks(self):
        self.marks.clear()
        self._marks = ()
        try:
            self._marks = list_private_bookmarks(self._catalog, self._folder)
            for mark in self._marks:
                self.marks.addItem(f'{mark.volume_index}권 · {mark.chapter_index}회차 · {mark.created_at[:19]}')
            self.status.setText(f'현재 EPUB 선택에 맞는 책갈피 {len(self._marks)}개 조회')
        except (ValueError, OSError):
            self.status.setText('책갈피를 읽지 못했습니다. EPUB 선택·폴더를 확인하세요.')

    def open_bookmark(self, item):
        index = self.marks.row(item)
        if not 0 <= index < len(self._marks):
            return
        mark = self._marks[index]
        self.volume.setValue(mark.volume_index)
        self.chapter.setMaximum(self._catalog.volumes[mark.volume_index-1].chapters)
        self.chapter.setValue(mark.chapter_index)
        self.open_current()
