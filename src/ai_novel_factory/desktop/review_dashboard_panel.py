"""Project-scoped desktop dashboard for 1~1000 saved chapter review status."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..episode_review_dashboard import build_review_dashboard, export_review_dashboard_csv
from .author_navigation_contract import _busy, _unsaved


class ReviewDashboardPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('장편 전체 회차 검수·참고작·원고 상태 (읽기 전용)', parent)
        self.authoring = authoring
        self._report = None
        self._identity = None
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('마지막 회차'))
        self.through = QSpinBox()
        self.through.setObjectName('novelReviewDashboardThrough')
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.valueChanged.connect(self.invalidate_export)
        top.addWidget(self.through)
        self.refresh_button = QPushButton('저장된 원고·검수·참고작 기록 새로고침')
        self.refresh_button.setObjectName('novelReviewDashboardRefresh')
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        root.addLayout(top)
        self.status = QLabel('기존 작품을 열어야 조회할 수 있습니다. 출판 승인과 별개입니다.')
        self.status.setWordWrap(True)
        self.status.setObjectName('novelReviewDashboardStatus')
        root.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName('novelReviewDashboardTable')
        self.table.setHorizontalHeaderLabels((
            '회차', '원고', 'QC 기록', '참고작 비교 범위', '작가 검수'))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(230)
        root.addWidget(self.table)
        self.open_button = QPushButton('선택한 회차를 기존 편집 화면에서 열기')
        self.open_button.setObjectName('novelReviewDashboardOpen')
        self.open_button.clicked.connect(self.open_selected)
        root.addWidget(self.open_button)
        self.export_consent = QCheckBox(
            '현재 1~N화 QC·참고작·작가 검수 상태만 새 로컬 CSV로 내보내는 이번 1회를 승인')
        self.export_consent.setObjectName('novelReviewDashboardExportConsent')
        root.addWidget(self.export_consent)
        self.export_button = QPushButton('수동 검수 작업표 CSV 새 파일 저장 (원고 본문 제외)')
        self.export_button.setObjectName('novelReviewDashboardExport')
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_current)
        root.addWidget(self.export_button)

    def invalidate_export(self, *_args):
        self._report = None
        self._identity = None
        self.export_consent.setChecked(False)
        self.export_button.setEnabled(False)

    def refresh(self):
        self.invalidate_export()
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('기존 작품 SQLite를 먼저 열어야 합니다.')
            self.table.setRowCount(0)
            return
        try:
            report = build_review_dashboard(
                session.store, str(session.project_id),
                through_episode=self.through.value())
        except (OSError, ValueError):
            self.status.setText('현재 작품의 회차 검수 현황을 읽을 수 없습니다.')
            self.table.setRowCount(0)
            return
        self._report = report
        self._identity = (str(session.path), str(session.project_id))
        self.export_button.setEnabled(True)
        self.status.setText(
            f'본문 누락 {report.missing_manuscripts}화 / 작가 검수 없음·과거 판정 '
            f'{report.unreviewed_or_stale}화 / 참고작 비교 누락·불완전 '
            f'{report.reference_not_examined}화 / QC 미완료 {report.qc_incomplete}화. '
            'QC 기록과 참고작 비교 범위는 문학 품질·저작권·출판 승인 아님.')
        self.table.setRowCount(len(report.chapters))
        for row, chapter in enumerate(report.chapters):
            values = (str(chapter.episode), chapter.manuscript, chapter.qc_state,
                      chapter.reference_scope, chapter.human_review)
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def open_selected(self):
        row = self.table.currentRow()
        if row < 0:
            self.status.setText('이동할 회차를 먼저 선택하세요.')
            return
        number_item = self.table.item(row, 0)
        if number_item is None:
            return
        number = int(number_item.text())
        selector = self.authoring.episodes
        index = selector.findData(number)
        if index < 0:
            self.status.setText('해당 회차는 저장되어 있지 않습니다. 자동 생성하지 않습니다.')
            return
        selector.setCurrentIndex(index)
        self.status.setText(f'{number}화를 기존 편집 화면에서 선택했습니다. 검수·출판 승인 아님.')

    def export_current(self):
        """별도 승인 후 현재 1~N화 읽기 전용 QC 근거만 로컬 새 파일로 기록."""
        report, identity = self._report, self._identity
        consent = self.export_consent.isChecked()
        self.export_consent.setChecked(False)
        if (not consent or report is None or identity is None
                or self.through.value() != report.through_episode):
            self.status.setText('현재 검수 현황 조회와 별도 내보내기 승인이 필요합니다.')
            return
        session = self.authoring.session
        if (session.store is None or session.path is None
                or session.project_id is None
                or (str(session.path), str(session.project_id)) != identity
                or _busy(self.authoring) or _unsaved(self.authoring)):
            self.invalidate_export()
            self.status.setText('작품·미저장 원고·집필 상태가 변경되어 새 조회가 필요합니다.')
            return
        folder = QFileDialog.getExistingDirectory(
            self, '새 검수 작업표를 저장할 기존 로컬 폴더 선택')
        if not folder:
            self.status.setText('내보내기를 취소했습니다. 기존 파일은 변경하지 않았습니다.')
            return
        try:
            receipt = export_review_dashboard_csv(
                session.store, identity[1], report, folder,
                explicit_author_export=True)
        except (ValueError, OSError):
            self.invalidate_export()
            self.status.setText('저장 원고·QC·참고작·검수 상태가 변경됐거나 새 CSV를 저장하지 못했습니다.')
            return
        self.invalidate_export()
        self.status.setText(
            f'{receipt.chapter_count}화의 검수 작업표를 {receipt.file.name} 새 파일로 저장했습니다. '
            '원고·QC 원문·참고작은 포함하지 않았으며, 합격·출판 승인이 아닙니다.')
