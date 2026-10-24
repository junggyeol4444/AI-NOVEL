"""Manual chapter-title editing for the existing Windows EPUB3 preview path."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from ..epub_toc_authoring import (
    EpubTocError, load_epub_toc_reedit_snapshot, plan_epub_toc,
    require_current_epub_toc_reedit_snapshot, save_new_epub_toc_manifest,
)


class EpubTocPanel(QGroupBox):
    def __init__(self, authoring, parent=None):
        super().__init__('EPUB3 회차별 목차 제목 · 로컬 JSON 별도 저장', parent)
        self.authoring = authoring
        self._overrides = {}
        self._project = None
        self._source_stamp = None
        self._import_snapshot = None
        layout = QVBoxLayout(self)
        self.through = QSpinBox()
        self.through.setRange(1, 1000)
        self.through.setValue(30)
        layout.addWidget(self.through)
        self.load = QPushButton('저장된 최종본 기준 목차 편집 시작')
        self.load.setObjectName('epubTocLoad')
        self.load.clicked.connect(self.load_plan)
        layout.addWidget(self.load)
        self.import_existing = QPushButton('기존 목차 JSON 직접 선택해 재편집 시작 (원본 읽기 전용)')
        self.import_existing.setObjectName('epubTocImportExisting')
        self.import_existing.clicked.connect(self.load_existing_manifest)
        layout.addWidget(self.import_existing)
        self.episode = QSpinBox()
        self.episode.setRange(1, 1000)
        self.episode.setValue(1)
        layout.addWidget(self.episode)
        self.title_edit = QLineEdit()
        self.title_edit.setMaxLength(120)
        self.title_edit.setPlaceholderText('현재 회차 목차 제목 (원고 본문 변경 없음)')
        layout.addWidget(self.title_edit)
        self.apply = QPushButton('선택 회차 제목을 임시 목차에 반영')
        self.apply.setObjectName('epubTocApply')
        self.apply.clicked.connect(self.apply_title)
        layout.addWidget(self.apply)
        self.consent = QCheckBox('이번 목차 제목을 새 로컬 JSON 파일로 저장합니다')
        layout.addWidget(self.consent)
        self.save = QPushButton('새 EPUB3 목차 JSON 저장 (기존 파일 덮어쓰기 없음)')
        self.save.setObjectName('epubTocSave')
        self.save.clicked.connect(self.save_manifest)
        layout.addWidget(self.save)
        self.status = QLabel('목차 편집은 SQLite 원고/EPUB 원본/출판 승인에 영향을 주지 않습니다.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.through.valueChanged.connect(self.invalidate)
        self.episode.valueChanged.connect(self.show_current)

    def invalidate(self, *_args):
        self._overrides = {}
        self._project = None
        self._source_stamp = None
        self._import_snapshot = None
        self.consent.setChecked(False)
        self.status.setText('작품 또는 회차 범위 변경: 기존 목차 편집 상태를 폐기했습니다.')

    def load_plan(self):
        self.invalidate()
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('먼저 기존 작품을 열어야 합니다.')
            return
        try:
            plan = plan_epub_toc(session.store, str(session.project_id),
                                 through_episode=self.through.value())
        except (EpubTocError, ValueError, OSError):
            self.status.setText('최종본 누락 또는 현재 작품 오류로 목차 편집을 시작하지 않았습니다.')
            return
        self._project = str(session.project_id)
        self._source_stamp = plan.source_sha256
        self.episode.setMaximum(plan.through_episode)
        self.show_current()
        self.status.setText(
            f'최종본 {plan.through_episode}화의 목차 제목 편집 준비. '
            '기본 제목은 N화이며 새 JSON 저장 전에는 어디에도 반영되지 않습니다.')

    def load_existing_manifest(self):
        session = self.authoring.session
        if session.store is None or session.project_id is None:
            self.status.setText('먼저 기존 작품을 열어야 합니다.')
            return
        path, _ = QFileDialog.getOpenFileName(
            self, '재편집할 기존 로컬 EPUB 목차 JSON 선택', '', 'JSON (*.json)')
        if not path:
            return
        self.invalidate()
        try:
            snapshot = load_epub_toc_reedit_snapshot(
                path, session.store, str(session.project_id),
                through_episode=self.through.value())
        except (EpubTocError, ValueError, OSError):
            self.status.setText('기존 목차 파일의 작품·범위·최종본이 일치하지 않아 불러오지 않았습니다.')
            return
        self._import_snapshot = snapshot
        self._project = snapshot.project_id
        self._source_stamp = snapshot.source_sha256
        self._overrides = {number: title for number, title in enumerate(snapshot.titles, 1)}
        self.episode.setMaximum(snapshot.through_episode)
        self.show_current()
        self.consent.setChecked(False)
        self.status.setText(
            f'기존 목차 {snapshot.through_episode}화 제목을 메모리로만 불러왔습니다. '
            '원본 JSON은 수정하지 않으며 새 파일명으로만 저장할 수 있습니다.')

    def show_current(self, *_args):
        if self._source_stamp is None:
            self.title_edit.clear()
            return
        n = self.episode.value()
        self.title_edit.setText(self._overrides.get(n, f'{n}화'))

    def apply_title(self):
        if self._source_stamp is None:
            self.status.setText('현재 최종본 목차 편집을 먼저 시작하세요.')
            return
        n = self.episode.value()
        session = self.authoring.session
        try:
            if self._import_snapshot is not None:
                require_current_epub_toc_reedit_snapshot(
                    self._import_snapshot, session.store, self._project)
            trial = dict(self._overrides)
            trial[n] = self.title_edit.text()
            plan = plan_epub_toc(session.store, self._project,
                                 through_episode=self.through.value(),
                                 overrides=trial)
            if plan.source_sha256 != self._source_stamp:
                raise EpubTocError('원고가 변경되었습니다.')
        except (EpubTocError, ValueError, OSError):
            self.invalidate()
            self.status.setText('회차 제목 중복/형식 오류 또는 원고 변경. 새로 시작하세요.')
            return
        self._overrides = trial
        self.consent.setChecked(False)
        self.status.setText(f'{len(trial)}화 제목을 메모리 목차에 반영. 파일은 아직 저장하지 않았습니다.')

    def save_manifest(self):
        session = self.authoring.session
        if (self._source_stamp is None or not self.consent.isChecked()
                or session.store is None or str(session.project_id) != self._project):
            self.status.setText('현재 작품 목차와 이번 파일 저장 승인을 확인하세요.')
            return
        self.consent.setChecked(False)
        try:
            if self._import_snapshot is not None:
                require_current_epub_toc_reedit_snapshot(
                    self._import_snapshot, session.store, self._project)
            plan = plan_epub_toc(session.store, self._project,
                                 through_episode=self.through.value(),
                                 overrides=self._overrides)
            if plan.source_sha256 != self._source_stamp:
                raise EpubTocError('원고가 변경되었습니다.')
        except (EpubTocError, ValueError, OSError):
            self.invalidate()
            self.status.setText('저장 최종본이 변경되었습니다. 목차를 다시 편집하세요.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '새 EPUB 목차 JSON 파일 저장', '', 'JSON (*.json)')
        if not path:
            return
        try:
            if self._import_snapshot is not None:
                require_current_epub_toc_reedit_snapshot(
                    self._import_snapshot, session.store, self._project)
            current = plan_epub_toc(
                session.store, self._project, through_episode=self.through.value(),
                overrides=self._overrides)
            if current != plan:
                raise EpubTocError('파일 선택 중 저장 원고가 변경되었습니다.')
            save_new_epub_toc_manifest(current, path, explicit_author_save=True)
        except (EpubTocError, ValueError, OSError):
            self.status.setText('기존 파일을 덮어쓰지 않았습니다. 새 JSON 파일명을 선택하세요.')
            return
        self.status.setText(
            f'목차 {plan.through_episode}화 로컬 JSON 신규 저장 완료. '
            'EPUB3 생성 화면에서 이 JSON을 별도로 선택하세요. 출판·업로드 없음.')
