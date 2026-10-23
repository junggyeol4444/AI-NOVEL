"""Author-only local spelling and character voice rule editor for Windows GUI."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QPushButton,
    QCheckBox, QFileDialog,
)
from ..author_language_ledger import (
    AuthorLanguageError, add_author_language_rule, read_author_language_rules,
    withdraw_author_language_rule, language_ledger_fingerprint,
)


class AuthorLanguagePanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('작가 직접 고유명사 표기·인물 말투 규칙', parent)
        self.authoring = authoring
        self.folder: Path | None = None
        self._bound = None
        self._batch_bound = None
        self._batch_stamp = None
        layout = QVBoxLayout(self)
        self.notice = QLabel('작가 규칙은 별도 로컬 JSON 사건 파일만 기록합니다. 원고/SQLite 자동 수정 없음.')
        self.notice.setWordWrap(True); layout.addWidget(self.notice)
        form = QFormLayout(); layout.addLayout(form)
        self.kind = QComboBox(); self.kind.addItem('고유명사/용어 권장 표기', 'TERM')
        self.kind.addItem('인물 호칭·말투', 'VOICE'); form.addRow('규칙 종류', self.kind)
        self.first = QSpinBox(); self.first.setRange(1, 1000); form.addRow('시작 회차', self.first)
        self.last = QSpinBox(); self.last.setRange(1, 1000); self.last.setValue(1000)
        form.addRow('종료 회차', self.last)
        self.subject = QLineEdit(); self.subject.setMaxLength(100)
        form.addRow('용어/인물 이름', self.subject)
        self.preferred = QLineEdit(); self.preferred.setMaxLength(180)
        form.addRow('권장 표기/호칭·말투 지시', self.preferred)
        self.avoided = QLineEdit(); self.avoided.setMaxLength(950)
        form.addRow('피할 변형 표기 (쉼표 구분, 최대 12개)', self.avoided)
        self.guidance = QPlainTextEdit(); self.guidance.setMaximumHeight(85)
        form.addRow('작가 추가 지시', self.guidance)
        self.folder_label = QLabel('기록 폴더 미선택'); form.addRow(self.folder_label)
        choose = QPushButton('기존 로컬 규칙 폴더 직접 선택')
        choose.clicked.connect(self.choose_folder); layout.addWidget(choose)
        self.listing = QComboBox(); layout.addWidget(self.listing)
        self.save_consent = QCheckBox('이번 언어 규칙 파일 신규 저장을 직접 승인합니다')
        self.withdraw_consent = QCheckBox('선택한 기록의 이번 철회를 직접 승인합니다')
        self.batch_approval = QCheckBox('이번 AI 다회차 집필 1회에 현재 언어 규칙 사용을 별도 승인합니다')
        layout.addWidget(self.save_consent); layout.addWidget(self.withdraw_consent)
        layout.addWidget(self.batch_approval)
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        for title, fn in [('규칙 저장', self.save), ('선택 규칙 철회', self.withdraw),
                          ('현재 규칙 읽기', self.refresh)]:
            btn = QPushButton(title); btn.clicked.connect(fn); buttons.addWidget(btn)
        self.status = QLabel('기존 저장 원고/참고작/모델/계정은 변경하지 않습니다.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        for widget in (self.first, self.last):
            widget.valueChanged.connect(self._revoke)
        for widget in (self.subject, self.preferred, self.avoided):
            widget.textChanged.connect(self._revoke)
        self.kind.currentIndexChanged.connect(self._revoke)
        self.guidance.textChanged.connect(self._revoke)
        self.batch_approval.toggled.connect(self._bind_batch)

    def _signature(self):
        session = self.authoring.session
        return (str(session.path), str(session.project_id))

    def _revoke(self, *_):
        self.save_consent.setChecked(False)
        self.batch_approval.setChecked(False)

    def invalidate(self):
        self.save_consent.setChecked(False); self.withdraw_consent.setChecked(False)
        self.batch_approval.setChecked(False)
        self._bound = self._batch_bound = self._batch_stamp = None
        self.folder = None
        self.listing.clear()
        self.folder_label.setText('작품 변경: 규칙 폴더를 다시 선택하세요.')

    def _project(self):
        store, pid = self.authoring.session.required()
        if self.folder is None:
            raise AuthorLanguageError('기존 로컬 언어 규칙 폴더를 선택하세요.')
        return store, str(pid)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, '작가 언어 규칙 기록용 기존 로컬 폴더')
        if path:
            self.invalidate()
            self.folder = Path(path)
            self.folder_label.setText('로컬 규칙 폴더가 선택됐습니다.')

    def _bind_batch(self, checked):
        self._batch_bound = self._batch_stamp = None
        if checked:
            try:
                _, pid = self._project()
                self._batch_bound = (self._signature(), pid)
                self._batch_stamp = language_ledger_fingerprint(self.folder)
            except (AuthorLanguageError, OSError, ValueError):
                self.batch_approval.setChecked(False)
                self.status.setText('작품·로컬 규칙 폴더를 다시 선택해야 합니다.')

    def consume_batch_folder(self) -> str | None:
        if not self.batch_approval.isChecked():
            return None
        try:
            _, pid = self._project()
            if (self._batch_bound != (self._signature(), pid)
                    or self._batch_stamp != language_ledger_fingerprint(self.folder)):
                raise AuthorLanguageError('규칙 변경: 이전 배치 승인이 무효입니다.')
            return str(self.folder)
        finally:
            self.batch_approval.setChecked(False)

    def refresh(self):
        self.listing.clear(); self.withdraw_consent.setChecked(False)
        try:
            _, pid = self._project()
            rules = read_author_language_rules(self.folder, pid)
            for rule in rules:
                name = ('용어' if rule.kind == 'TERM' else '인물 말투')
                state = '철회됨' if rule.withdrawn else '활성'
                self.listing.addItem(f'{rule.first_episode}~{rule.last_episode}화 / {name} / {rule.subject} / {state}',
                                     rule.rule_id)
            self._bound = self._signature()
            self.status.setText(f'작가 언어 규칙 {len(rules)}개 조회. 자동 교정·QC PASS 없음.')
        except (AuthorLanguageError, OSError, ValueError):
            self._bound = None
            self.status.setText('현재 작품 언어 규칙을 불러오지 못했습니다.')

    def save(self):
        approved = self.save_consent.isChecked()
        self.save_consent.setChecked(False)
        try:
            store, pid = self._project()
            values = tuple(value.strip() for value in self.avoided.text().split(',') if value.strip())
            add_author_language_rule(store, pid, folder=self.folder,
                kind=self.kind.currentData(), first_episode=self.first.value(),
                last_episode=self.last.value(), subject=self.subject.text(),
                preferred=self.preferred.text(), discouraged=values,
                guidance=self.guidance.toPlainText(), explicit_author_save=approved)
            self.batch_approval.setChecked(False)
            self.refresh()
        except (AuthorLanguageError, OSError, ValueError):
            self.status.setText('언어 규칙을 저장하지 않았습니다. 입력·기존 규칙·승인을 확인하세요.')

    def withdraw(self):
        approved = self.withdraw_consent.isChecked()
        self.withdraw_consent.setChecked(False)
        try:
            _, pid = self._project()
            ident = self.listing.currentData()
            if not approved or not ident or self._bound != self._signature():
                raise AuthorLanguageError('기록과 별도 철회 승인을 다시 선택하세요.')
            withdraw_author_language_rule(self.folder, pid, ident, explicit_author_withdraw=True)
            self.batch_approval.setChecked(False)
            self.refresh()
        except (AuthorLanguageError, OSError, ValueError):
            self.status.setText('규칙을 철회하지 않았습니다. 활성 기록을 다시 선택하세요.')
