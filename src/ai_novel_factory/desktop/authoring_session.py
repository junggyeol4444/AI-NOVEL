"""Explicit, private GUI authoring over the existing SQLite and local-model APIs."""
from __future__ import annotations
import os
from pathlib import Path
from ai_novel_factory.database.episodes import EpisodeStore
from ai_novel_factory.database.characters import CharacterStore
from ai_novel_factory.auto_novel_run import _character_bible_context
from ai_novel_factory.desktop.plot_editor_model import PlotEditorSession
from ai_novel_factory.epub3 import Chapter, create_epub, verify_epub
from ai_novel_factory.local_models import (LocalExecutableProvider, SceneDraftRequest,
                                          SceneDraftResult, MAX_DRAFT_CHARS, draft_scene)
from ai_novel_factory.publication_metadata import MetadataDraft, validate_metadata

class AuthoringError(ValueError):
    pass


def _manual_prior_context(earlier):
    """Pass only saved same-project events to the already approved local model.

    Existing drafts and summaries are explicitly UNAPPROVED, never promoted
    into author-owned canon or copied from any reference novel.
    """
    if not earlier:
        return ''
    checkpoints, recent = [], []
    for chapter in earlier[:-3]:
        if chapter.episode == 1 or chapter.episode % 25 == 0:
            # A summary may be stale or unreviewed. Use the actual saved
            # manuscript first, with an explicit reviewed/draft label.
            # Only use an unapproved summary if no saved prose exists.
            actual = chapter.final_text if chapter.final_text.strip() else chapter.draft
            if actual.strip():
                review = '검수본' if chapter.final_text.strip() else '미검수 초고'
                checkpoints.append(
                    f'{chapter.episode}화 {review} 마지막 사건 원문: {actual[-130:]}')
            elif chapter.summary.strip():
                checkpoints.append(
                    f'{chapter.episode}화 과거 미확정 요약: {chapter.summary[:130]}')
    for chapter in earlier[-3:]:
        if chapter.summary.strip():
            recent.append(f'{chapter.episode}화 최근 미확정 요약: {chapter.summary[:200]}')
        actual = chapter.final_text if chapter.final_text.strip() else chapter.draft
        if actual.strip():
            review = '검수본' if chapter.final_text.strip() else '미검수 초고'
            recent.append(f'{chapter.episode}화 {review} 저장 본문 마지막 사건: {actual[-260:]}')
    if not checkpoints and not recent:
        return ''
    # Always retain the first saved chapter's anchor and the newest four
    # checkpoints. Taking only the last eight dropped chapter 1 in a 250-part
    # work; slicing the JOINED text could silently drop that anchor again.
    if len(checkpoints) > 5:
        selected_checkpoints = ([checkpoints[0][:110]]
                                + ['[중간 체크포인트 생략: 저장 원문은 유지됨]']
                                + [item[:95] for item in checkpoints[-4:]])
    else:
        selected_checkpoints = [item[:110] for item in checkpoints]
    return ('같은 작품의 이전 회차 저장 기록 (작가 설정이 우선):\n'
            + '\n'.join(selected_checkpoints) + '\n'
            + '\n'.join(recent)[-900:])

def _manual_compact_character_lines(text: str, limit: int) -> str:
    """Fairly preserve every selected character and each saved fact field.

    A single long character used to consume the native 3900-character
    allowance and silently hide the eighth selected character. Only the
    temporary model excerpt is shortened, never the author's SQLite rows.
    """
    if len(text) <= limit:
        return text
    header, *lines = text.split('\n')
    if not lines:
        return text[:limit]
    header = header[:min(len(header), limit // 4)]
    remaining = max(0, limit - len(header) - len(lines))
    base, extra = divmod(remaining, len(lines))
    output = [header]
    for index, line in enumerate(lines):
        quota = base + (index < extra)
        if len(line) <= quota:
            output.append(line)
            continue
        fields = line.split(' | ')
        available = quota - 3 * (len(fields) - 1)
        if available <= 0:
            output.append(line[:quota])
            continue
        # Keep the name and the labels for personality, goal, speech and
        # secret. Distribute the remaining capacity among all saved fields.
        minimum = [min(len(field), max(8, len(field.split(':', 1)[0]) + 3))
                   for field in fields]
        if sum(minimum) > available:
            output.append(line[:quota])
            continue
        allowance = minimum[:]
        spare = available - sum(allowance)
        while spare:
            pending = [i for i, field in enumerate(fields)
                       if allowance[i] < len(field)]
            if not pending:
                break
            for i in pending:
                if not spare:
                    break
                allowance[i] += 1
                spare -= 1
        output.append(' | '.join(field[:width]
                                 for field, width in zip(fields, allowance)))
    return '\n'.join(output)[:limit]


def _manual_canon_context(character_context: str, author_context: str) -> str:
    """Bound model-only excerpts while identifying omissions of BOTH sources.

    Metadata labels belong to author_context BEFORE trimming; otherwise they
    were appended after the 12k budget and could silently evict the ending.
    No original Bible, character row or user-authored metadata is modified.
    """
    if not character_context and len(author_context) <= 12000:
        return author_context
    if len(character_context) + len(author_context) + 1 <= 12000:
        return (character_context + '\n' + author_context).strip()
    character_budget = min(3900, len(character_context))
    character_truncated = len(character_context) > character_budget
    author_label = '\n[모델 입력 길이 제한으로 일부 작가 설정이 생략됨. 저장된 원본은 유지됨]\n'
    character_label = '\n[모델 입력 길이 제한으로 일부 저장 인물 설정이 생략됨]\n'
    if character_truncated:
        character_budget -= len(character_label)
        character_excerpt = _manual_compact_character_lines(character_context, character_budget) + character_label
    else:
        character_excerpt = character_context
    remaining = 12000 - len(character_excerpt) - (1 if character_excerpt else 0)
    if len(author_context) > remaining:
        excerpt_budget = remaining - len(author_label)
        first = excerpt_budget // 2
        author_excerpt = (author_context[:first] + author_label
                          + author_context[-(excerpt_budget-first):])
    else:
        author_excerpt = author_context
    return (character_excerpt + '\n' if character_excerpt else '') + author_excerpt


def _manual_scene_context(plot: str, scene_text: str, prior_notes: str) -> str:
    """Keep last scene events AND earlier chapter memory within native style budget.

    A long user-authored scene previously made all earlier chapter context
    disappear. This sends bounded excerpts only; saved original is untouched.
    """
    # A long plot can reveal the current scene's resolution at its end.
    # Keep BOTH author-written endpoints within the original 1200-char quota.
    if len(plot) > 1200:
        marker = '\n[현재 플롯 중간 생략; 원본은 유지됨]\n'
        head = (1200 - len(marker)) // 2
        plot_excerpt = plot[:head] + marker + plot[-(1200 - len(marker) - head):]
    else:
        plot_excerpt = plot
    parts = [
        '현재 회차 플롯(앞부분과 뒷부분):\n' + plot_excerpt,
        '현재 장면(마지막 문맥):\n' + scene_text[-2100:],
    ]
    context = '\n'.join(parts)
    if prior_notes:
        # Never slice the combined prompt from the front: that used to drop
        # the latest saved events when the current scene was long. Reserve a
        # fixed budget and keep both the first anchor and newest events.
        prefix = '\n이전 회차 기록(정사 승인 아님):\n'
        budget = max(0, 5000 - len(context) - len(prefix))
        if budget >= 1:
            if len(prior_notes) <= budget:
                excerpt = prior_notes
            else:
                marker = '\n[이전 회차 중간 생략; 저장 원본 유지]\n'
                if budget > len(marker) + 40:
                    available = budget - len(marker)
                    earliest = available // 3
                    excerpt = (prior_notes[:earliest] + marker
                               + prior_notes[-(available-earliest):])
                else:
                    excerpt = prior_notes[-budget:]
            context += prefix + excerpt
    return context


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
        # Invalidate even when the same DB is reopened with identical revisions.
        self._active_generation_token = None
        self._pending_generation_provenance = None

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
        # Switching away and back to the same scene must invalidate old jobs.
        self._active_generation_token = None
        self._pending_generation_provenance = None

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
        self._pending_generation_provenance = None

    def save_scene(self, text):
        db, pid = self.required()
        ep, scene = self.episode(), self.scene()
        db.update_scene(pid, ep.episode, scene.scene_id,
                        expected_revision=ep.revision, text=text)
        self.pending_draft = None
        self._pending_generation_provenance = None

    def prepare_generation(self, executable, arguments, approved, goal, conflict, location, characters):
        """Resolve the author-owned canon and identity on the GUI thread."""
        if approved is not True:
            raise AuthoringError('로컬 실행 파일을 명시적으로 승인하세요.')
        ep, scene = self.episode(), self.scene()
        if not ep.plot.strip() or not scene.text.strip():
            raise AuthoringError('회차와 장면 플롯을 먼저 저장하세요.')
        # The explicit --gguf choice may be a larger Korean-capable CPU model.
        # Keep the original short limit for the tiny bundled smoke model.
        user_gguf = arguments[:1] == ('--gguf',)
        packaged_bridge = (isinstance(executable, (str, Path))
                           and Path(executable).name.casefold() == 'anf_local_model.exe')
        limit = 1500 if user_gguf and packaged_bridge else (450 if user_gguf else 120)
        provider = LocalExecutableProvider(executable, arguments=arguments,
                                           timeout_seconds=limit, explicitly_allowed=True)
        metadata = {r.key: r.value for r in self.store.list_rules(self.project_id)}
        canon = self.rule('premise')
        # Carry author-owned character facts into the same approved local model.
        # Reject stale asynchronous drafts when character revisions change.
        with CharacterStore(self.path) as character_store:
            saved_characters = character_store.list_characters(self.project_id)
        character_snapshot = tuple(
            (character.character_id, character.revision)
            for character in saved_characters)
        # Prioritize characters explicitly selected for THIS scene, even
        # when a long Bible has more than eight stored characters.
        selected_names = set(characters)
        ordered_characters = ([item for item in saved_characters
                               if item.name in selected_names]
                              + [item for item in saved_characters
                                 if item.name not in selected_names])
        character_context = _character_bible_context(ordered_characters[:8])
        # Use Korean labels when sending the unchanged stored metadata to
        # local models. English schema keys appeared verbatim in bad drafts.
        author_labels = {'genre': '장르', 'subject': '주제',
                         'mood': '분위기', 'target_episodes': '목표 회차 수',
                         'characters_per_episode': '회차당 목표 글자 수'}
        for field, label in author_labels.items():
            if metadata.get(field):
                canon += '\n' + label + ': ' + metadata[field]
        # Include every user-saved metadata field before applying the native
        # context budget; late metadata previously exceeded 12k silently.
        canon = _manual_canon_context(character_context, canon)
        # The saved episode length must reach the model, even when a user
        # does not repeat "5000자" in the free-text scene goal. Distribute
        # across the episode's real scene count; never multiply the target
        # by the number of scenes. Existing free-text scene targets remain
        # author-owned and can override this fallback in the model bridge.
        episode_length = metadata.get('characters_per_episode', '').strip()
        scene_target = None
        if episode_length.isdecimal() and 1 <= int(episode_length) <= 1_000_000:
            ordered_scenes = self.store.list_scenes(self.project_id, ep.episode)
            scene_count = max(1, len(ordered_scenes))
            scene_rank = next((index for index, item in enumerate(ordered_scenes)
                               if item.scene_id == scene.scene_id), None)
            if scene_rank is None:
                raise AuthoringError('현재 장면을 찾을 수 없습니다.')
            base_chars, remainder = divmod(int(episode_length), scene_count)
            if base_chars < 1:
                raise AuthoringError('장면 수가 회차 목표 글자 수보다 많습니다.')
            # Preserve exact chapter quota even when scene positions have gaps.
            scene_target = base_chars + (scene_rank < remainder)
            if scene_target > 10000:
                raise AuthoringError('장면별 목표 분량은 최대 10000자입니다.')
        prior_episodes = tuple(item for item in self.store.list_episodes(self.project_id)
                               if item.episode < ep.episode)
        prior_snapshot = tuple((item.episode, item.revision) for item in prior_episodes)
        prior_notes = _manual_prior_context(prior_episodes)
        # Preserve actual recent events even when the active plot is very long.
        # Only the prompt excerpt is bounded; stored source remains unchanged.
        scene_context = _manual_scene_context(ep.plot, scene.text, prior_notes)
        # A later request for the same scene supersedes an earlier in-flight
        # result, even if the saved episode and scene revisions are unchanged.
        self._active_generation_token = object()
        self.pending_draft = None
        self._pending_generation_provenance = None
        request = SceneDraftRequest(
            self.project_id, ep.episode, scene.position, canon,
            goal, conflict, location, characters, scene_context,
            target_chars=scene_target)
        rules_snapshot = tuple(sorted(
            (rule.key, rule.value, rule.revision)
            for rule in self.store.list_rules(self.project_id)))
        identity = (str(self.path), self.project_id, ep.episode, scene.scene_id,
                    ep.revision, scene.text, rules_snapshot,
                    character_snapshot, prior_snapshot, provider.provider_id,
                    self._active_generation_token)
        return request, provider, identity

    def accept_generation(self, request, result, identity):
        """Discard stale async drafts; never attach them to a different manuscript."""
        if (not self.store or not self.path
                or (str(self.path), self.project_id, self.episode_number, self.scene_id)
                != identity[:4]):
            raise AuthoringError('작품/회차/장면이 변경되어 이전 AI 결과를 적용하지 않았습니다.')
        if len(identity) != 11 or identity[10] is not getattr(self, '_active_generation_token', None):
            raise AuthoringError('더 새로운 집필 요청이 있어 이전 AI 결과를 적용하지 않았습니다.')
        ep, scene = self.episode(), self.scene()
        if ep.revision != identity[4] or scene.text != identity[5]:
            raise AuthoringError('집필 도중 회차/장면이 바뀌어 AI 결과를 적용하지 않았습니다.')
        current_rules = tuple(sorted(
            (rule.key, rule.value, rule.revision)
            for rule in self.store.list_rules(self.project_id)))
        if current_rules != identity[6]:
            raise AuthoringError('집필 도중 Novel Bible이 변경되어 이전 AI 결과를 적용하지 않았습니다.')
        with CharacterStore(self.path) as character_store:
            current_characters = tuple(
                (character.character_id, character.revision)
                for character in character_store.list_characters(self.project_id))
        if current_characters != identity[7]:
            raise AuthoringError('집필 도중 인물 설정이 변경되어 이전 AI 결과를 적용하지 않았습니다.')
        current_prior = tuple((item.episode, item.revision)
                              for item in self.store.list_episodes(self.project_id)
                              if item.episode < ep.episode)
        if current_prior != identity[8]:
            raise AuthoringError('집필 도중 이전 회차가 변경되어 이전 AI 결과를 적용하지 않았습니다.')
        if not isinstance(result, SceneDraftResult):
            raise AuthoringError('AI 결과 형식이 올바르지 않습니다.')
        if (result.project_id != request.project_id
                or result.episode_number != request.episode_number
                or result.scene_number != request.scene_number):
            raise AuthoringError('AI 결과의 작품/회차/장면이 일치하지 않습니다.')
        # Only the same explicitly approved offline provider's unpersisted
        # draft can enter the manual review queue. Never treat a claimed
        # APPROVED/persisted result as author-reviewed final prose.
        if (result.provider != identity[9]
                or result.status != 'DRAFT_REQUIRES_USER_APPROVAL'
                or result.persisted is not False):
            raise AuthoringError('AI 결과의 제공자/검수 상태가 일치하지 않습니다.')
        if (type(result.draft) is not str or not result.draft.strip()
                or len(result.draft) > MAX_DRAFT_CHARS):
            raise AuthoringError('AI 결과 본문이 비어 있거나 허용 분량을 초과했습니다.')
        # Bind the pending review text to the same revision snapshot until save.
        self._pending_generation_provenance = (request, result, identity)
        self.pending_draft = result.draft
        return result.draft

    def generate(self, executable, arguments, approved, goal, conflict, location, characters):
        """Backward-compatible synchronous API for non-GUI callers."""
        request, provider, identity = self.prepare_generation(
            executable, arguments, approved, goal, conflict, location, characters)
        return self.accept_generation(request, draft_scene(request, provider), identity)

    def save_draft(self, text):
        if self.pending_draft is None or type(text) is not str or not text.strip():
            raise AuthoringError('저장할 로컬 모델 초고가 없습니다.')
        # The SQLite/character/Bible snapshots may have changed AFTER the
        # async draft was accepted but BEFORE the author pressed Save.
        provenance = getattr(self, '_pending_generation_provenance', None)
        if provenance is None:
            self.pending_draft = None
            raise AuthoringError('AI 생성 결과 검증 정보가 없어 저장하지 않았습니다.')
        if provenance is not None:
            try:
                self.accept_generation(*provenance)
            except AuthoringError:
                self.pending_draft = None
                self._pending_generation_provenance = None
                raise
        db, pid = self.required()
        ep = self.episode()
        db.update_episode(pid, ep.episode, expected_revision=ep.revision, draft=text)
        self._pending_generation_provenance = None
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

    def export_final(self, directory, price, *, cover_path=None):
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
        # Validate the author's metadata BEFORE reserving the output folder.
        # Invalid price/legacy rules must not leave an empty reviewed_final
        # directory that blocks the user's next export attempt.
        meta = validate_metadata(MetadataDraft(
            pid, db.get_project(pid).title,
            self.rule('author'), self.rule('premise'),
            '소설', ('사용자검수본', '비공개'), price))
        folder.mkdir(mode=0o700)
        txt = folder / 'final.txt'
        try:
            epub = create_epub(meta, chapters, folder, cover_path=cover_path)
            with os.fdopen(os.open(txt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                           'w', encoding='utf-8') as out:
                out.write('\n\n'.join(f'# {c.title}\n\n{c.text}' for c in chapters) + '\n')
                out.flush()
                os.fsync(out.fileno())
            verify_epub(epub.path, expected_chapters=len(chapters),
                        expect_cover=cover_path is not None,
                        expected_sha256=epub.sha256)
        except BaseException:
            txt.unlink(missing_ok=True)
            (folder / 'book.epub').unlink(missing_ok=True)
            folder.rmdir()
            raise
        return txt, epub.path

    def export(self, directory, price, *, cover_path=None):
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
        result = create_epub(meta, chapters, output, cover_path=cover_path)
        try:
            with os.fdopen(os.open(txt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                           'w', encoding='utf-8') as f:
                f.write('\n\n'.join(f'# {c.title}\n\n{c.text}' for c in chapters) + '\n')
                f.flush()
                os.fsync(f.fileno())
            verify_epub(result.path, expected_chapters=len(chapters),
                        expect_cover=cover_path is not None,
                        expected_sha256=result.sha256)
        except BaseException:
            txt.unlink(missing_ok=True)
            result.path.unlink(missing_ok=True)
            raise
        return txt, result.path
