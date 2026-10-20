"""Read-only local manuscript reader over the CURRENT SQLite authoring session.

This is a real GUI surface, not a simulated reader score. It only reads
persisted draft/final text, never unsaved previews, reference sources or
publishing accounts. All writer edits and publication approvals remain separate.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QPlainTextEdit, QSpinBox, QLineEdit, QFileDialog,
)
from ai_novel_factory.epub3 import EpubError
from ai_novel_factory.epub_reader import read_private_epub


class PrivateNovelReader(QWidget):
    """Reader navigation never calls EpisodeStore write methods."""

    def __init__(self, session_getter, parent=None):
        super().__init__(parent)
        self.setObjectName('privateNovelReader')
        self._session_getter = session_getter
        self._project_key = None
        self._epub_chapters = None
        layout = QVBoxLayout(self)
        title = QLabel('저장된 소설 원고 읽기 · 내 PC 전용')
        title.setObjectName('privateReaderTitle')
        layout.addWidget(title)
        notice = QLabel(
            '기존 SQLite에 저장된 원고만 읽습니다. 저장하지 않은 수정 내용은 보이지 않으며, '
            '미승인 초고는 최종본이나 출판 승인으로 표시하지 않습니다.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        book_bar = QHBoxLayout()
        self.open_epub = QPushButton('검증된 로컬 EPUB3 파일 읽기')
        self.open_epub.setObjectName('privateReaderOpenEpub')
        self.open_epub.clicked.connect(self._choose_epub)
        book_bar.addWidget(self.open_epub)
        self.show_sqlite = QPushButton('현재 작품 SQLite 원고로 돌아가기')
        self.show_sqlite.setObjectName('privateReaderReturnSqlite')
        self.show_sqlite.clicked.connect(self._return_to_project)
        book_bar.addWidget(self.show_sqlite)
        layout.addLayout(book_bar)
        controls = QHBoxLayout()
        self.episodes = QComboBox()
        self.episodes.setObjectName('privateReaderEpisodes')
        self.episodes.setAccessibleName('읽을 회차 선택')
        controls.addWidget(self.episodes, 1)
        self.version = QComboBox()
        self.version.setObjectName('privateReaderVersion')
        self.version.addItem('최종본 우선', 'auto')
        self.version.addItem('저장된 미승인 초고', 'draft')
        self.version.addItem('저장된 사용자 검수 최종본', 'final')
        controls.addWidget(self.version, 1)
        self.previous = QPushButton('이전 회차')
        self.previous.setObjectName('privateReaderPrevious')
        self.previous.clicked.connect(lambda: self._step(-1))
        controls.addWidget(self.previous)
        self.next = QPushButton('다음 회차')
        self.next.setObjectName('privateReaderNext')
        self.next.clicked.connect(lambda: self._step(1))
        controls.addWidget(self.next)
        layout.addLayout(controls)
        self.status = QLabel('작품을 열고 읽기 버튼을 눌러 주세요.')
        self.status.setObjectName('privateReaderStatus')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.body = QPlainTextEdit()
        self.body.setObjectName('privateReaderText')
        self.body.setAccessibleName('저장된 회차 본문 읽기 전용')
        self.body.setReadOnly(True)
        self.body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.body, 1)
        search = QHBoxLayout()
        self.find_input = QLineEdit()
        self.find_input.setObjectName('privateReaderFindText')
        self.find_input.setPlaceholderText('현재 회차 본문에서 찾기')
        self.find_input.returnPressed.connect(self._find)
        search.addWidget(self.find_input, 1)
        self.find_button = QPushButton('다음 찾기')
        self.find_button.setObjectName('privateReaderFindNext')
        self.find_button.clicked.connect(self._find)
        search.addWidget(self.find_button)
        self.font_size = QSpinBox()
        self.font_size.setObjectName('privateReaderFontSize')
        self.font_size.setRange(12, 30)
        self.font_size.setValue(16)
        self.font_size.setSuffix('pt')
        self.font_size.valueChanged.connect(self._font_changed)
        search.addWidget(self.font_size)
        layout.addLayout(search)
        self.episodes.currentIndexChanged.connect(self._display)
        self.version.currentIndexChanged.connect(self._display)
        self._font_changed(self.font_size.value())
        self._buttons()

    def _font_changed(self, size):
        font = self.body.font()
        font.setPointSize(size)
        self.body.setFont(font)

    def _buttons(self):
        i = self.episodes.currentIndex()
        self.previous.setEnabled(i > 0)
        self.next.setEnabled(0 <= i < self.episodes.count() - 1)

    def _step(self, delta):
        index = self.episodes.currentIndex() + delta
        if 0 <= index < self.episodes.count():
            self.episodes.setCurrentIndex(index)

    def _find(self):
        text = self.find_input.text()
        if not text or not self.body.toPlainText():
            return
        if not self.body.find(text):
            cursor = self.body.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self.body.setTextCursor(cursor)
            self.body.find(text)

    def _choose_epub(self):
        file, _ = QFileDialog.getOpenFileName(
            self, '로컬 EPUB3 원고 선택', '', 'EPUB 파일 (*.epub)')
        if file:
            self._load_epub_file(file)

    def _load_epub_file(self, file):
        # Verify/read the complete archive before changing the open book.
        try:
            chapters = read_private_epub(file)
        except (EpubError, OSError, ValueError):
            self.status.setText('로컬 EPUB3 검증 실패 · 현재 책은 변경하지 않았습니다.')
            return
        self._epub_chapters = chapters
        self.version.setEnabled(False)
        self.episodes.blockSignals(True)
        try:
            self.episodes.clear()
            for number, chapter in enumerate(chapters, 1):
                self.episodes.addItem(f'{number}화 · {chapter.title}', number)
            self.episodes.setCurrentIndex(0)
        finally:
            self.episodes.blockSignals(False)
        self._display()

    def _return_to_project(self):
        self._epub_chapters = None
        self.version.setEnabled(True)
        self.refresh()

    def refresh(self):
        if self._epub_chapters is not None:
            self._display()
            return
        # This method is called when entering the reader tab, not by a
        # timer. It never creates or alters a database or manuscript.
        self.body.clear()
        self.status.setText('선택된 로컬 작품의 저장 원고 확인 중')
        self.episodes.blockSignals(True)
        previous_number = self.episodes.currentData()
        self.episodes.clear()
        try:
            session = self._session_getter()
            if not session or session.store is None or not session.project_id:
                self._project_key = None
                self.status.setText('작품을 먼저 생성하거나 열어 주세요.')
                return
            identity = (str(session.path), session.project_id)
            if self._project_key != identity:
                previous_number = None
            self._project_key = identity
            saved = session.store.list_episodes(session.project_id)
            for ep in saved:
                if ep.draft.strip() or ep.final_text.strip():
                    flag = '최종본 있음' if ep.final_text.strip() else '미승인 초고'
                    self.episodes.addItem(f'{ep.episode}화 · {flag}', ep.episode)
            if not self.episodes.count():
                self.status.setText('읽을 수 있는 저장 원고가 없습니다. 집필실에서 먼저 저장하세요.')
                return
            numbers = [self.episodes.itemData(i)
                       for i in range(self.episodes.count())]
            selected = (previous_number if previous_number in numbers
                        else session.episode_number
                        if session.episode_number in numbers else numbers[0])
            self.episodes.setCurrentIndex(numbers.index(selected))
        except (OSError, ValueError):
            self.episodes.clear()
            self.status.setText('로컬 원고를 읽을 수 없습니다. DB 상태를 확인하세요.')
        finally:
            self.episodes.blockSignals(False)
            self._buttons()
        self._display()

    def _display(self, *_):
        self.body.clear()
        self._buttons()
        number = self.episodes.currentData()
        if number is None:
            return
        if self._epub_chapters is not None:
            if type(number) is not int or not 1 <= number <= len(self._epub_chapters):
                self.status.setText('EPUB 회차를 선택할 수 없습니다.')
                return
            chapter = self._epub_chapters[number - 1]
            self.body.setPlainText(chapter.text)
            self.status.setText(
                f'{number}화 · 검증된 로컬 EPUB3 · {len(chapter.text)}자 · '
                '읽기 전용 · 문학품질/출판 승인 아님')
            return
        try:
            session = self._session_getter()
            if (session is None or session.store is None
                    or (str(session.path), session.project_id) != self._project_key):
                self.status.setText('작품 선택이 변경되었습니다. 읽기 화면을 새로고침하세요.')
                return
            ep = session.store.get_episode(session.project_id, number)
            choice = self.version.currentData()
            if choice == 'final':
                prose = ep.final_text
                kind = '사용자 검수 최종본' if prose.strip() else '최종본 없음'
            elif choice == 'draft':
                prose = ep.draft
                kind = '미승인 초고' if prose.strip() else '초고 없음'
            else:
                prose = ep.final_text if ep.final_text.strip() else ep.draft
                kind = '사용자 검수 최종본' if ep.final_text.strip() else '미승인 초고'
            self.body.setPlainText(prose)
            self.status.setText(
                f'{number}화 · {kind} · {len(prose)}자 · 읽기 전용 · 출판/문학품질 승인과 별개')
        except (OSError, ValueError):
            self.body.clear()
            self.status.setText('선택한 저장 원고를 읽지 못했습니다. 다시 열어 주세요.')
