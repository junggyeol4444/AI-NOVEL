"""Windows PySide6 author-only continuity facts and per-run AI opt-in."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ai_novel_factory.author_fact_ledger import (
    FACT_TYPES, add_author_fact, read_author_facts, retract_author_fact,
)


class AuthorFactPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 구조화 사실·연속성 기억 (로컬 전용)', parent)
        self.authoring = authoring
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        form.addRow('작가 선택 로컬 기록 폴더', self.folder)
        choose = QPushButton('기존 기록 폴더 선택')
        choose.clicked.connect(self._choose_folder)
        form.addRow(choose)
        self.kind = QComboBox()
        self.kind.addItems(sorted(FACT_TYPES))
        form.addRow('사실 종류', self.kind)
        self.source = QSpinBox()
        self.source.setRange(1, 1000)
        form.addRow('근거 최종본 회차', self.source)
        self.first = QSpinBox()
        self.first.setRange(1, 1000)
        form.addRow('적용 시작 회차', self.first)
        self.last = QSpinBox()
        self.last.setRange(1, 1000)
        self.last.setValue(1000)
        form.addRow('적용 마지막 회차', self.last)
        self.subject = QLineEdit()
        self.subject.setMaxLength(100)
        form.addRow('인물·사건·세계관 대상', self.subject)
        self.predicate = QLineEdit()
        self.predicate.setMaxLength(100)
        form.addRow('속성·관계·복선 식별자', self.predicate)
        self.value = QPlainTextEdit()
        self.value.setMaximumHeight(72)
        form.addRow('작가가 직접 입력한 사실', self.value)
        self.status = QLabel('저장 최종본에 근거한 작가 사실만 기록합니다. AI 검수 합격 아님.')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        add = QPushButton('현재 사실을 새 로컬 파일로 등록 (작가 직접 저장)')
        add.setObjectName('authorFactExplicitAdd')
        add.clicked.connect(self._add)
        root.addWidget(add)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['근거 회차', '분류', '대상', '상태'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(175)
        root.addWidget(self.table)
        refresh = QPushButton('현재 작품 구조화 사실 목록 조회')
        refresh.clicked.connect(self.refresh)
        root.addWidget(refresh)
        retract = QPushButton('선택 사실 철회 기록 (작가 직접 철회)')
        retract.setObjectName('authorFactExplicitRetract')
        retract.clicked.connect(self._retract)
        root.addWidget(retract)
        self.batch_approval = QCheckBox(
            '이번 AI 집필 1회에 한해 현재 폴더의 작가 사실 사용을 승인합니다')
        self.batch_approval.setObjectName('authorFactBatchOneShotConsent')
        root.addWidget(self.batch_approval)
        for field in (self.source, self.first, self.last):
            field.valueChanged.connect(lambda _v: self.batch_approval.setChecked(False))
        for field in (self.subject, self.predicate):
            field.textChanged.connect(lambda _v: self.batch_approval.setChecked(False))
        self.value.textChanged.connect(lambda: self.batch_approval.setChecked(False))

    def invalidate(self):
        self.batch_approval.setChecked(False)
        self.table.setRowCount(0)
        self.status.setText('작품 또는 입력이 변경되었습니다. 기록을 다시 조회하세요.')

    def _choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, '작가 사실 기록 로컬 폴더')
        if selected:
            self.folder.setText(selected)
            self.invalidate()

    def _session(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            raise ValueError('기존 작품 SQLite를 먼저 열어야 합니다.')
        if not self.folder.text():
            raise ValueError('작가 사실 기록 폴더를 직접 선택해야 합니다.')
        return session.store, str(session.project_id), Path(self.folder.text())

    def _add(self):
        try:
            store, project_id, folder = self._session()
            add_author_fact(store, project_id, folder=folder,
                            source_episode=self.source.value(),
                            valid_from=self.first.value(),
                            valid_until=self.last.value(),
                            kind=self.kind.currentText(),
                            subject=self.subject.text(),
                            predicate=self.predicate.text(),
                            value=self.value.toPlainText(),
                            explicit_author_save=True)
            self.batch_approval.setChecked(False)
            self.refresh()
            self.status.setText('작가 사실 1건을 새 로컬 파일로 등록했습니다. 자동 승인 아님.')
        except (ValueError, OSError):
            self.status.setText('사실 등록 보류: 작품·근거 회차·입력·폴더를 확인하세요.')

    def refresh(self):
        try:
            _, project_id, folder = self._session()
            facts = read_author_facts(folder, project_id)
            self.table.setRowCount(len(facts))
            for row, fact in enumerate(facts):
                values = (str(fact.source_episode), fact.kind, fact.subject,
                          '철회됨' if fact.retracted else '등록됨·원고 변경 시 재확인')
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, fact.fact_id)
                    self.table.setItem(row, col, item)
            self.status.setText(f'등록 사실 {len(facts)}건. 최신 원고 근거는 집필 시 다시 확인합니다.')
        except (ValueError, OSError):
            self.table.setRowCount(0)
            self.status.setText('구조화 사실 목록을 읽을 수 없습니다.')

    def _retract(self):
        try:
            store, project_id, folder = self._session()
            row = self.table.currentRow()
            if row < 0 or self.table.item(row, 0) is None:
                raise ValueError('철회할 사실을 선택하세요.')
            fact_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            retract_author_fact(folder, project_id, fact_id,
                                explicit_author_retract=True)
            self.batch_approval.setChecked(False)
            self.refresh()
            self.status.setText('선택 사실 철회 사건을 새 로컬 파일로 저장했습니다.')
        except (ValueError, OSError):
            self.status.setText('철회 보류: 선택 사실과 로컬 기록을 확인하세요.')

    def consume_batch_folder(self) -> str | None:
        """Never reuse approval for a later batch; called before worker launch."""
        if not self.batch_approval.isChecked():
            return None
        _, _, folder = self._session()
        self.batch_approval.setChecked(False)
        return str(folder)
