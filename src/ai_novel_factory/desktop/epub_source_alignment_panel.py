"""Read-only local EPUB3-to-current-final comparison in the existing GUI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.epub_source_alignment import (
    EpubSourceAlignmentError, compare_private_epub_to_saved_finals,
)


class EpubSourceAlignmentPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('EPUB3 권별 본문 ↔ 현재 SQLite 최종본 비교 (읽기 전용)', parent)
        self.authoring = authoring
        self._paths = ()
        self._toc = ''
        root = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(250)
        self.through.valueChanged.connect(self.invalidate)
        root.addWidget(QLabel('비교할 현재 최종본 마지막 회차 (1~1000화)'))
        root.addWidget(self.through)
        choose = QPushButton('현재 분할 계획의 모든 기존 EPUB3 권 순서대로 선택')
        choose.setObjectName('epubSourceAlignmentSelect')
        choose.clicked.connect(self.choose_volumes)
        root.addWidget(choose)
        toc = QPushButton('작가 목차 JSON 직접 선택 (없으면 기본 회차 제목)')
        toc.clicked.connect(self.choose_toc)
        root.addWidget(toc)
        compare = QPushButton('EPUB3 권별 원고와 현재 SQLite 최종본 읽기 전용 대조')
        compare.setObjectName('epubSourceAlignmentCompare')
        compare.clicked.connect(self.compare)
        root.addWidget(compare)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ['권/회차 범위', '본문 불일치', '목차 불일치', '검사 범위 상태'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(260)
        root.addWidget(self.table)
        self.status = QLabel('기존 EPUB3 권 미선택. 출판/품질/실제 Reader 합격 판정 아님.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def invalidate(self, *_args):
        self.table.setRowCount(0)
        self.status.setText('작품·범위·파일 선택이 변경되었습니다. 다시 비교하세요.')

    def choose_volumes(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, '권 순서대로 기존 EPUB3 모두 선택', '', 'EPUB3 (*.epub)')
        if paths:
            self._paths = tuple(paths)
            self.invalidate()
            self.status.setText(f'기존 EPUB3 {len(paths)}권 선택. 모든 권을 선택했는지 확인하세요.')

    def choose_toc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '기존 작가 목차 JSON 선택', '', 'JSON (*.json)')
        if path:
            self._toc = path
            self.invalidate()
            self.status.setText('작가 목차 JSON 선택. 다시 비교해야 합니다.')

    def compare(self):
        self.invalidate()
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('기존 작품을 먼저 열어야 합니다.')
            return
        if not self._paths:
            self.status.setText('기존 EPUB3 권들을 직접 선택하세요.')
            return
        try:
            report = compare_private_epub_to_saved_finals(
                session.store, str(session.project_id),
                through_episode=self.through.value(),
                selected_volume_files=self._paths,
                toc_manifest_file=self._toc or None)
        except (EpubSourceAlignmentError, OSError, ValueError):
            self.status.setText('원고/EPUB3 변경 또는 누락으로 전체 권별 비교를 완료하지 못했습니다.')
            return
        self.table.setRowCount(len(report.volumes))
        for row_index, item in enumerate(report.volumes):
            cells = (f'{item.volume_index}권 {item.first_episode}~{item.last_episode}화',
                     f'{len(item.mismatched_text)}화',
                     f'{len(item.mismatched_title)}화', item.status)
            for col, value in enumerate(cells):
                self.table.setItem(row_index, col, QTableWidgetItem(value))
        self.status.setText(
            f'{report.through_episode}화 / {len(report.volumes)}권 / {report.status}. '
            '본문과 목차의 현재 저장본 일치 범위만 확인하며, '
            '실제 Windows EPUB Reader·품질·출판 승인은 별도입니다.')
