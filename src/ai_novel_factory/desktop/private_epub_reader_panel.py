"""Author-selected private EPUB3 reading in the existing Windows desktop UI.

No remote requests, downloads, publishing, automatic book imports, or writes.
Uses the project's existing EPUB reader and displays only a local preview.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QListWidget, QPlainTextEdit,
)
from ai_novel_factory.private_epub_workflow import read_private_epub_preview


class PrivateEpubReaderPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('비공개 EPUB3 로컬 리더 · 실제 원고 미리보기', parent)
        self.authoring = authoring
        self._chapters = ()
        root = QVBoxLayout(self)
        notice = QLabel('작가가 선택한 기존 로컬 EPUB 파일만 읽습니다. '
                        '읽기는 원고 품질 검증·출판 승인·업로드가 아닙니다.')
        notice.setWordWrap(True)
        root.addWidget(notice)
        choose = QPushButton('기존 EPUB3 파일 선택하여 읽기')
        choose.setObjectName('privateEpubReaderChoose')
        choose.clicked.connect(self.choose_epub)
        root.addWidget(choose)
        self.chapters = QListWidget()
        self.chapters.setObjectName('privateEpubReaderChapters')
        self.chapters.currentRowChanged.connect(self.show_chapter)
        root.addWidget(self.chapters)
        self.reader = QPlainTextEdit()
        self.reader.setReadOnly(True)
        self.reader.setObjectName('privateEpubReaderText')
        root.addWidget(self.reader)
        self.status = QLabel('로컬 EPUB 파일 미선택')
        self.status.setObjectName('privateEpubReaderStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def invalidate(self, *_args):
        self._chapters = ()
        self.chapters.clear()
        self.reader.clear()
        self.status.setText('로컬 EPUB 파일 미선택')

    def choose_epub(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, '기존 로컬 EPUB3 선택', '', 'EPUB (*.epub)')
        if not filename:
            return
        self.invalidate()
        try:
            chapters = read_private_epub_preview(filename)
        except (ValueError, OSError, KeyError):
            self.status.setText('EPUB3 파일을 읽지 못했습니다. 원본은 변경하지 않았습니다.')
            return
        self._chapters = tuple(chapters)
        for index, chapter in enumerate(self._chapters, 1):
            self.chapters.addItem(f'{index}화 · {chapter.title[:90]}')
        self.status.setText(f'{len(self._chapters)}화 로컬 열람 · 출판/품질 승인 없음')
        if self._chapters:
            self.chapters.setCurrentRow(0)

    def show_chapter(self, index):
        if not 0 <= index < len(self._chapters):
            self.reader.clear()
            return
        chapter = self._chapters[index]
        self.reader.setPlainText(chapter.text)
