"""Stage 59: offline episode/scene plot editing widget (optional PySide6)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QSpinBox,
    QLabel, QPlainTextEdit, QPushButton, QFileDialog, QMessageBox,
)

from .plot_editor_model import PlotEditorSession
from ai_novel_factory.database.novel_bible import NovelBibleError


class PlotEditorWidget(QWidget):
    """Edits only Episode.plot and scene text; never draft/final/publishing.

    Database selection is explicit and read-only until Save/Add/Create/Delete.
    """
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = PlotEditorSession()
        self._scene_id: str | None = None
        self._active_project_id: str | None = None
        self._active_episode_number: int | None = None
        self._displayed_plot = ''
        self._displayed_scene = ''
        root = QVBoxLayout(self)
        root.addWidget(QLabel('로컬 SQLite DB의 기존 작품·회차를 선택한 후 플롯을 수동 편집합니다.'))
        bar = QHBoxLayout()
        self.open_button = QPushButton('로컬 DB 열기')
        self.open_button.setObjectName('plotOpenDatabase')
        self.path_label = QLabel('선택된 DB 없음')
        bar.addWidget(self.open_button)
        bar.addWidget(self.path_label, stretch=1)
        root.addLayout(bar)
        form = QFormLayout()
        self.project_combo = QComboBox()
        self.project_combo.setObjectName('plotProjectSelector')
        self.episode_combo = QComboBox()
        self.episode_combo.setObjectName('plotEpisodeSelector')
        self.create_episode_button = QPushButton('새 회차 생성')
        self.create_episode_button.setObjectName('plotCreateEpisode')
        self.new_episode_number = QSpinBox()
        self.new_episode_number.setRange(1, 1000000)
        form.addRow('작품', self.project_combo)
        form.addRow('기존 회차', self.episode_combo)
        form.addRow('새 회차 번호', self.new_episode_number)
        root.addLayout(form)
        root.addWidget(self.create_episode_button)
        self.revision_label = QLabel('회차를 불러오지 않았습니다.')
        root.addWidget(self.revision_label)
        self.plot_input = QPlainTextEdit()
        self.plot_input.setObjectName('episodePlotInput')
        self.plot_input.setPlaceholderText('회차 목표·필수 사건·감정 변화·Hook 등 회차 플롯')
        self.plot_input.setMaximumHeight(140)
        root.addWidget(QLabel('회차 플롯 (사용자 직접 작성)'))
        root.addWidget(self.plot_input)
        self.save_plot_button = QPushButton('회차 플롯 저장')
        self.save_plot_button.setObjectName('saveEpisodePlot')
        root.addWidget(self.save_plot_button)
        root.addWidget(QLabel('장면별 플롯 (자유 텍스트, 원고 자동 생성 아님)'))
        self.scene_combo = QComboBox()
        self.scene_combo.setObjectName('plotSceneSelector')
        root.addWidget(self.scene_combo)
        self.scene_input = QPlainTextEdit()
        self.scene_input.setObjectName('scenePlotInput')
        self.scene_input.setPlaceholderText('장면의 장소·등장인물·목표·갈등·감정 방향 입력')
        self.scene_input.setMaximumHeight(140)
        root.addWidget(self.scene_input)
        scene_buttons = QHBoxLayout()
        self.add_scene_button = QPushButton('장면 추가')
        self.add_scene_button.setObjectName('addPlotScene')
        self.save_scene_button = QPushButton('장면 저장')
        self.save_scene_button.setObjectName('savePlotScene')
        self.delete_scene_button = QPushButton('장면 삭제')
        self.delete_scene_button.setObjectName('deletePlotScene')
        scene_buttons.addWidget(self.add_scene_button)
        scene_buttons.addWidget(self.save_scene_button)
        scene_buttons.addWidget(self.delete_scene_button)
        root.addLayout(scene_buttons)
        self.info = QLabel('AI 집필 및 출판 비활성 · 저장 시 회차 버전 검사')
        self.info.setObjectName('plotEditorStatus')
        root.addWidget(self.info)
        self.open_button.clicked.connect(self._choose_database)
        self.project_combo.currentIndexChanged.connect(self._switch_project)
        self.episode_combo.currentIndexChanged.connect(self._switch_episode)
        self.scene_combo.currentIndexChanged.connect(self._switch_scene)
        self.create_episode_button.clicked.connect(self._create_episode)
        self.save_plot_button.clicked.connect(self._save_plot)
        self.add_scene_button.clicked.connect(self._add_scene)
        self.save_scene_button.clicked.connect(self._save_scene)
        self.delete_scene_button.clicked.connect(self._delete_scene)
        self._render(None)

    def closeEvent(self, event) -> None:
        if not self._warn_unsaved():
            event.ignore()
            return
        self.session.close()
        event.accept()

    def _warn_unsaved(self) -> bool:
        if (self.plot_input.toPlainText() == self._displayed_plot
                and self.scene_input.toPlainText() == self._displayed_scene):
            return True
        return QMessageBox.question(self, '저장되지 않은 변경',
            '저장되지 않은 플롯 수정이 있습니다. 변경사항을 버리시겠습니까?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _run(self, fn) -> None:
        try:
            fn()
        except (NovelBibleError, ValueError, OSError) as exc:
            # Domain errors intentionally do not contain user-authored text.
            self.info.setText(str(exc))
        except Exception:
            self.info.setText('로컬 플롯 편집 중 오류가 발생했습니다.')

    def _choose_database(self) -> None:
        if not self._warn_unsaved():
            return
        filename, _ = QFileDialog.getOpenFileName(self, '기존 로컬 SQLite DB', '',
                                                   'SQLite DB (*.db *.sqlite *.sqlite3);;모든 파일 (*)')
        if filename:
            self.open_database(filename)

    def open_database(self, filename: str) -> None:
        """Public method allows desktop integration tests without native dialogs."""
        if not self._warn_unsaved():
            return
        def action():
            projects = self.session.open_existing(filename)
            self.path_label.setText('로컬 DB 연결됨')  # don't show sensitive paths
            self._render(None)
            self._active_project_id = None
            self._active_episode_number = None
            self.project_combo.blockSignals(True)
            self.project_combo.clear()
            for project_id, title in projects:
                self.project_combo.addItem(title, project_id)
            self.project_combo.blockSignals(False)
            self._switch_project(0)
        self._run(action)

    def _switch_project(self, _index: int) -> None:
        project_id = self.project_combo.currentData()
        if (self._active_project_id is not None and project_id != self._active_project_id
                and not self._warn_unsaved()):
            self.project_combo.blockSignals(True)
            self.project_combo.setCurrentIndex(self.project_combo.findData(self._active_project_id))
            self.project_combo.blockSignals(False)
            return
        self._active_project_id = project_id
        self._active_episode_number = None
        def action():
            self.episode_combo.blockSignals(True)
            self.episode_combo.clear()
            if project_id:
                for ep in self.session.list_episodes(project_id):
                    self.episode_combo.addItem(f'{ep}화', ep)
            self.episode_combo.blockSignals(False)
            self._switch_episode(0)
        self._run(action)

    def _switch_episode(self, _index: int) -> None:
        project_id = self.project_combo.currentData()
        ep = self.episode_combo.currentData()
        if (self._active_episode_number is not None and ep != self._active_episode_number
                and not self._warn_unsaved()):
            self.episode_combo.blockSignals(True)
            self.episode_combo.setCurrentIndex(self.episode_combo.findData(self._active_episode_number))
            self.episode_combo.blockSignals(False)
            return
        self._active_episode_number = ep
        def action():
            if project_id and ep:
                self._render(self.session.load(project_id, ep))
            else:
                self._render(None)
        self._run(action)

    def _render(self, view) -> None:
        self.scene_combo.blockSignals(True)
        self.scene_combo.clear()
        self._scene_id = None
        if view is None:
            self.revision_label.setText('회차를 불러오지 않았습니다.')
            self._displayed_plot = ''
            self.plot_input.setPlainText('')
        else:
            self.revision_label.setText(f'{view.project_title} · {view.episode_number}화 · 버전 {view.revision}')
            self._displayed_plot = view.plot
            self.plot_input.setPlainText(view.plot)
            for sid, position, _text in view.scenes:
                self.scene_combo.addItem(f'장면 {position}', sid)
        self.scene_combo.blockSignals(False)
        self._switch_scene(0)
        enabled = view is not None
        for button in (self.save_plot_button, self.add_scene_button, self.save_scene_button,
                       self.delete_scene_button):
            button.setEnabled(enabled)
        self.info.setText('수동 저장만 허용 · AI/출판 비활성')

    def _switch_scene(self, _index: int) -> None:
        target = self.scene_combo.currentData()
        if (self._scene_id is not None and target != self._scene_id
                and not self._warn_unsaved()):
            self.scene_combo.blockSignals(True)
            self.scene_combo.setCurrentIndex(self.scene_combo.findData(self._scene_id))
            self.scene_combo.blockSignals(False)
            return
        self._scene_id = target
        view = self.session.current
        self._displayed_scene = ''
        if view and self._scene_id:
            self._displayed_scene = next((text for sid, _, text in view.scenes
                                          if sid == self._scene_id), '')
        self.scene_input.setPlainText(self._displayed_scene)
        self.save_scene_button.setEnabled(bool(self._scene_id))
        self.delete_scene_button.setEnabled(bool(self._scene_id))

    def _create_episode(self) -> None:
        project_id = self.project_combo.currentData()
        if not project_id or not self._warn_unsaved():
            return
        def action():
            view = self.session.create_episode(project_id, self.new_episode_number.value())
            self._refresh_episode_list(view.episode_number)
        self._run(action)

    def _refresh_episode_list(self, episode_number: int) -> None:
        project_id = self.project_combo.currentData()
        numbers = self.session.list_episodes(project_id)
        self.episode_combo.blockSignals(True)
        self.episode_combo.clear()
        for number in numbers:
            self.episode_combo.addItem(f'{number}화', number)
        index = self.episode_combo.findData(episode_number)
        self.episode_combo.setCurrentIndex(index)
        self.episode_combo.blockSignals(False)
        self._active_episode_number = episode_number
        self._render(self.session.current)

    def _save_plot(self) -> None:
        if self.scene_input.toPlainText() != self._displayed_scene:
            self.info.setText('먼저 장면 플롯을 저장하거나 변경을 취소하세요.')
            return
        def action():
            view = self.session.save_plot(self.plot_input.toPlainText())
            self._render(view)
            self.info.setText('회차 플롯 수동 저장 완료')
        self._run(action)

    def _add_scene(self) -> None:
        if not self._warn_unsaved():
            return
        def action():
            view = self.session.add_scene('')
            self._render(view)
            self.scene_combo.setCurrentIndex(self.scene_combo.count()-1)
            self.info.setText('장면 추가 완료 · 장면 내용을 수동 입력하세요')
        self._run(action)

    def _save_scene(self) -> None:
        if not self._scene_id:
            return
        if self.plot_input.toPlainText() != self._displayed_plot:
            self.info.setText('먼저 회차 플롯을 저장하거나 변경을 취소하세요.')
            return
        scene_id, text = self._scene_id, self.scene_input.toPlainText()
        def action():
            view = self.session.save_scene(scene_id, text)
            self._render(view)
            self.scene_combo.setCurrentIndex(self.scene_combo.findData(scene_id))
            self.info.setText('장면 플롯 수동 저장 완료')
        self._run(action)

    def _delete_scene(self) -> None:
        if not self._scene_id:
            return
        if not self._warn_unsaved():
            return
        if QMessageBox.question(self, '장면 삭제 확인', '이 장면을 삭제하시겠습니까?',
                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                  QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        def action():
            self._render(self.session.delete_scene(self._scene_id))
            self.info.setText('장면 삭제 완료')
        self._run(action)
