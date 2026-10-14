"""Local authoring GUI event handlers; never uploads or publishes."""
from __future__ import annotations
import shlex
from PySide6.QtWidgets import QWidget
from .authoring_controls import AuthoringControls
from .authoring_session import AuthoringSession

class AuthoringWorkflowWidget(AuthoringControls, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = AuthoringSession()
        self.build_controls()

    def _run(self, fn, message):
        try:
            fn()
            self.status.setText(message)
            self._sync()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc)[:200])
        except Exception:
            self.status.setText('작업 실패: 상세 오류는 비공개입니다.')

    def _create(self):
        self.session.create_project(self._text('db'), self._text('title'),
                                    self._text('author'), self._text('premise'))

    def _open(self):
        self.session.open_project(self._text('db'))
        self._set('title', self.session.store.get_project(self.session.project_id).title)
        self._set('author', self.session.rule('author'))
        self._set('premise', self.session.rule('premise'))

    def _sync(self):
        if not self.session.store:
            return
        db, pid = self.session.required()
        self._set('bible', self.session.rule('premise'))
        self.episodes.blockSignals(True)
        self.episodes.clear()
        for ep in db.list_episodes(pid):
            self.episodes.addItem(f'{ep.episode}화', ep.episode)
        self.episodes.setCurrentIndex(self.episodes.findData(self.session.episode_number))
        self.episodes.blockSignals(False)
        self._sync_episode()

    def _sync_episode(self):
        db, pid = self.session.required()
        self.scenes.blockSignals(True)
        self.scenes.clear()
        if self.session.episode_number:
            ep = self.session.episode()
            self._set('plot', ep.plot)
            self._set('draft', self.session.pending_draft if self.session.pending_draft is not None else ep.draft)
            for scene in db.list_scenes(pid, ep.episode):
                self.scenes.addItem(f'장면 {scene.position}', scene.scene_id)
            self.scenes.setCurrentIndex(self.scenes.findData(self.session.scene_id))
        self.scenes.blockSignals(False)
        self._sync_scene()

    def _sync_scene(self):
        self._set('scene', self.session.scene().text if self.session.scene_id else '')

    def _select_episode(self, _index):
        number = self.episodes.currentData()
        if number:
            self._run(lambda: self.session.select_episode(number), '회차 선택 완료')

    def _select_scene(self, _index):
        sid = self.scenes.currentData()
        if sid:
            self.session.scene_id = sid
            self.session.pending_draft = None
            self._sync_scene()

    def _generate(self):
        arguments = tuple(shlex.split(self._text('arguments')))
        characters = tuple(v.strip() for v in self._text('characters').split(',') if v.strip())
        self.session.generate(self._text('executable'), arguments, self.approved.isChecked(),
                              self._text('goal'), self._text('conflict'), self._text('location'),
                              characters)
        self.approved.setChecked(False)

    def closeEvent(self, event):
        self.session.close()
        event.accept()
