"""Author-controlled Windows editor for 1~20 scene beats in one episode."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QSpinBox, QTableWidget, QTableWidgetItem, QPushButton, QCheckBox,
    QFileDialog, QListWidget)
from ..author_scene_plan import (AuthorScenePlanError, save_author_scene_plan,
    revoke_author_scene_plan, read_author_scene_plans, scene_plan_fingerprint)


class AuthorScenePlanPanel(QGroupBox):
    HEADERS = ('장면 목표', '갈등', '장소', '반드시 포함', '포함하지 말 것')

    def __init__(self, authoring, parent=None):
        super().__init__('작가 직접 회차별 장면 설계표 · 로컬 기록', parent)
        self.authoring = authoring
        self.folder = None
        self._project_bound = None
        self._batch_project = None
        self._batch_sha = None
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.episode = QSpinBox(); self.episode.setRange(1, 1000)
        self.scenes = QSpinBox(); self.scenes.setRange(1, 20); self.scenes.setValue(3)
        form.addRow('회차', self.episode); form.addRow('장면 수', self.scenes)
        self.folder_label = QLabel('기존 로컬 기록 폴더 미선택')
        select = QPushButton('기존 장면 계획 기록 폴더 직접 선택')
        select.clicked.connect(self.choose_folder)
        form.addRow(select); form.addRow(self.folder_label)
        self.table = QTableWidget(3, 5)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setMinimumHeight(170)
        root.addWidget(self.table)
        self.listing = QListWidget(); self.listing.setMaximumHeight(120)
        root.addWidget(self.listing)
        self.save_consent = QCheckBox('위 회차의 모든 장면을 이번 한 번 새 JSON으로 저장하는 데 동의')
        self.revoke_consent = QCheckBox('선택한 기록을 이번 한 번 철회하는 데 동의')
        self.batch_consent = QCheckBox('이번 AI 배치 한 번에만 작가 장면 계획을 사용합니다')
        root.addWidget(self.save_consent)
        root.addWidget(self.revoke_consent)
        root.addWidget(self.batch_consent)
        buttons = QHBoxLayout()
        for caption, action in [('새 계획 저장', self.save_plan),
                                ('선택 계획 철회', self.revoke_plan),
                                ('기록 다시 읽기', self.refresh)]:
            btn = QPushButton(caption); btn.clicked.connect(action)
            buttons.addWidget(btn)
        root.addLayout(buttons)
        self.status = QLabel('기존 원고·SQLite는 변경하지 않습니다. AI 실행/출판 자동 승인 없음.')
        self.status.setWordWrap(True); root.addWidget(self.status)
        self.scenes.valueChanged.connect(self._resize)
        self.episode.valueChanged.connect(self._changed)
        self.table.cellChanged.connect(self._changed)
        self.batch_consent.toggled.connect(self._bind_batch)

    def _changed(self, *args):
        self.save_consent.setChecked(False)
        self.batch_consent.setChecked(False)

    def _resize(self, count):
        self.table.setRowCount(count)
        self._changed()

    def _project(self):
        session = self.authoring.session
        store, pid = session.required()
        return store, str(pid), (str(session.path), str(pid))

    def invalidate(self):
        self.save_consent.setChecked(False)
        self.revoke_consent.setChecked(False)
        self.batch_consent.setChecked(False)
        self.listing.clear()
        self._project_bound = None
        self.status.setText('작품/경로 변경: 이전 장면 계획 승인과 목록을 초기화했습니다.')

    def choose_folder(self):
        value = QFileDialog.getExistingDirectory(self, '기존 로컬 장면 계획 폴더 선택')
        if value:
            self.folder = Path(value)
            self.folder_label.setText('기존 로컬 장면 계획 폴더 선택됨')
            self.invalidate()

    def _beats(self):
        beats = []
        for row in range(self.scenes.value()):
            values = []
            for col in range(5):
                item = self.table.item(row, col)
                values.append(item.text() if item is not None else '')
            beats.append(dict(zip(('goal','conflict','place','must_include','avoid'), values)))
        return tuple(beats)

    def refresh(self):
        self.listing.clear()
        self.revoke_consent.setChecked(False)
        try:
            _, pid, bound = self._project()
            if self.folder is None:
                raise AuthorScenePlanError('폴더를 먼저 선택하세요.')
            plans = read_author_scene_plans(self.folder, pid)
            for plan in plans:
                status = '철회' if plan.revoked else '작가 계획'
                self.listing.addItem(f'{plan.episode}화 · {len(plan.beats)}장면 · {status}')
                self.listing.item(self.listing.count()-1).setData(256, plan.plan_id)
            self._project_bound = bound
            self.status.setText(f'장면 계획 {len(plans)}건 읽음. 실제 집필·품질 검증은 NOT_RUN.')
        except (AuthorScenePlanError, OSError, ValueError):
            self.status.setText('선택한 작품의 장면 계획을 읽지 못했습니다.')

    def save_plan(self):
        approved = self.save_consent.isChecked()
        self.save_consent.setChecked(False)
        try:
            store, pid, _ = self._project()
            if self.folder is None:
                raise AuthorScenePlanError('폴더 선택 필요')
            save_author_scene_plan(store, pid, database_path=self.authoring.session.path,
                folder=self.folder, episode=self.episode.value(), beats=self._beats(),
                explicit_author_save=approved)
            self.batch_consent.setChecked(False)
            self.refresh()
        except (AuthorScenePlanError, OSError, ValueError):
            self.status.setText('저장하지 않았습니다. 장면 내용·폴더·이번 저장 승인을 확인하세요.')

    def revoke_plan(self):
        approved = self.revoke_consent.isChecked()
        self.revoke_consent.setChecked(False)
        try:
            _, pid, bound = self._project()
            current = self.listing.currentItem()
            if not approved or current is None or self._project_bound != bound:
                raise AuthorScenePlanError('기록 선택과 이번 철회 승인을 확인하세요.')
            revoke_author_scene_plan(self.folder, pid, current.data(256),
                                     explicit_author_revoke=True)
            self.batch_consent.setChecked(False)
            self.refresh()
        except (AuthorScenePlanError, OSError, ValueError):
            self.status.setText('철회하지 않았습니다. 작품과 기록을 다시 확인하세요.')

    def _bind_batch(self, enabled):
        self._batch_project = None
        self._batch_sha = None
        if enabled:
            try:
                _, _, bound = self._project()
                if self.folder is None:
                    raise AuthorScenePlanError('폴더 선택 필요')
                self._batch_sha = scene_plan_fingerprint(self.folder)
                self._batch_project = bound
            except (AuthorScenePlanError, OSError, ValueError):
                self.batch_consent.setChecked(False)
                self.status.setText('장면 계획 폴더와 현재 작품을 먼저 선택하세요.')

    def consume_batch_folder(self) -> str | None:
        if not self.batch_consent.isChecked():
            return None
        try:
            _, _, bound = self._project()
            if (self.folder is None or self._batch_project != bound
                    or self._batch_sha != scene_plan_fingerprint(self.folder)):
                raise AuthorScenePlanError('장면 계획 기록이 변경되었습니다.')
            return str(self.folder)
        finally:
            self.batch_consent.setChecked(False)
