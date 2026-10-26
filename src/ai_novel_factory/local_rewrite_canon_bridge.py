"""Read-only author canon and real saved-neighbor bridge for local rewrite.

Never calls AI, writes SQLite, exposes reference-original prose or asserts
literary approval. Registered private character secrets are NOT added to
open-POV rewrite context, because no one can assume who knows a secret.
All excerpts are labeled and omitted records disclosed, never invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .author_canon_context import read_saved_author_context
from .database.episodes import EpisodeStore
from .database.characters import CharacterStore


class RewriteCanonBridgeError(ValueError):
    """Errors intentionally omit author manuscript and private paths."""


@dataclass(frozen=True)
class SavedRewriteCanon:
    episode: int
    text: str = field(repr=False)
    author_sections: int = 0
    neighbor_chapters: tuple[int, ...] = ()
    missing_neighbor_chapters: tuple[int, ...] = ()
    omitted_author_records: int = 0
    verified_prose: bool = False
    publication_approved: bool = False


def _excerpt(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    marker = '[원문 중간 생략: 실제 저장값 발췌본]'
    if max_chars < len(marker) + 20:
        return marker
    left = (max_chars - len(marker)) // 3
    return value[:left] + marker + value[-(max_chars - len(marker) - left):]


def build_saved_rewrite_canon(
    store: EpisodeStore, database_path: str | Path,
    project_id: str, episode: int, *,
    max_chars: int = 6500,
) -> SavedRewriteCanon:
    """Connect real stored author facts and adjacent manuscript provenance."""
    if (not isinstance(store, EpisodeStore)
            or type(project_id) is not str or not project_id
            or type(episode) is not int or not 1 <= episode <= 1000
            or type(max_chars) is not int or not 3000 <= max_chars <= 8500):
        raise RewriteCanonBridgeError('작가 저장 문맥의 회차·범위가 올바르지 않습니다.')
    path = Path(database_path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise RewriteCanonBridgeError('기존 작가 로컬 SQLite를 선택하세요.')
    project = store.get_project(project_id)
    store.get_episode(project_id, episode)
    rule_rows = store.list_rules(project_id)
    saved_temporal = read_saved_author_context(path, project_id, episode)
    with CharacterStore(path) as char_store:
        people = char_store.list_characters(project_id)
    reserved = {'author', 'target_episodes', 'characters_per_episode',
                'ai_story_outline_preview', 'price', 'model',
                'executable', 'arguments'}
    rules = sorted(
        (r for r in rule_rows if r.key not in reserved),
        key=lambda r: (
            0 if r.key in ('bible', 'premise', 'genre', 'subject', 'mood') else 1,
            r.key))
    selected, used, omitted = [], 0, 0
    for item in rules:
        cap = min(400, max(0, 1450 - used - len(item.key) - 12))
        if cap < 80:
            omitted += 1
            continue
        val = _excerpt(item.value, cap)
        selected.append(f'- {item.key}: {val}')
        used += len(item.key) + len(val) + 5
    character_lines = [
        f'- {p.name}: 성격={_excerpt(p.personality, 90)} / '
        f'목표={_excerpt(p.goal, 90)} / '
        f'말투={_excerpt(p.speech_style, 90)}; '
        '비공개 비밀은 자동 제공하지 않음'
        for p in people[:8]
    ]
    omitted += max(0, len(people)-8)
    chapters = {row.episode: row for row in store.list_episodes(project_id)}
    found, missing, neighbor_lines = [], [], []
    for number in (episode-1, episode+1):
        if not 1 <= number <= 1000:
            continue
        row = chapters.get(number)
        passage = (row.final_text if row and row.final_text.strip()
                   else row.draft if row and row.draft.strip() else '')
        if not passage:
            missing.append(number)
            continue
        found.append(number)
        source = ('저장 최종본(검수 승인 별도)' if row.final_text.strip()
                  else '저장된 미검수 초고')
        excerpt = passage[-390:] if number < episode else passage[:390]
        label = ('직전 회차의 실제 끝 부분' if number < episode
                 else '뒤에 작성된 회차의 시작 부분, 이 회차에 아직 발생하지 않은 사건')
        neighbor_lines.append(f'[{number}화 {label}; {source}]\n{excerpt}')
    headings = [
        '[기존 Novel Bible과 작가 저장 실원고: 비검수 모델 참고 범위]',
        '작품: ' + _excerpt(project.title, 100),
        '[현재 작가 저장 작품 규칙]', *selected,
        '[현재 작가 저장 인물 성격·목표·말투]', *character_lines,
        '[해당 회차까지 작가가 기록한 세계관·관계·시간선·인물 지식]',
        _excerpt(saved_temporal.memory, 1400)
        if saved_temporal.memory else '[저장된 추가 사실 없음]',
        '[작가 저장 문체 지시]',
        _excerpt(saved_temporal.style, 800)
        if saved_temporal.style else '[추가 문체 지시 없음]',
        *neighbor_lines,
    ]
    if missing:
        headings.append('[인접 저장 본문 확인 불가: '
                        + ', '.join(map(str, missing))
                        + '화. 없는 사건을 추측하지 말 것]')
    if omitted:
        headings.append(f'[인물·작가 규칙 {omitted}개 본 모델 발췌 범위에서 생략됨]')
    headings.append(
        '[원작자 지시와 실제 초고를 우선. 뒤 회차의 저장 내용은 '
        '이번 회차에서 이미 일어난 일로 소급 금지. 발췌는 전체 검증 아님.]')
    text = '\n'.join(headings)
    if len(text) > max_chars:
        raise RewriteCanonBridgeError(
            '선택한 모델 문맥의 작가 원본 설정 분량이 너무 깁니다. '
            '임의 절단하지 않고 실행을 보류했습니다.')
    return SavedRewriteCanon(
        episode, text,
        int(bool(selected))+int(bool(people))
        +int(bool(saved_temporal.memory))+int(bool(saved_temporal.style)),
        tuple(found), tuple(missing), omitted)
