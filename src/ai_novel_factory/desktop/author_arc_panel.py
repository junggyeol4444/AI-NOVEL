"""PySide6 desktop: author-only, append-only story-arc planning."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QSpinBox, QPushButton, QCheckBox, QFileDialog,
    QListWidget)
from ..author_arc_ledger import (AuthorArcError, add_author_arc,
                                 read_author_arcs, withdraw_author_arc)

class AuthorArcPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 직접 장편 아크 계획 · 로컬 전용', parent)
        self.authoring = authoring
        self._folder = None
        self._bound = None
        form = QFormLayout()
        root = QVBoxLayout(self)
        root.addLayout(form)
        self.folder_label = QLabel('로컬 계획 폴더 미선택')
        self.folder_label.setWordWrap(True)
        choose = QPushButton('기존 아크 기록 폴더 직접 선택')
        choose.clicked.connect(self.choose_folder)
        form.addRow(choose)
        form.addRow(self.folder_label)
        self.start = QSpinBox(); self.start.setRange(1, 1000)
        self.end = QSpinBox(); self.end.setRange(1, 1000); self.end.setValue(30)
        form.addRow('시작 회차', self.start); form.addRow('종료 회차', self.end)
        self.title_input = QLineEdit()
        form.addRow('아크 제목', self.title_input)
        self.fields = {}
        for key, label in [('objective','장편 목표'),('conflict','주요 갈등'),
                           ('foreshadow','복선 계획'),('resolution','해소 계획')]:
            edit=QPlainTextEdit();edit.setMaximumHeight(66)
            self.fields[key]=edit;form.addRow(label,edit)
        self.preview = QListWidget();self.preview.setMaximumHeight(130)
        root.addWidget(self.preview)
        self.save_consent = QCheckBox('위 내용을 이번 한 번 새 로컬 기록으로 저장하는 데 동의')
        self.withdraw_consent = QCheckBox('선택한 아크 기록을 이번 한 번 철회하는 데 동의')
        root.addWidget(self.save_consent);root.addWidget(self.withdraw_consent)
        self.batch_approval = QCheckBox('이번 AI 집필 한 번에만 현재 작가 아크 계획을 사용합니다')
        root.addWidget(self.batch_approval)
        self._batch_project = None
        self._batch_stamp = None
        self.batch_approval.toggled.connect(self._bind_batch)
        save = QPushButton('새 아크 기록 저장');save.clicked.connect(self.save_arc)
        remove = QPushButton('선택한 아크 철회');remove.clicked.connect(self.withdraw_arc)
        refresh=QPushButton('현재 아크 목록 읽기');refresh.clicked.connect(self.refresh)
        root.addWidget(save);root.addWidget(remove);root.addWidget(refresh)
        self.status=QLabel('저장·철회는 작가가 직접 누른 때에만 별도 JSON으로 기록합니다.')
        self.status.setWordWrap(True);root.addWidget(self.status)
        for obj in (self.start,self.end):obj.valueChanged.connect(self._revoke_save)
        self.title_input.textChanged.connect(self._revoke_save)
        for obj in self.fields.values():obj.textChanged.connect(self._revoke_save)

    def _revoke_save(self, *args):
        self.save_consent.setChecked(False)

    def invalidate(self):
        self.save_consent.setChecked(False);self.withdraw_consent.setChecked(False)
        self.batch_approval.setChecked(False)
        self.preview.clear();self._bound=None
        self.status.setText('작품이 변경되어 아크 승인과 목록을 초기화했습니다.')

    def _project(self):
        session=self.authoring.session
        db,pid=session.required()
        current=(str(session.path),str(pid))
        return db,str(pid),current

    def _bind_batch(self, enabled):
        self._batch_project = None
        self._batch_stamp = None
        if enabled:
            try:
                _, pid, bound = self._project()
                if self._folder is None:
                    raise AuthorArcError('기록 폴더 선택 필요')
                from ..author_arc_ledger import arc_ledger_fingerprint
                self._batch_project = bound
                self._batch_stamp = arc_ledger_fingerprint(self._folder)
            except (AuthorArcError, ValueError, OSError):
                self.batch_approval.setChecked(False)
                self.status.setText('작품·로컬 아크 기록 폴더를 먼저 확인하세요.')

    def consume_batch_folder(self) -> str | None:
        if not self.batch_approval.isChecked():
            return None
        try:
            _, _, bound = self._project()
            from ..author_arc_ledger import arc_ledger_fingerprint
            if (self._folder is None or self._batch_project != bound
                    or self._batch_stamp != arc_ledger_fingerprint(self._folder)):
                raise AuthorArcError('아크 기록이 변경되었습니다.')
            return str(self._folder)
        finally:
            self.batch_approval.setChecked(False)

    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'작가 아크 JSON 기록용 기존 로컬 폴더')
        if path:
            self._folder=Path(path)
            self.folder_label.setText('기존 로컬 폴더 선택됨 (원고 SQLite와 별도)')
            self.invalidate()

    def refresh(self):
        self.preview.clear();self.withdraw_consent.setChecked(False)
        try:
            _,pid,bound=self._project()
            if self._folder is None:raise AuthorArcError('폴더를 먼저 선택하세요.')
            arcs=read_author_arcs(self._folder,pid)
            for arc in arcs:
                status='철회' if arc.withdrawn else '작가 기록'
                self.preview.addItem(f'{arc.start}~{arc.end}화 · {arc.title} · {status}')
                self.preview.item(self.preview.count()-1).setData(256,arc.arc_id)
            self._bound=bound
            self.status.setText(f'작가 아크 기록 {len(arcs)}개 조회. 현재 품질 PASS·출판 승인 없음.')
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('현재 작품의 아크 기록을 읽을 수 없습니다.')

    def save_arc(self):
        approved=self.save_consent.isChecked();self.save_consent.setChecked(False)
        try:
            db,pid,_=self._project()
            if self._folder is None:raise AuthorArcError('기존 계획 폴더 선택 필요')
            add_author_arc(db,pid,folder=self._folder,start=self.start.value(),
                end=self.end.value(),title=self.title_input.text(),
                objective=self.fields['objective'].toPlainText(),
                conflict=self.fields['conflict'].toPlainText(),
                foreshadow=self.fields['foreshadow'].toPlainText(),
                resolution=self.fields['resolution'].toPlainText(),
                explicit_author_save=approved)
            self.batch_approval.setChecked(False)
            self.refresh()
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('아크를 저장하지 않았습니다. 회차 범위·승인·입력값을 확인하세요.')

    def withdraw_arc(self):
        approved=self.withdraw_consent.isChecked();self.withdraw_consent.setChecked(False)
        try:
            _,pid,bound=self._project()
            current=self.preview.currentItem()
            if not approved or current is None or self._bound!=bound:
                raise AuthorArcError('기록과 철회 승인을 다시 선택하세요.')
            withdraw_author_arc(self._folder,pid,current.data(256),explicit_author_withdraw=True)
            self.batch_approval.setChecked(False)
            self.refresh()
        except (AuthorArcError,OSError,ValueError):
            self.status.setText('아크 철회를 실행하지 않았습니다. 다시 확인하세요.')
