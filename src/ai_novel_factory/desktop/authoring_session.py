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
        if type(premise) is not str or not premise.strip():
            raise AuthoringError('최상위 작품 설정을 입력하세요.')
        # The pen name is optional while drafting. Store an explicit
        # 'undecided' marker so EPUB metadata is never a fabricated author.
        if type(author) is not str:
            raise AuthoringError('작가 이름의 형식이 올바르지 않습니다.')
        author = author.strip() or '미정'
        # Reserve the exact target exclusively, not just path.exists():
        # another process may have created a user's file after our check.
        db = None
        reserved_identity = None
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            try:
                metadata = os.fstat(fd)
                reserved_identity = (metadata.st_dev, metadata.st_ino)
            finally:
                os.close(fd)
            db = EpisodeStore(path)
            project = db.create_project(title)
            db.save_rule(project.project_id, 'author', author)
            db.save_rule(project.project_id, 'premise', premise)
            for key, value in extra_rules.items():
                if value.strip():
                    db.save_rule(project.project_id, key, value)
        except FileExistsError:
            raise AuthoringError('기존 작품 파일을 덮어쓸 수 없습니다.') from None
        except BaseException:
            if db is not None:
                db.close()
            # Remove only the empty/new DB file reserved by *this* call.
            # If the path was replaced, never unlink that other file.
            if reserved_identity is not None:
                try:
                    current = path.lstat()
                    if (current.st_dev, current.st_ino) == reserved_identity:
                        path.unlink()
                except FileNotFoundError:
                    pass
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
        try:
            project_id = projects[0][0]
            # Completely validate the next project/episode/scene BEFORE
            # closing the current user's session. A damaged import must
            # never close the manuscript the person was already editing.
            # The user-facing studio and advanced form immediately read
            # metadata, the current chapter, its scene and QA records. All
            # those reads must succeed BEFORE replacing the active session.
            # These checks are read-only and do not fill in missing rules.
            db.get_project(project_id)
            db.list_rules(project_id)
            episodes = db.list_episodes(project_id)
            episode_number = episodes[0].episode if episodes else None
            if episode_number is not None:
                db.get_episode(project_id, episode_number)
                scenes = db.list_scenes(project_id, episode_number)
                scene_id = scenes[0].scene_id if scenes else None
                if scene_id is not None:
                    db.get_scene(project_id, episode_number, scene_id)
                db.list_checks(project_id, episode_number)
            else:
                scene_id = None
        except BaseException:
            db.close()
            raise
        self.close()
        self.store, self.path, self.project_id = db, Path(filename), project_id
        self.episode_number, self.scene_id = episode_number, scene_id

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
        # Load *all* dependent data before switching active chapter, so
        # failed/corrupt scene reads cannot leave a half-selected session.
        scenes = db.list_scenes(pid, number)
        self.episode_number = number
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

    def prepare_generation(self, executable, arguments, approved, goal, conflict, location, characters):
        """Resolve the author-owned canon and identity on the GUI thread."""
        if approved is not True:
            raise AuthoringError('로컬 실행 파일을 명시적으로 승인하세요.')
        ep, scene = self.episode(), self.scene()
        if not ep.plot.strip() or not scene.text.strip():
            raise AuthoringError('회차와 장면 플롯을 먼저 저장하세요.')
        # The explicit --gguf choice may be a larger Korean-capable CPU model.
        # Keep the original short limit for the tiny bundled smoke model.
        limit = 450 if arguments[:1] == ('--gguf',) else 120
        provider = LocalExecutableProvider(executable, arguments=arguments,
                                           timeout_seconds=limit, explicitly_allowed=True)
        metadata = {r.key: r.value for r in self.store.list_rules(self.project_id)}
        canon = self.rule('premise')
        # Use Korean labels when sending the unchanged stored metadata to
        # local models. English schema keys appeared verbatim in bad drafts.
        author_labels = {'genre': '장르', 'subject': '주제',
                         'mood': '분위기', 'target_episodes': '목표 회차 수',
                         'characters_per_episode': '회차당 목표 글자 수'}
        for field, label in author_labels.items():
            if metadata.get(field):
                canon += '\n' + label + ': ' + metadata[field]
        # The saved episode length must reach the model, even when a user
        # does not repeat "5000자" in the free-text scene goal. Distribute
        # across the episode's real scene count; never multiply the target
        # by the number of scenes. Existing free-text scene targets remain
        # author-owned and can override this fallback in the model bridge.
        episode_length = metadata.get('characters_per_episode', '').strip()
        scene_target = None
        if episode_length.isdecimal() and 1 <= int(episode_length) <= 1_000_000:
            scene_count = max(1, len(self.store.list_scenes(self.project_id, ep.episode)))
            scene_target = (int(episode_length) + scene_count - 1) // scene_count
        request = SceneDraftRequest(
            self.project_id, ep.episode, scene.position, canon,
            goal, conflict, location, characters, ep.plot + '\n' + scene.text,
            target_chars=scene_target)
        rules_snapshot = tuple(sorted(
            (rule.key, rule.value, rule.revision)
            for rule in self.store.list_rules(self.project_id)))
        identity = (str(self.path), self.project_id, ep.episode, scene.scene_id,
                    ep.revision, scene.text, rules_snapshot)
        return request, provider, identity

    def accept_generation(self, request, result, identity):
        """Discard stale async drafts; never attach them to a different manuscript."""
        if (not self.store or not self.path
                or (str(self.path), self.project_id, self.episode_number, self.scene_id)
                != identity[:4]):
            raise AuthoringError('작품/회차/장면이 변경되어 이전 AI 결과를 적용하지 않았습니다.')
        ep, scene = self.episode(), self.scene()
        if ep.revision != identity[4] or scene.text != identity[5]:
            raise AuthoringError('집필 도중 회차/장면이 바뀌어 AI 결과를 적용하지 않았습니다.')
        current_rules = tuple(sorted(
            (rule.key, rule.value, rule.revision)
            for rule in self.store.list_rules(self.project_id)))
        if current_rules != identity[6]:
            raise AuthoringError('집필 도중 Novel Bible이 변경되어 이전 AI 결과를 적용하지 않았습니다.')
        if result.project_id != request.project_id or result.episode_number != request.episode_number:
            raise AuthoringError('AI 결과의 작품/회차가 일치하지 않습니다.')
        self.pending_draft = result.draft
        return result.draft

    def generate(self, executable, arguments, approved, goal, conflict, location, characters):
        """Backward-compatible synchronous API for non-GUI callers."""
        request, provider, identity = self.prepare_generation(
            executable, arguments, approved, goal, conflict, location, characters)
        return self.accept_generation(request, draft_scene(request, provider), identity)

    def save_draft(self, text):
        if self.pending_draft is None or not text.strip():
            raise AuthoringError('저장할 로컬 모델 초고가 없습니다.')
        db, pid = self.required()
        ep = self.episode()
        db.update_episode(pid, ep.episode, expected_revision=ep.revision, draft=text)
        self.pending_draft = None

    def save_final_text(self, text, *, human_reviewed=False,
                        incomplete_qc_acknowledged=False):
        """Explicit manual review, not an automatic quality or publication pass."""
        if human_reviewed is not True or incomplete_qc_acknowledged is not True:
            raise AuthoringError('직접 검수 및 미완료 품질 검사 확인이 모두 필요합니다.')
        if type(text) is not str or not text.strip():
            raise AuthoringError('최종 원고가 비어 있습니다.')
        db, pid = self.required()
        ep = self.episode()
        if not ep.draft.strip():
            raise AuthoringError('먼저 초고를 저장하세요.')
        if ep.final_text.strip():
            raise AuthoringError('기존 최종본은 덮어쓰지 않습니다.')
        db.update_episode(pid, ep.episode,
                          expected_revision=ep.revision, final_text=text)

    def export_final(self, directory, price):
        """Export reviewed final episodes only, privately and exclusively."""
        db, pid = self.required()
        parent = Path(directory)
        if not parent.is_absolute() or parent.is_symlink() or not parent.is_dir():
            raise AuthoringError('기존 로컬 출력 폴더를 선택하세요.')
        chapters = tuple(Chapter(f'{ep.episode}화', ep.final_text)
                         for ep in db.list_episodes(pid) if ep.final_text.strip())
        if not chapters:
            raise AuthoringError('저장된 검수 최종 원고가 없습니다.')
        folder = parent / 'reviewed_final'
        if folder.exists() or folder.is_symlink():
            raise AuthoringError('검수본 출력 폴더가 이미 존재합니다. 덮어쓰지 않습니다.')
        folder.mkdir(mode=0o700)
        meta = MetadataDraft(pid, db.get_project(pid).title,
                             self.rule('author'), self.rule('premise'),
                             '소설', ('사용자검수본', '비공개'), price)
        txt = folder / 'final.txt'
        try:
            epub = create_epub(meta, chapters, folder)
            with os.fdopen(os.open(txt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                           'w', encoding='utf-8') as out:
                out.write('\n\n'.join(f'# {c.title}\n\n{c.text}' for c in chapters) + '\n')
                out.flush()
                os.fsync(out.fileno())
            verify_epub(epub.path, expected_chapters=len(chapters),
                        expected_sha256=epub.sha256)
        except BaseException:
            txt.unlink(missing_ok=True)
            (folder / 'book.epub').unlink(missing_ok=True)
            folder.rmdir()
            raise
        return txt, epub.path

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
