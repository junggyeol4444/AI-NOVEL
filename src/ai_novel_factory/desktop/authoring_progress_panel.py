"""Author-initiated Windows GUI for offline episode progress."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from ai_novel_factory.authoring_progress_readonly import (
    ProgressReadError, load_author_progress, require_current_chapter,
)

class AuthoringProgressDialog(QDialog):
    def __init__(self, authoring, parent=None):
        super().__init__(parent or authoring)
        self.authoring = authoring
        self.snapshot = None
        self.setWindowTitle("장편 회차별 작업 현황 · 읽기 전용")
        self.resize(920, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("검수·저작권·출판 승인 아님. 실제 모델 실행 없음."))
        controls = QHBoxLayout()
        self.limit = QComboBox()
        for n in (30, 100, 250, 1000):
            self.limit.addItem(f"{n}화까지", n)
        self.limit.setCurrentIndex(2)
        controls.addWidget(self.limit)
        refresh = QPushButton("현황 다시 조회")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        open_button = QPushButton("선택한 저장 회차를 기존 편집기에서 열기")
        open_button.clicked.connect(self.open_episode)
        controls.addWidget(open_button)
        layout.addLayout(controls)
        self.summary = QLabel("조회 대기")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels((
            "회차", "저장 버전", "초고", "최종본",
            "현재 검사 기록 수", "작가 작업 / 검수기록"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.refresh()

    def _project(self):
        session = self.authoring.session
        if session.path is None or session.project_id is None:
            raise ProgressReadError("먼저 기존 작품을 열어 주세요.")
        if self.authoring.auto_panel.is_running() or self.authoring.is_generating():
            raise ProgressReadError("로컬 집필이 끝난 뒤 회차 현황을 선택하세요.")
        return session

    def refresh(self):
        self.snapshot = None
        self.table.setRowCount(0)
        try:
            session = self._project()
            report = load_author_progress(session.path, str(session.project_id),
                                          through_episode=self.limit.currentData())
            self.snapshot = (str(session.path), str(session.project_id), report)
            self.table.setRowCount(len(report.chapters))
            for index, row in enumerate(report.chapters):
                values = (str(row.number), str(row.revision or "-"),
                          "있음" if row.has_draft else "없음",
                          "있음" if row.has_final else "없음",
                          str(row.current_check_records),
                          f"{row.next_action} / {row.review_receipt}")
                for col, value in enumerate(values):
                    self.table.setItem(index, col, QTableWidgetItem(value))
            self.summary.setText(
                f"{report.through_episode}화 범위 · 저장 {report.saved_count} · "
                f"초고 {report.draft_count} · 최종본 {report.final_count} · "
                f"미작성 {report.missing_count} · 검수 기록 존재(미확인) "
                f"{report.review_receipt_count}")
        except (ProgressReadError, ValueError):
            self.summary.setText("읽기 전용 현황 조회 불가: 기존 작품과 로컬 DB를 확인하세요.")

    def open_episode(self):
        if self.snapshot is None or self.table.currentRow() < 0:
            self.summary.setText("먼저 현황과 저장 회차를 선택하세요.")
            return
        path, project_id, report = self.snapshot
        chapter = report.chapters[self.table.currentRow()]
        try:
            session = self._project()
            if str(session.path) != path or str(session.project_id) != project_id:
                raise ProgressReadError("작품이 변경됐습니다.")
            require_current_chapter(session.path, project_id, chapter)
            session.select_episode(chapter.number)
            self.authoring._sync()
            self.accept()
        except (ProgressReadError, ValueError):
            self.snapshot = None
            self.summary.setText("작품·회차·원고가 변경됐습니다. 다시 조회하세요.")
