"""Explicit, private GUI authoring over the existing SQLite and local-model APIs."""
from __future__ import annotations
import os
from pathlib import Path
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.desktop.plot_editor_model import PlotEditorSession
from ai_novel_factory.epub3 import Chapter, create_epub, verify_epub
from ai_novel_factory.local_models import LocalExecutableProvider, SceneDraftRequest, draft_scene
from ai_novel_factory.publication_metadata import MetadataDraft

class AuthoringError(ValueError):
    pass

class AuthoringSession:
    def __init__(self):
        self.close()

    def close(self):
        if getattr(self, 'store', None):
            self.store.close()
        self.store = None
        self.path = None
        self.project_id = None
        self.episode_number = None
        self.scene_id = None
        self.pending_draft = None

    def required(self):
        if not self.store or not self.project_id:
            raise AuthoringError('로컬 작품 DB를 먼저 열어 주세요.')
        return self.store, self.project_id

    def episode(self):
        db, pid = self.required()
        if self.episode_number is None:
            raise AuthoringError('회차를 먼저 생성하세요.')
        return db.get_episode(pid, self.episode_number)

    def scene(self):
        db, pid = self.required()
        if not self.scene_id:
            raise AuthoringError('장면을 먼저 생성하세요.')
        return db.get_scene(pid, self.episode().episode, self.scene_id)

    def create_project(self, filename, title, author, premise, *,
                       extra_rules=None):
        extra_rules = extra_rules or {}
        allowed = {'genre', 'subject', 'target_episodes',
                   'characters_per_episode', 'mood'}
        if (type(extra_rules) is not dict or
                any(k not in allowed or type(v) is not str or len(v) > 4000
                    for k, v in extra_rules.items())):
            raise AuthoringError('초기 설정 값이 올바르지 않습니다.')
        path = Path(filename)
        if (not path.is_absolute() or path.exists() or path.is_symlink()
                or not path.parent.is_dir() or path.suffix.lower() not in ('.db', '.sqlite')):
            raise AuthoringError('기존 파일이 없는 로컬 SQLite 경로를 선택하세요.')
        db = EpisodeStore(path)
        try:
            project = db.create_project(title)
            db.save_rule(project.project_id, 'author', author)
            db.save_rule(project.project_id, 'premise', premise)
            for key, value in extra_rules.items():
                if value.strip():
                    db.save_rule(project.project_id, key, value)
        except BaseException:
            db.close()
            path.unlink(missing_ok=True)
            raise
        self.close()
        self.store, self.path, self.project_id = db, path, project.project_id
        return project.project_id

    def open_project(self, filename):
        probe = PlotEditorSession()
        try:
            projects = probe.open_existing(filename)
        finally:
            probe.close()
        if not projects:
            raise AuthoringError('DB에 작품이 없습니다.')
        db = EpisodeStore(filename)
        self.close()
        self.store, self.path, self.project_id = db, Path(filename), projects[0][0]
        episodes = db.list_episodes(self.project_id)
        if episodes:
            self.select_episode(episodes[0].episode)

    def rule(self, key):
        db, pid = self.required()
        return db.get_rule(pid, key).value

    def save_bible(self, premise):
        db, pid = self.required()
        old = db.get_rule(pid, 'premise')
        db.save_rule(pid, 'premise', premise, expected_revision=old.revision)

    def select_episode(self, number):
        db, pid = self.required()
        db.get_episode(pid, number)
        self.episode_number = number
        scenes = db.list_scenes(pid, number)
        self.scene_id = scenes[0].scene_id if scenes else None
        self.pending_draft = None

    def create_episode(self, number, plot):
        db, pid = self.required()
        db.create_episode(pid, number, plot=plot)
        self.select_episode(number)

    def save_plot(self, plot):
        db, pid = self.required()
        ep = self.episode()
        db.update_episode(pid, ep.episode, expected_revision=ep.revision, plot=plot)

    def add_scene(self, text):
        db, pid = self.required()
        ep = self.episode()
        scenes = db.list_scenes(pid, ep.episode)
        position = next((i for i in range(1, 201)
                         if i not in {s.position for s in scenes}), None)
        if position is None:
            raise AuthoringError('장면 한도 초과')
        scene = db.add_scene(pid, ep.episode, position, text, expected_revision=ep.revision)
        self.scene_id, self.pending_draft = scene.scene_id, None

    def save_scene(self, text):
        db, pid = self.required()
        ep, scene = self.episode(), self.scene()
        db.update_scene(pid, ep.episode, scene.scene_id,
                        expected_revision=ep.revision, text=text)
        self.pending_draft = None

    def generate(self, executable, arguments, approved, goal, conflict, location, characters):
        if approved is not True:
            raise AuthoringError('로컬 실행 파일을 명시적으로 승인하세요.')
        ep, scene = self.episode(), self.scene()
        if not ep.plot.strip() or not scene.text.strip():
            raise AuthoringError('회차와 장면 플롯을 먼저 저장하세요.')
        provider = LocalExecutableProvider(executable, arguments=arguments,
                                           timeout_seconds=120, explicitly_allowed=True)
        metadata = {r.key: r.value for r in self.store.list_rules(self.project_id)}
        canon = self.rule('premise')
        for field in ('genre', 'subject', 'mood', 'target_episodes',
                      'characters_per_episode'):
            if metadata.get(field):
                canon += '\n' + field + ': ' + metadata[field]
        request = SceneDraftRequest(
            self.project_id, ep.episode, scene.position, canon,
            goal, conflict, location, characters, ep.plot + '\n' + scene.text)
        result = draft_scene(request, provider)
        self.pending_draft = result.draft
        return result.draft

    def save_draft(self, text):
        if self.pending_draft is None or not text.strip():
            raise AuthoringError('저장할 로컬 모델 초고가 없습니다.')
        db, pid = self.required()
        ep = self.episode()
        db.update_episode(pid, ep.episode, expected_revision=ep.revision, draft=text)
        self.pending_draft = None

    def export(self, directory, price):
        db, pid = self.required()
        output = Path(directory)
        if not output.is_absolute() or output.is_symlink() or not output.is_dir():
            raise AuthoringError('기존 로컬 폴더를 선택하세요.')
        chapters = tuple(Chapter(f'{ep.episode}화', ep.draft)
                         for ep in db.list_episodes(pid) if ep.draft.strip())
        if not chapters:
            raise AuthoringError('저장된 초고가 없습니다.')
        title = db.get_project(pid).title
        meta = MetadataDraft(pid, title, self.rule('author'), self.rule('premise'),
                             '소설', ('비공개초고',), price)
        txt = output / 'draft.txt'
        epub = output / 'book.epub'
        if txt.exists() or txt.is_symlink() or epub.exists() or epub.is_symlink():
            raise AuthoringError('내보내기 파일이 이미 존재합니다.')
        result = create_epub(meta, chapters, output)
        try:
            with os.fdopen(os.open(txt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                           'w', encoding='utf-8') as f:
                f.write('\n\n'.join(f'# {c.title}\n\n{c.text}' for c in chapters) + '\n')
                f.flush()
                os.fsync(f.fileno())
            verify_epub(result.path, expected_chapters=len(chapters),
                        expected_sha256=result.sha256)
        except BaseException:
            txt.unlink(missing_ok=True)
            result.path.unlink(missing_ok=True)
            raise
        return txt, result.path
