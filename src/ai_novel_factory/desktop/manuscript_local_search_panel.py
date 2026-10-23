"""Explicit offline search of saved author manuscript in current SQLite."""
from __future__ import annotations
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QFormLayout, QLabel,
    QLineEdit, QComboBox, QSpinBox, QPushButton, QTableWidget,
    QTableWidgetItem, QPlainTextEdit)
from ai_novel_factory.manuscript_local_search import (
    search_saved_manuscript, revalidate_manuscript_hit)


class ManuscriptLocalSearchPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('현재 작품 저장 원고 오프라인 검색', parent)
        self.authoring = authoring
        self._report = None
        self._signature = None
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
        self.go = QPushButton('선택 결과를 기존 편집 화면에서 열기')
        self.go.setObjectName('manuscriptLocalSearchOpenEpisode')
        root.addWidget(self.go)
        self.status = QLabel('검색 미실행 · QC/출판 승인 아님')
        root.addWidget(self.status)
        self.search_button.clicked.connect(self.search)
        self.table.itemSelectionChanged.connect(self.preview_selected)
        self.go.clicked.connect(self.open_episode)
        self.query.textChanged.connect(self.invalidate)
        self.source.currentIndexChanged.connect(self.invalidate)
        self.end.valueChanged.connect(self.invalidate)

    def _signature_now(self):
        session = self.authoring.session
        return (str(session.path), str(session.project_id))

    def invalidate(self, *_args):
        self._report = None
        self._signature = None
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
        self.preview.clear()
        hit = self._selected_hit()
        if hit is not None:
            self.preview.setPlainText(hit.excerpt)

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
