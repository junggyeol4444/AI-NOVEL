"""Stage 68 optional PySide6 UI for user-selected local task queue DB.

Purely local monitoring and cooperative controls: no worker is started, no
remote endpoint contacted, no generated draft is shown or approved here.
"""
from __future__ import annotations

from pathlib import Path
from contextlib import closing
import sqlite3

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QAbstractItemView,
)

from ai_novel_factory.local_task_queue import LocalTaskQueue, TaskQueueError
from ai_novel_factory.task_monitor import TaskMonitor


class TaskMonitorWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.monitor: TaskMonitor | None = None
        root = QVBoxLayout(self)
        root.addWidget(QLabel('기존 로컬 SQLite 작업큐를 선택해 상태를 확인합니다. 집필은 시작하지 않습니다.'))
        top = QHBoxLayout()
        self.open_button = QPushButton('작업큐 DB 열기')
        self.open_button.setObjectName('taskQueueOpen')
        self.path_label = QLabel('선택된 작업큐 없음')
        top.addWidget(self.open_button)
        top.addWidget(self.path_label, stretch=1)
        root.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName('taskProgressTable')
        self.table.setHorizontalHeaderLabels(('작업 ID', '작품 ID', '회차', '상태', '진행률', '단계'))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)
        self.progress = QProgressBar()
        self.progress.setObjectName('taskProgressBar')
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.refresh_button = QPushButton('새로고침')
        self.pause_button = QPushButton('일시정지 요청')
        self.resume_button = QPushButton('재개 요청')
        self.cancel_button = QPushButton('취소 요청')
        for button, name in ((self.refresh_button, 'taskRefresh'),
                             (self.pause_button, 'taskPause'),
                             (self.resume_button, 'taskResume'),
                             (self.cancel_button, 'taskCancel')):
            button.setObjectName(name)
            buttons.addWidget(button)
        root.addLayout(buttons)
        self.status = QLabel('실행 중인 작업은 다음 안전 지점에서 일시정지·취소 요청을 처리합니다.')
        self.status.setObjectName('taskMonitorStatus')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.open_button.clicked.connect(self._choose_db)
        self.refresh_button.clicked.connect(self.refresh)
        self.pause_button.clicked.connect(lambda: self._control('pause'))
        self.resume_button.clicked.connect(lambda: self._control('resume'))
        self.cancel_button.clicked.connect(lambda: self._control('cancel'))
        self.table.itemSelectionChanged.connect(self._selected_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self._selected_changed()

    def _choose_db(self):
        path, _ = QFileDialog.getOpenFileName(self, '기존 로컬 작업큐 선택', '',
                                              'SQLite database (*.sqlite3 *.db);;All files (*)')
        if path:
            self.open_database(path)

    def open_database(self, path: str):
        """Explicit read/write file open; do not turn an unrelated file into a DB."""
        try:
            p = Path(path)
            if not p.is_file() or p.is_symlink():
                raise TaskQueueError('existing regular database file required')
            with closing(sqlite3.connect(p.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                              "AND name='local_tasks'").fetchone() is None:
                    raise TaskQueueError('not a local task queue database')
            queue = LocalTaskQueue(p, recover_running=False)
            self.monitor = TaskMonitor(queue)
            self.path_label.setText(p.name)
            self.timer.start()
            self.refresh()
        except (sqlite3.Error, TaskQueueError, OSError) as exc:
            self.status.setText('작업큐를 열지 못했습니다. 파일 형식을 확인하세요.')
            self.timer.stop()
            self.monitor = None
            self._selected_changed()

    def _current_id(self) -> str | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.text() if item else None

    def refresh(self):
        if self.monitor is None:
            return
        selected = self._current_id()
        try:
            records = self.monitor.list_tasks()
        except (sqlite3.Error, TaskQueueError):
            self.status.setText('작업큐 상태를 읽지 못했습니다.')
            return
        self.table.blockSignals(True)
        self.table.setRowCount(len(records))
        for row, r in enumerate(records):
            for col, value in enumerate((r.task_id, r.project_id, str(r.episode_number),
                                         r.status, f'{r.progress}%', r.stage)):
                self.table.setItem(row, col, QTableWidgetItem(value))
        if selected is not None:
            for row, r in enumerate(records):
                if r.task_id == selected:
                    self.table.selectRow(row)
                    break
        self.table.blockSignals(False)
        self._selected_changed()

    def _selected_changed(self):
        rec = self.monitor.get(self._current_id()) if self.monitor and self._current_id() else None
        self.progress.setValue(rec.progress if rec else 0)
        self.pause_button.setEnabled(bool(rec and rec.status in ('QUEUED', 'RUNNING')))
        self.resume_button.setEnabled(bool(rec and rec.status in ('PAUSED', 'PAUSE_REQUESTED')))
        self.cancel_button.setEnabled(bool(rec and rec.status in
                                           ('QUEUED', 'RUNNING', 'PAUSED', 'PAUSE_REQUESTED')))
        self.refresh_button.setEnabled(self.monitor is not None)

    def _control(self, action: str):
        if self.monitor is None or self._current_id() is None:
            return
        if action == 'cancel':
            answer = QMessageBox.question(self, '작업 취소 요청',
                                           '작업 취소를 요청하시겠습니까? 이미 생성한 원고를 확정하지 않습니다.',
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                           QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            {'pause': self.monitor.request_pause,
             'resume': self.monitor.request_resume,
             'cancel': self.monitor.request_cancel}[action](self._current_id())
            self.status.setText('작업 제어 요청을 기록했습니다. 실행 중이면 작업자의 협력이 필요합니다.')
        except (TaskQueueError, sqlite3.Error):
            self.status.setText('작업 상태가 변경됐거나 제어 요청을 처리할 수 없습니다.')
        self.refresh()
