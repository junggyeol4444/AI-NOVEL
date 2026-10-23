"""Read-only local EPUB3-to-current-final comparison in the existing GUI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGroupBox, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.epub_reader_handoff import (
    EpubReaderHandoffError, preview_epub_reader_handoff,
    require_current_epub_reader_handoff,
)
from .author_batch_scope_bridge import _current_author_state, BatchScopeBridgeError
from .author_navigation_contract import select_saved_episode


class EpubSourceAlignmentPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('EPUB3 권별 본문 ↔ 현재 SQLite 최종본 비교 (읽기 전용)', parent)
        self.authoring = authoring
        self._paths = ()
        self._toc = ''
        self._lease = None
        self._project = None
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
        self.reader_button = QPushButton('현재 원고와 일치하는 EPUB3 전체 권을 기존 Reader로 열기')
        self.reader_button.setEnabled(False)
        self.reader_button.clicked.connect(self.open_checked_reader)
        root.addWidget(self.reader_button)
        self.mismatches = QComboBox()
        root.addWidget(self.mismatches)
        self.editor_button = QPushButton('선택한 불일치 회차를 기존 원고 편집기로 열기')
        self.editor_button.setEnabled(False)
        self.editor_button.clicked.connect(self.open_mismatched_episode)
        root.addWidget(self.editor_button)
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
        self._lease = None
        self._project = None
        self.reader_button.setEnabled(False)
        self.editor_button.setEnabled(False)
        self.mismatches.clear()
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
            checked_session, identity = _current_author_state(self.authoring)
            report, lease = preview_epub_reader_handoff(
                checked_session.store, identity[1],
                through_episode=self.through.value(),
                selected_files=self._paths, toc_manifest_file=self._toc)
        except (EpubReaderHandoffError, BatchScopeBridgeError, OSError, ValueError):
            self.status.setText('원고/EPUB3 변경 또는 누락으로 전체 권별 비교를 완료하지 못했습니다.')
            return
        self._lease, self._project = lease, identity
        self.reader_button.setEnabled(not lease.mismatched_episodes)
        for number in lease.mismatched_episodes:
            self.mismatches.addItem(f'{number}화 불일치 · 직접 검토 필요', number)
        self.editor_button.setEnabled(bool(lease.mismatched_episodes))
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

    def _require_current(self):
        if self._lease is None or self._project is None:
            raise EpubReaderHandoffError('먼저 현재 저장 원고와 EPUB3 전체 권을 대조하세요.')
        session, identity = _current_author_state(self.authoring)
        if identity != self._project:
            raise EpubReaderHandoffError('작품이 변경됐습니다. 다시 대조하세요.')
        require_current_epub_reader_handoff(self._lease, session.store, identity[1])
        return identity

    def open_checked_reader(self):
        """작가의 두 번째 클릭으로 일치하는 권만 기존 로컬 Reader에 인계."""
        try:
            identity = self._require_current()
            if self._lease.mismatched_episodes:
                raise EpubReaderHandoffError('불일치 회차를 먼저 직접 검토하세요.')
            hub = getattr(self.authoring, 'feature_workspace_hub', None)
            if hub is None or not hub.open_feature(
                    'private_volume_reader_panel', project_identity=identity):
                raise EpubReaderHandoffError('기존 EPUB3 Reader 화면을 열지 못했습니다.')
            panel = getattr(self.authoring, 'private_volume_reader_panel', None)
            if panel is None or not panel.load_selected_volumes(self._lease.selected_files):
                raise EpubReaderHandoffError('기존 EPUB3 Reader가 선택 권을 열지 못했습니다.')
        except (EpubReaderHandoffError, BatchScopeBridgeError, OSError, ValueError):
            self.invalidate()
            self.status.setText('원고·EPUB3·목차 또는 작품이 변경됐습니다. 다시 대조하세요.')
            return
        self.status.setText('일치 범위의 EPUB3 권을 로컬 Reader로 열었습니다. 실제 Reader 통합 검증·출판 승인은 아닙니다.')

    def open_mismatched_episode(self):
        """불일치 원고를 직접 고칠 수 있도록 기존 편집기로만 이동."""
        number = self.mismatches.currentData()
        try:
            identity = self._require_current()
            if number not in self._lease.mismatched_episodes:
                raise EpubReaderHandoffError('불일치 회차를 다시 선택하세요.')
            decision = select_saved_episode(
                self.authoring, project_identity=identity, episode=number)
            if not decision.allowed:
                self.status.setText(decision.message)
                return
        except (EpubReaderHandoffError, BatchScopeBridgeError, OSError, ValueError):
            self.invalidate()
            self.status.setText('불일치 원고 또는 EPUB3 파일이 변경됐습니다. 다시 대조하세요.')
            return
        self.status.setText(f'{number}화 기존 편집기로 이동했습니다. 저장·검수·출판은 자동 수행하지 않습니다.')
