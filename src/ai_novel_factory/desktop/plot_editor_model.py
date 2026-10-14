"""Stage 59: UI-independent editing session for local, user-approved plot changes.

No implicit writes: selecting/opening and changing editor text do not modify SQLite.
Existing EpisodeStore revision checks prevent overwriting concurrent edits.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from urllib.parse import quote

from ai_novel_factory.database.episodes import EpisodeError, EpisodeSnapshot, EpisodeStore
from ai_novel_factory.database.novel_bible import NovelBibleError


class PlotEditorError(ValueError):
    """Non-sensitive editing/session errors."""


@dataclass(frozen=True)
class PlotEditorView:
    project_id: str
    episode_number: int
    revision: int
    plot: str
    scenes: tuple[tuple[str, int, str], ...]  # id, position, text
    project_title: str


class PlotEditorSession:
    def __init__(self) -> None:
        self._store: EpisodeStore | None = None
        self._snapshot: EpisodeSnapshot | None = None
        self._project_title: str = ''
        self._path: Path | None = None

    @property
    def connected(self) -> bool:
        return self._store is not None

    @property
    def current(self) -> PlotEditorView | None:
        if self._snapshot is None:
            return None
        ep = self._snapshot.episode
        return PlotEditorView(ep.project_id, ep.episode, ep.revision, ep.plot,
                              tuple((s.scene_id, s.position, s.text) for s in self._snapshot.scenes),
                              self._project_title)

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
        self._store = None
        self._snapshot = None
        self._path = None
        self._project_title = ''

    def open_existing(self, path: str | Path) -> tuple[tuple[str, str], ...]:
        """Only open existing local DB files; never silently create an empty DB."""
        target = Path(path)
        if not target.is_file() or target.is_symlink() or not target.resolve().is_file():
            raise PlotEditorError('기존 로컬 DB 파일만 열 수 있습니다.')
        # Refuse URI and UNC paths, including on non-Windows test environments.
        raw = str(path)
        if raw.startswith(('file:', '\\\\', '//')):
            raise PlotEditorError('로컬 DB 파일만 열 수 있습니다.')
        # Read-only preflight: opening an unrelated or empty SQLite file must
        # never silently initialize the Novel Bible schema.
        try:
            uri = 'file:' + quote(str(target.resolve()), safe='/') + '?mode=ro'
            with sqlite3.connect(uri, uri=True) as probe:
                tables = {row[0] for row in probe.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ")}
                if not {'bible_projects', 'bible_episodes'} <= tables:
                    raise PlotEditorError('기존 Novel Bible 회차 DB가 아닙니다.')
        except sqlite3.DatabaseError:
            raise PlotEditorError('유효한 로컬 SQLite DB가 아닙니다.') from None
        store = EpisodeStore(target)
        try:
            projects = tuple((p.project_id, p.title) for p in store.list_projects())
        except BaseException:
            store.close()
            raise
        self.close()
        self._store = store
        self._path = target
        return projects

    def _required(self) -> EpisodeStore:
        if self._store is None:
            raise PlotEditorError('먼저 로컬 DB를 열어 주세요.')
        return self._store

    def list_episodes(self, project_id: str) -> tuple[int, ...]:
        return tuple(e.episode for e in self._required().list_episodes(project_id))

    def load(self, project_id: str, episode_number: int) -> PlotEditorView:
        store = self._required()
        title = store.get_project(project_id).title
        snapshot = store.snapshot(project_id, episode_number)
        self._snapshot = snapshot
        self._project_title = title
        return self.current  # type: ignore[return-value]

    def create_episode(self, project_id: str, episode_number: int) -> PlotEditorView:
        store = self._required()
        store.create_episode(project_id, episode_number)
        return self.load(project_id, episode_number)

    def _current(self) -> EpisodeSnapshot:
        if self._snapshot is None:
            raise PlotEditorError('편집할 회차를 먼저 불러오세요.')
        return self._snapshot

    def save_plot(self, plot: str) -> PlotEditorView:
        old = self._current().episode
        self._required().update_episode(old.project_id, old.episode,
                                        expected_revision=old.revision, plot=plot)
        return self.load(old.project_id, old.episode)

    def add_scene(self, text: str) -> PlotEditorView:
        old = self._current()
        ep = old.episode
        positions = {scene.position for scene in old.scenes}
        position = next((i for i in range(1, 201) if i not in positions), None)
        if position is None:
            raise PlotEditorError('장면 개수 제한을 초과했습니다.')
        self._required().add_scene(ep.project_id, ep.episode, position, text,
                                   expected_revision=ep.revision)
        return self.load(ep.project_id, ep.episode)

    def save_scene(self, scene_id: str, text: str) -> PlotEditorView:
        old = self._current()
        if scene_id not in {scene.scene_id for scene in old.scenes}:
            raise PlotEditorError('현재 회차에 없는 장면입니다.')
        ep = old.episode
        self._required().update_scene(ep.project_id, ep.episode, scene_id,
                                      expected_revision=ep.revision, text=text)
        return self.load(ep.project_id, ep.episode)

    def delete_scene(self, scene_id: str) -> PlotEditorView:
        old = self._current()
        if scene_id not in {scene.scene_id for scene in old.scenes}:
            raise PlotEditorError('현재 회차에 없는 장면입니다.')
        ep = old.episode
        self._required().delete_scene(ep.project_id, ep.episode, scene_id,
                                      expected_revision=ep.revision)
        return self.load(ep.project_id, ep.episode)
