"""Existing PySide6 authoring GUI: explicit, background final-reference audit.

Two separate user clicks: run a full local scan; optionally record one
scoped QC result for a still-current final manuscript. No automatic PASS.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QLabel, QPushButton, QSpinBox, QVBoxLayout,
)

from ..final_reference_audit import (
    FinalReferenceAuditError, audit_saved_final_references,
    save_explicit_final_reference_qc, require_current_final_reference_audit,
)
from ..reference_intake_plan import ReferenceIntakeError, require_current_intake
from ..reference_batch_context import ReferenceBatchError
from .reference_profile_browser import default_local_catalog_path
from .author_navigation_contract import select_saved_episode


class FinalReferenceAuditWorker(QThread):
    progress_changed = Signal(int)
    audit_ready = Signal(object, object)
    audit_failed = Signal(str)

    def __init__(self, db_path, project_id, selected_paths, through, parent=None):
        super().__init__(parent)
        self.db_path = str(db_path)
        self.project_id = str(project_id)
        self.selected_paths = tuple(selected_paths)
        self.through = through

    def run(self):
        try:
            report, intake = audit_saved_final_references(
                self.db_path, self.project_id,
                selected_paths=self.selected_paths,
                catalog_path=default_local_catalog_path(),
                through_episode=self.through,
                progress=self.progress_changed.emit)
        except (FinalReferenceAuditError, ReferenceIntakeError,
                ReferenceBatchError, OSError, ValueError):
            self.audit_failed.emit('선택 참고작 또는 최종 원고 전체 검사를 완료하지 못했습니다.')
            return
        self.audit_ready.emit(report, intake)


class FinalReferenceAuditPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('저장된 최종본 · 참고작 전수 비교 (수동 실행)', parent)
        self.authoring = authoring
        self._worker = None
        self._report = None
        self._intake = None
        self._selection = ()
        self._project = None
        layout = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        self.through.setObjectName('finalReferenceThrough')
        layout.addWidget(self.through)
        self.scan_consent = QCheckBox(
            '이번 한 번만 선택 참고작 원문을 로컬 메모리에서 읽어 저장 최종본 전체와 비교')
        layout.addWidget(self.scan_consent)
        self.scan = QPushButton('선택 참고작 전수 · 최종본 1화부터 비교')
        self.scan.setObjectName('finalReferenceRun')
        self.scan.clicked.connect(self.run_scan)
        layout.addWidget(self.scan)
        self.chapter = QComboBox()
        self.chapter.setObjectName('finalReferenceEpisode')
        layout.addWidget(self.chapter)
        self.open_review = QPushButton('선택 회차를 기존 원고 편집기로 이동 (별도 직접 클릭)')
        self.open_review.setObjectName('finalReferenceOpenReview')
        self.open_review.setEnabled(False)
        self.open_review.clicked.connect(self.open_selected_review)
        layout.addWidget(self.open_review)
        self.record_consent = QCheckBox(
            '선택한 한 회차의 현재 검사 범위만 SQLite QC에 WARN/FAIL로 기록 (PASS 아님)')
        layout.addWidget(self.record_consent)
        self.record = QPushButton('선택 회차 검사 기록 수동 저장')
        self.record.setObjectName('finalReferenceRecord')
        self.record.clicked.connect(self.record_selected)
        layout.addWidget(self.record)
        self.status = QLabel('검사 전 NOT_RUN. 최종본·참고작 원문은 화면/로그에 표시하지 않습니다.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.through.valueChanged.connect(self.invalidate)

    def invalidate(self, *_args):
        self._report = None
        self._intake = None
        self._selection = ()
        self._project = None
        self.scan_consent.setChecked(False)
        self.record_consent.setChecked(False)
        self.chapter.clear()
        self.open_review.setEnabled(False)
        self.status.setText('작품·회차·참고작 변경 시 검사 결과는 재사용할 수 없습니다.')

    def run_scan(self):
        if self._worker is not None and self._worker.isRunning():
            return
        session = self.authoring.session
        selected = tuple(self.authoring.auto_panel.reference_paths)
        if (not self.scan_consent.isChecked() or session.path is None
                or session.project_id is None or session.store is None
                or not selected or self.authoring.auto_panel.is_running()
                or self.authoring.is_generating()):
            self.status.setText('작품·참고작 선택 및 이번 로컬 전수 검사 승인이 필요합니다.')
            return
        self.invalidate()
        self.scan.setEnabled(False)
        self._project = (str(session.path), str(session.project_id))
        self._selection = selected
        self._worker = FinalReferenceAuditWorker(
            session.path, session.project_id, selected, self.through.value(), self)
        self._worker.progress_changed.connect(self._progress)
        self._worker.audit_ready.connect(self._complete)
        self._worker.audit_failed.connect(self._failed)
        self._worker.finished.connect(lambda: self.scan.setEnabled(True))
        self._worker.start()

    def _progress(self, number):
        self.status.setText(f'{number}/{self.through.value()}화 로컬 비교 중 · 합격 아님')

    def _complete(self, report, intake):
        session = self.authoring.session
        if (self._project != (str(session.path), str(session.project_id))
                or tuple(self.authoring.auto_panel.reference_paths) != self._selection):
            self.invalidate()
            return
        self._report, self._intake = report, intake
        self.chapter.clear()
        for row in report.results:
            self.chapter.addItem(f'{row.episode}화 · {row.status}', row.episode)
        self.open_review.setEnabled(any(
            row.status != 'MISSING_FINAL' for row in report.results))
        self.status.setText(
            f'{report.through_episode}화 중 최종본 누락 {len(report.missing)}화 / '
            f'위험 표시 {len(report.flagged)}화 / 참고작 {report.selected_count}개 비교. '
            '문장·구조 일부 범위만 확인. PASS·출판 승인 아님.')

    def _failed(self, message):
        self.invalidate()
        self.status.setText(message)


    def open_selected_review(self):
        """전체 검사와 별도의 작가 클릭. 저장된 원고 편집기로만 이동한다."""
        report, intake = self._report, self._intake
        project, selection = self._project, self._selection
        number = self.chapter.currentData()
        through = self.through.value()
        self.invalidate()  # 결과·일회 동의 재사용 금지
        if (report is None or intake is None or project is None
                or type(number) is not int or not 1 <= number <= through
                or through != report.through_episode):
            self.status.setText('전수 검사 후 저장된 회차를 직접 선택하세요.')
            return
        row = next((item for item in report.results if item.episode == number), None)
        if row is None or row.status == 'MISSING_FINAL':
            self.status.setText('최종본이 저장되지 않은 회차는 자동 생성하거나 이동하지 않습니다.')
            return
        session = self.authoring.session
        if ((str(session.path), str(session.project_id)) != project
                or session.store is None
                or tuple(self.authoring.auto_panel.reference_paths) != selection):
            self.status.setText('작품·선택 참고작이 변경됐습니다. 다시 직접 검사하세요.')
            return
        try:
            require_current_final_reference_audit(
                report, intake, database_path=session.path,
                project_id=project[1], selected_paths=selection,
                through_episode=through)
            decision = select_saved_episode(
                self.authoring, project_identity=project, episode=number)
        except (FinalReferenceAuditError, ReferenceIntakeError,
                ReferenceBatchError, OSError, ValueError, LookupError):
            self.status.setText('원고·참고작이 변경되어 이전 결과를 폐기했습니다. 다시 검사하세요.')
            return
        self.status.setText(
            decision.message + ' 수동 검토용 이동이며 QC PASS·출판 승인과 무관합니다.')

    def record_selected(self):
        report, intake = self._report, self._intake
        if report is None or intake is None or not self.record_consent.isChecked():
            self.status.setText('현재 회차 검사 결과와 별도 QC 기록 승인이 필요합니다.')
            return
        self.record_consent.setChecked(False)
        session = self.authoring.session
        if (self._project != (str(session.path), str(session.project_id))
                or tuple(self.authoring.auto_panel.reference_paths) != self._selection
                or session.store is None):
            self.invalidate()
            return
        number = self.chapter.currentData()
        row = next((r for r in report.results if r.episode == number), None)
        if row is None:
            self.status.setText('검사된 회차를 선택해야 합니다.')
            return
        try:
            require_current_intake(intake, self._selection)
            saved = save_explicit_final_reference_qc(
                session.store, report.project_id, row,
                intake=intake, selected_paths=self._selection,
                explicit_author_record=True)
        except (FinalReferenceAuditError, ReferenceIntakeError,
                ReferenceBatchError, OSError, ValueError):
            self.invalidate()
            self.status.setText('원고·참고작이 변경되었거나 기록 실패. 새로 비교하세요.')
            return
        self.invalidate()
        self.status.setText(
            f'{number}화 현재 검사 범위 {saved.outcome} 기록. '
            '의미·복선·문학 품질·저작권·출판 합격을 의미하지 않습니다.')
