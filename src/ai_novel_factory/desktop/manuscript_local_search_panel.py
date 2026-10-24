"""Explicit offline search of saved author manuscript in current SQLite."""
from __future__ import annotations
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QFormLayout, QLabel,
    QLineEdit, QComboBox, QSpinBox, QPushButton, QTableWidget,
    QTableWidgetItem, QPlainTextEdit)
from ai_novel_factory.manuscript_local_search import (
    search_saved_manuscript, revalidate_manuscript_hit,
    read_saved_manuscript_exact_match)
from .author_navigation_contract import _busy, _unsaved, select_saved_episode


class ManuscriptLocalSearchPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('현재 작품 저장 원고 오프라인 검색', parent)
        self.authoring = authoring
        self._report = None
        self._signature = None
        self._exact = None
        root = QVBoxLayout(self)
        root.addWidget(QLabel('기존 작품 SQLite 읽기 전용 · 결과 화면에만 표시 · 원고/검수 상태 변경 없음'))
        form = QFormLayout()
        root.addLayout(form)
        self.query = QLineEdit()
        self.query.setObjectName('manuscriptLocalSearchQuery')
        form.addRow('검색어', self.query)
        self.source = QComboBox()
        for name, value in (('최종본','final_text'),('초고','draft'),('회차 플롯','plot'),('회차 요약','summary')):
            self.source.addItem(name, value)
        form.addRow('원고 종류', self.source)
        self.end = QSpinBox()
        self.end.setRange(1,1000)
        self.end.setValue(250)
        form.addRow('검색 마지막 회차', self.end)
        self.search_button = QPushButton('이 작품 SQLite 검색')
        self.search_button.setObjectName('manuscriptLocalSearchExecute')
        root.addWidget(self.search_button)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(('회차','버전','일치 위치'))
        self.table.setObjectName('manuscriptLocalSearchResults')
        root.addWidget(self.table)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(145)
        root.addWidget(self.preview)
        self.exact_button = QPushButton('선택 결과의 저장 원문·정확한 일치 위치 직접 열기')
        self.exact_button.setObjectName('manuscriptLocalSearchExactMatch')
        root.addWidget(self.exact_button)
        self.exact_text = QPlainTextEdit()
        self.exact_text.setReadOnly(True)
        self.exact_text.setMaximumHeight(260)
        self.exact_text.setObjectName('manuscriptLocalSearchExactText')
        root.addWidget(self.exact_text)
        self.editor_exact_button = QPushButton('확인한 일치 위치를 기존 원고 편집기에서 선택')
        self.editor_exact_button.setObjectName('manuscriptLocalSearchExactEditor')
        root.addWidget(self.editor_exact_button)
        self.go = QPushButton('선택 결과를 기존 편집 화면에서 열기')
        self.go.setObjectName('manuscriptLocalSearchOpenEpisode')
        root.addWidget(self.go)
        self.status = QLabel('검색 미실행 · QC/출판 승인 아님')
        root.addWidget(self.status)
        self.search_button.clicked.connect(self.search)
        self.table.itemSelectionChanged.connect(self.preview_selected)
        self.go.clicked.connect(self.open_episode)
        self.exact_button.clicked.connect(self.open_exact_match)
        self.editor_exact_button.clicked.connect(self.open_exact_editor)
        self.query.textChanged.connect(self.invalidate)
        self.source.currentIndexChanged.connect(self.invalidate)
        self.end.valueChanged.connect(self.invalidate)

    def _signature_now(self):
        session = self.authoring.session
        return (str(session.path), str(session.project_id))

    def invalidate(self, *_args):
        self._report = None
        self._signature = None
        self._exact = None
        self.exact_text.clear()
        self.table.setRowCount(0)
        self.preview.clear()
        self.status.setText('이전 검색 결과를 폐기했습니다. 직접 다시 검색하세요.')

    def search(self):
        self.invalidate()
        session = self.authoring.session
        if session.path is None or session.project_id is None:
            self.status.setText('먼저 기존 작품을 열어 주세요.')
            return
        try:
            report = search_saved_manuscript(
                session.path, session.project_id, self.query.text(),
                field_name=self.source.currentData(), through_episode=self.end.value())
        except (ValueError, OSError):
            self.status.setText('현재 작품 검색을 완료하지 못했습니다. 검색어/DB를 확인하세요.')
            return
        self._report = report
        self._signature = self._signature_now()
        self.table.setRowCount(len(report.hits))
        for i, hit in enumerate(report.hits):
            for j, value in enumerate((hit.episode, hit.revision, hit.column_start+1)):
                self.table.setItem(i, j, QTableWidgetItem(str(value)))
        self.status.setText(
            f'{report.checked_episodes}회차 조회 · {report.total_occurrences}개 일치 · '
            f'{len(report.hits)}개 화면 표시'
            + (' (표시 제한 200건)' if report.truncated else '')
            + ' · 원고 변경 없음')

    def _selected_hit(self):
        if self._report is None or self._signature != self._signature_now():
            return None
        row = self.table.currentRow()
        if not 0 <= row < len(self._report.hits):
            return None
        return self._report.hits[row]

    def preview_selected(self):
        self._exact = None
        self.exact_text.clear()
        self.preview.clear()
        hit = self._selected_hit()
        if hit is not None:
            self.preview.setPlainText(hit.excerpt)

    @staticmethod
    def _highlight_match(widget, text, start, end):
        """Python 문자열 인덱스를 Qt UTF-16 커서 위치로 변환한다."""
        begin = len(text[:start].encode('utf-16-le')) // 2
        finish = len(text[:end].encode('utf-16-le')) // 2
        cursor = widget.textCursor()
        cursor.setPosition(begin)
        cursor.setPosition(finish, QTextCursor.MoveMode.KeepAnchor)
        widget.setTextCursor(cursor)
        widget.ensureCursorVisible()

    def open_exact_match(self):
        """첫 검색·행 선택 이후 별도 클릭에서만 저장 원문을 표시한다."""
        self._exact = None
        self.exact_text.clear()
        hit = self._selected_hit()
        if hit is None or self._report is None:
            self.status.setText('현재 검색 결과에서 한 행을 직접 선택하세요.')
            return
        identity = self._signature
        session = self.authoring.session
        try:
            if _busy(self.authoring) or _unsaved(self.authoring):
                raise ValueError('미저장 원고·실행 중인 집필을 먼저 직접 정리하세요.')
            exact = read_saved_manuscript_exact_match(
                session.path, str(session.project_id), hit, self._report.query)
            if (identity != self._signature_now()
                    or not revalidate_manuscript_hit(
                        session.path, str(session.project_id), hit)):
                raise ValueError('원고·작품이 변경됐습니다.')
            self.exact_text.setPlainText(exact.text)
            if self.exact_text.toPlainText() != exact.text:
                raise ValueError('저장 원고를 정확히 표시할 수 없습니다.')
            self._highlight_match(
                self.exact_text, exact.text, exact.match_start, exact.match_end)
        except (ValueError, OSError, LookupError, UnicodeError):
            self._exact = None
            self.exact_text.clear()
            self.status.setText('원고·검색 위치가 변경됐거나 미저장 작업이 있습니다. 다시 검색하세요.')
            return
        self._exact = (hit, exact, identity)
        self.status.setText(
            f'{hit.episode}화 저장 {self.source.currentText()} 원문에서 '
            '검색어의 정확한 위치를 선택했습니다. 조회만 수행했습니다.')

    def open_exact_editor(self):
        """작가가 재확인한 위치만 기존 편집기로 이동·선택한다. 저장 없음."""
        prepared = self._exact
        if prepared is None:
            self.status.setText('먼저 별도 버튼으로 정확한 저장 원문 위치를 확인하세요.')
            return
        hit, exact, identity = prepared
        if hit != self._selected_hit() or identity != self._signature_now():
            self._exact = None
            self.status.setText('작품·검색 행이 변경됐습니다. 다시 검색하세요.')
            return
        if hit.field not in ('plot', 'draft', 'final_text'):
            self.status.setText('회차 요약은 읽기 전용 원문에서 확인하세요. 편집 필드가 없습니다.')
            return
        session = self.authoring.session
        try:
            if _busy(self.authoring) or _unsaved(self.authoring):
                raise ValueError('미저장 원고·실행 중인 집필이 있습니다.')
            if not revalidate_manuscript_hit(
                    session.path, str(session.project_id), hit):
                raise ValueError('저장 원고가 변경됐습니다.')
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=hit.episode)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
            widget = self.authoring.fields.get(hit.field)
            if (not isinstance(widget, QPlainTextEdit)
                    or widget.toPlainText() != exact.text):
                raise ValueError('편집기 원고와 조회 원문이 다릅니다.')
            self._highlight_match(
                widget, exact.text, exact.match_start, exact.match_end)
        except (ValueError, OSError, LookupError, UnicodeError):
            self._exact = None
            self.status.setText('원고·검색 위치·편집기 상태가 달라 이동을 완료하지 못했습니다.')
            return
        self._exact = None
        self.status.setText(
            f'{hit.episode}화 기존 편집기에서 검색 위치만 선택했습니다. '
            '원고 저장·검수·출판 승인 없음.')

    def open_episode(self):
        hit = self._selected_hit()
        if hit is None:
            self.status.setText('검색 결과가 없거나 작품이 변경되었습니다.')
            return
        session = self.authoring.session
        if not revalidate_manuscript_hit(session.path, session.project_id, hit):
            self.invalidate()
            self.status.setText('검색 후 원고가 변경되어 결과를 폐기했습니다.')
            return
        selector = self.authoring.episodes
        index = selector.findData(hit.episode)
        if index < 0:
            self.status.setText('해당 회차가 현재 작품 화면에 없습니다.')
            return
        selector.setCurrentIndex(index)
        self.status.setText(f'{hit.episode}화 편집 화면 선택 · 검색 결과는 품질 판단이 아닙니다.')
