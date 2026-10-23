"""Author-approved, offline assembly of five author-selected long-form sources.

A context envelope is not a manuscript, a QC result, an inference approval or a
publication approval. No data is written. Neither missing content nor excess
context may be silently dropped when a source was explicitly selected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from .database.episodes import EpisodeStore
from .author_arc_ledger import canon_fingerprint, arc_ledger_fingerprint
from .author_arc_context import build_author_arc_context, require_author_arc_for_model
from .author_scene_plan import scene_plan_fingerprint
from .author_scene_context import build_author_scene_context, require_author_scene_context
from .author_fact_ledger import ledger_fingerprint
from .author_fact_context import build_author_fact_context
from .author_language_ledger import language_ledger_fingerprint
from .author_language_context import build_author_language_context, require_author_language_context
from .author_memory_delta import list_author_memory_deltas, memory_delta_fingerprint
from .author_memory_context import build_author_memory_context


class AuthorContextEnvelopeError(ValueError):
    """Error messages intentionally never contain user text or local paths."""


@dataclass(frozen=True)
class AuthorContextSources:
    project_id: str
    canon_sha256: str
    # Empty string means the author did not opt in to that specific source.
    arc_folder: str = field(default='', repr=False)
    scene_folder: str = field(default='', repr=False)
    fact_folder: str = field(default='', repr=False)
    language_folder: str = field(default='', repr=False)
    arc_sha256: str = ''
    scene_sha256: str = ''
    fact_sha256: str = ''
    language_sha256: str = ''
    memory_folder: str = field(default='', repr=False)
    memory_sha256: str = ''


@dataclass(frozen=True)
class AuthorContextEnvelope:
    episode: int
    scene_count: int
    outline: str = field(repr=False)
    scenes: tuple[str, ...] = field(repr=False)
    sources: AuthorContextSources = field(repr=False)
    content_sha256: str
    quality_certified: bool = False
    publication_approved: bool = False

    def for_scene(self, position: int, *, max_chars: int = 14500) -> str:
        if type(position) is not int or not 1 <= position <= self.scene_count:
            raise AuthorContextEnvelopeError('작가 문맥의 장면 번호가 올바르지 않습니다.')
        result = self.outline + ('\n' + self.scenes[position - 1]
                                 if self.scenes[position - 1] else '')
        if len(result) > max_chars:
            raise AuthorContextEnvelopeError('작가 승인 문맥이 장면별 한도를 초과했습니다.')
        return result


def _folder(path: str | Path | None) -> str:
    if path is None or str(path).strip() == '':
        return ''
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_symlink() or not candidate.is_dir():
        raise AuthorContextEnvelopeError('기존 로컬 작가 기록 폴더를 직접 선택하세요.')
    return str(candidate.resolve())


def _stamp(folder: str, reader) -> str:
    return reader(folder) if folder else ''


def capture_author_context_sources(store: EpisodeStore, project_id: str, *,
                                   arc_folder: str | Path | None = None,
                                   scene_folder: str | Path | None = None,
                                   fact_folder: str | Path | None = None,
                                   language_folder: str | Path | None = None,
                                   memory_folder: str | Path | None = None,
                                   ) -> AuthorContextSources:
    """Record *one explicit selection*; this alone grants no model execution."""
    if not isinstance(store, EpisodeStore) or type(project_id) is not str or not project_id:
        raise AuthorContextEnvelopeError('기존 작품을 먼저 열어야 합니다.')
    paths = tuple(_folder(p) for p in
                  (arc_folder, scene_folder, fact_folder, language_folder, memory_folder))
    if not any(paths):
        raise AuthorContextEnvelopeError('사용할 작가 기록을 한 종류 이상 직접 선택하세요.')
    # Do not include the private path/text in a digest or log file.
    canon = canon_fingerprint(store, project_id)
    return AuthorContextSources(
        project_id=project_id, canon_sha256=canon,
        arc_folder=paths[0], scene_folder=paths[1], fact_folder=paths[2],
        language_folder=paths[3], memory_folder=paths[4],
        arc_sha256=_stamp(paths[0], arc_ledger_fingerprint),
        scene_sha256=_stamp(paths[1], scene_plan_fingerprint),
        fact_sha256=_stamp(paths[2], ledger_fingerprint),
        language_sha256=_stamp(paths[3], language_ledger_fingerprint),
        memory_sha256=_stamp(paths[4], memory_delta_fingerprint))


def require_unchanged_author_sources(store: EpisodeStore, project_id: str,
                                     sources: AuthorContextSources) -> None:
    """Call immediately before every model request AND before any manuscript save."""
    if (not isinstance(sources, AuthorContextSources) or
            project_id != sources.project_id or
            canon_fingerprint(store, project_id) != sources.canon_sha256):
        raise AuthorContextEnvelopeError('작품 설정이 변경되어 작가 문맥 승인이 무효화되었습니다.')
    for path, expected, reader in (
        (sources.arc_folder, sources.arc_sha256, arc_ledger_fingerprint),
        (sources.scene_folder, sources.scene_sha256, scene_plan_fingerprint),
        (sources.fact_folder, sources.fact_sha256, ledger_fingerprint),
        (sources.language_folder, sources.language_sha256, language_ledger_fingerprint),
        (sources.memory_folder, sources.memory_sha256, memory_delta_fingerprint),
    ):
        if path and (not Path(path).is_dir() or reader(path) != expected):
            raise AuthorContextEnvelopeError('작가 기록이 변경되어 다시 직접 선택·승인해야 합니다.')
    if sources.memory_folder:
        # The ledger SHA alone is insufficient: the evidence is a saved final
        # manuscript, which may change without changing the author's JSON.
        saved = {row.episode: row for row in store.list_episodes(project_id)}
        for record in list_author_memory_deltas(sources.memory_folder, project_id):
            if record.retracted:
                continue
            chapter = saved.get(record.source_episode)
            if (chapter is None or chapter.revision != record.source_revision
                    or not chapter.final_text.strip()
                    or sha256(chapter.final_text.encode('utf-8')).hexdigest()
                       != record.source_sha256):
                raise AuthorContextEnvelopeError(
                    '기억 근거 최종본이 변경되어 집필 문맥 사용 승인을 다시 받아야 합니다.')
        if memory_delta_fingerprint(sources.memory_folder) != sources.memory_sha256:
            raise AuthorContextEnvelopeError('작가 기억 기록이 변경됐습니다.')


def compose_author_context(store: EpisodeStore, project_id: str, *,
                           episode: int, scene_count: int,
                           sources: AuthorContextSources,
                           max_outline_chars: int = 12000,
                           max_scene_chars: int = 14500,
                           ) -> AuthorContextEnvelope:
    """Combine only explicitly opted-in sources; never infer facts or truncate."""
    if (type(episode) is not int or not 1 <= episode <= 1000 or
            type(scene_count) is not int or not 1 <= scene_count <= 20 or
            type(max_outline_chars) is not int or not 3000 <= max_outline_chars <= 20000 or
            type(max_scene_chars) is not int or not max_outline_chars <= max_scene_chars <= 24000):
        raise AuthorContextEnvelopeError('집필 문맥의 회차·장면·길이 범위가 잘못되었습니다.')
    require_unchanged_author_sources(store, project_id, sources)
    outlines: list[str] = []
    per_scene = tuple('' for _ in range(scene_count))
    if sources.arc_folder:
        arc = build_author_arc_context(store, project_id, next_episode=episode,
                                       folder=sources.arc_folder,
                                       expected_ledger_sha256=sources.arc_sha256)
        outlines.append(require_author_arc_for_model(arc))
    if sources.scene_folder:
        scene = require_author_scene_context(build_author_scene_context(
            store, project_id, episode=episode, scenes_per_episode=scene_count,
            folder=sources.scene_folder,
            arc_folder=sources.arc_folder or None,
            expected_ledger_sha256=sources.scene_sha256))
        outlines.append(scene.outline_context)
        per_scene = scene.scene_contexts
    if sources.fact_folder:
        fact = build_author_fact_context(store, project_id, next_episode=episode,
                                         folder=sources.fact_folder, max_chars=5000)
        if (fact.stale_source or fact.conflicting or fact.truncated or
                not fact.included or not fact.context):
            raise AuthorContextEnvelopeError('작가 사실 근거가 누락·충돌·오래되어 집필을 보류합니다.')
        outlines.append(fact.context)
    if sources.language_folder:
        language = build_author_language_context(
            store, project_id, episode=episode, folder=sources.language_folder,
            expected_ledger_sha256=sources.language_sha256)
        outlines.append(require_author_language_context(language))
    if sources.memory_folder:
        memory = build_author_memory_context(
            store, project_id, folder=sources.memory_folder, episode=episode,
            expected_ledger_sha256=sources.memory_sha256, max_chars=4200)
        if memory.stale or not memory.included or not memory.content:
            raise AuthorContextEnvelopeError('작가 기억 근거가 없어 집필 문맥을 보류합니다.')
        outlines.append(memory.content)
    if not outlines:
        raise AuthorContextEnvelopeError('사용하도록 승인한 작가 문맥이 없습니다.')
    heading = f'[작가 직접 작성한 회차별 참고 문맥 / {episode}화 / 검수·출판 미승인]'
    outline = heading + '\n' + '\n\n'.join(outlines)
    if len(outline) > max_outline_chars or any(
            len(outline) + len(scene) + 1 > max_scene_chars for scene in per_scene):
        raise AuthorContextEnvelopeError('작가 문맥이 한도를 초과했습니다. 임의로 줄이지 않습니다.')
    require_unchanged_author_sources(store, project_id, sources)
    signature = sha256((outline + '\u241e' + '\u241e'.join(per_scene)).encode('utf-8')).hexdigest()
    return AuthorContextEnvelope(episode, scene_count, outline, per_scene,
                                 sources, signature)
