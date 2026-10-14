"""Stage 90 optional PySide6 monitoring: reads a user-selected local queue only.

No model, queue dispatch, publisher adapter or API call is started by this tab.
Costs are explicitly reported/estimated metadata, never silently inferred.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ai_novel_factory.operations_monitor import OperationsReader, OperationsError


def _table(headers: tuple[str, ...], name: str) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setObjectName(name)
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
    table.setRowCount(len(rows))
    for index, values in enumerate(rows):
        for col, value in enumerate(values):
            table.setItem(index, col, QTableWidgetItem(value))


def _cost_label(kind: str, amount: int | None, currency: str | None) -> str:
    if kind == 'UNKNOWN':
        return '미확인'
    if amount is None or currency is None:
        return '미확인'
    if currency == 'USD':
        value = f'{amount / 100:.2f} USD'
    else:
        value = f'{amount:,} KRW'
    return f'{value} ({"추정" if kind == "ESTIMATED" else "보고값"})'


class OperationsMonitorWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.reader: OperationsReader | None = None
        root = QVBoxLayout(self)
        intro = QLabel('선택한 로컬 SQLite 작업큐의 실행·오류·비용 기록입니다. '
                       '미보고 비용은 미확인으로 표시하며 작업을 실행하지 않습니다.')
        intro.setWordWrap(True)
        root.addWidget(intro)
        controls = QHBoxLayout()
        self.open_button = QPushButton('기존 작업큐 DB 열기')
        self.open_button.setObjectName('operationsDbOpen')
        self.path_label = QLabel('선택된 DB 없음')
        self.project_filter = QLineEdit()
        self.project_filter.setObjectName('operationsProjectFilter')
        self.project_filter.setPlaceholderText('작품 ID (공란: 전체)')
        self.refresh_button = QPushButton('새로고침')
        self.refresh_button.setObjectName('operationsRefresh')
        controls.addWidget(self.open_button)
        controls.addWidget(self.path_label)
        controls.addWidget(self.project_filter)
        controls.addWidget(self.refresh_button)
        root.addLayout(controls)
        self.summary_label = QLabel('비용 미확인 · 실행 기록 없음')
        self.summary_label.setObjectName('operationsSummary')
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)
        root.addWidget(QLabel('작업 상태 (최근 200개, 현재 상태 기준)'))
        self.jobs_table = _table(('작업 ID','작품','회차','상태','시도','진행','단계','오류 코드'),
                                 'operationsJobsTable')
        root.addWidget(self.jobs_table)
        root.addWidget(QLabel('실행/오류/비용 이벤트 (최근 200개, 명시적 기록만)'))
        self.events_table = _table(('UTC','작업 ID','종류','오류 코드','소요 ms','입력 토큰',
                                   '출력 토큰','비용'), 'operationsEventsTable')
        root.addWidget(self.events_table)
        root.addWidget(QLabel('예약 실행 이력 (최근 200개, 등록된 경우)'))
        self.runs_table = _table(('예약 실행 ID','작업 ID','예약 UTC','상태','시도','오류 코드'),
                                 'operationsScheduleTable')
        root.addWidget(self.runs_table)
        self.status = QLabel('읽기 전용 화면 · 원고/프롬프트/비밀정보 표시 안 함')
        self.status.setObjectName('operationsStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.open_button.clicked.connect(self._choose_database)
        self.refresh_button.clicked.connect(self.refresh)
        self.project_filter.returnPressed.connect(self.refresh)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)

    def _choose_database(self):
        path, _ = QFileDialog.getOpenFileName(self, '기존 로컬 작업큐', '',
                                              'SQLite database (*.db *.sqlite *.sqlite3);;All files (*)')
        if path:
            self.open_database(path)

    def open_database(self, path: str) -> bool:
        try:
            reader = OperationsReader(path)
        except (OperationsError, OSError):
            self.reader = None
            self.timer.stop()
            self._clear()
            self.path_label.setText('선택된 DB 없음')
            self.status.setText('기존 작업큐 DB를 확인할 수 없습니다. 데이터는 변경되지 않았습니다.')
            return False
        self.reader = reader
        self.path_label.setText(Path(path).name)
        self.refresh()
        if self.reader is not None:
            self.timer.start()
        return self.reader is not None

    def _clear(self):
        for table in (self.jobs_table, self.events_table, self.runs_table):
            table.setRowCount(0)
        self.summary_label.setText('비용 미확인 · 실행 기록 없음')

    def refresh(self):
        if self.reader is None:
            return
        project = self.project_filter.text().strip() or None
        try:
            jobs = self.reader.list_jobs(project_id=project)
            events = self.reader.list_events(project_id=project)
            runs = self.reader.list_scheduled_runs(project_id=project)
            totals = self.reader.summary(project_id=project)
        except (OperationsError, OSError):
            self._clear()
            self.status.setText('조회 불가: 작품 ID 또는 로컬 DB를 확인하세요.')
            return
        _fill(self.jobs_table, [
            (j.task_id,j.project_id,str(j.episode_number),j.status,str(j.attempts),
             f'{j.progress}%',j.stage,j.error_code or '-') for j in jobs])
        _fill(self.events_table, [
            (e.recorded_utc,e.task_id,e.event,e.error_code or '-',
             '-' if e.duration_ms is None else str(e.duration_ms),
             '-' if e.input_tokens is None else str(e.input_tokens),
             '-' if e.output_tokens is None else str(e.output_tokens),
             _cost_label(e.cost_kind,e.cost_minor,e.currency)) for e in events])
        _fill(self.runs_table, [
            (r.run_id,r.task_id or '-',r.due_utc,r.status,str(r.attempts),
             r.error_code or '-') for r in runs])
        def sum_text(values):
            return ', '.join(_cost_label('REPORTED',amount,currency)
                             for currency, amount in values) if values else '없음'
        estimate = ', '.join(_cost_label('ESTIMATED',amount,currency)
                             for currency, amount in totals.estimated_minor_by_currency) or '없음'
        self.summary_label.setText(
            f'작업 {totals.task_count}건 · 실패/중단 {totals.failed_tasks}건 · '
            f'이벤트 {totals.event_count}건(오류 {totals.error_events}건) · '
            f'비용 미확인 {totals.unknown_cost_events}건 · '
            f'보고 비용 {sum_text(totals.reported_minor_by_currency)} · 추정 비용 {estimate}')
        self.status.setText('로컬 읽기 전용 · 집필/원고 확정/출판 실행 없음 · '
                            '비용은 사용자/호출자 제공값이며 결제 내역과 다를 수 있음')
