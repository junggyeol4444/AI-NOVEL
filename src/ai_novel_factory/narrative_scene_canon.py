"""Read-only, episode-scoped author canon focused on the *current* GGUF scene.

This is a selection/formatting layer only: earlier AI prose and outlines are
relevance cues, never approved facts. Future episode relation, knowledge or
foreshadow events are never loaded into the current chapter snapshot. The
original author database, models and manuscripts are never modified here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3

from .author_canon_context import _rows

_PROJECT = re.compile(r"[0-9a-f]{32}\Z")
_WORDS = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_COMMON = frozenset(('이번', '장면', '인물', '소설', '작품', '사건', '작가', '회차',
                     '지난', '다음', '그녀', '그가', '그는', '나는', '상황', '그런',
                     '위해', '주인공', '시간', '그리고', '다시', '하지만'))


@dataclass(frozen=True)
class EpisodeCanonFocus:
    episode: int
    relations: tuple[tuple[str, str, int, str, str], ...]
    knowledge: tuple[tuple[str, int, str, bool], ...]
    foreshadow: tuple[tuple[str, int, str, str], ...]
    timeline: tuple[tuple[str, str, str], ...]
    chronology: tuple[tuple[str, str], ...]


def load_episode_canon_focus(database_path: str | Path,
                             project_id: str, episode: int) -> EpisodeCanonFocus:
    """Select the LAST author-written state effective at this chapter only.

    Missing optional tables represent no saved entries; existing tables are
    only read with query_only. No canon is generated or written by this code.
    """
    if (type(project_id) is not str or not _PROJECT.fullmatch(project_id)
            or type(episode) is not int or not 1 <= episode <= 1_000_000):
        raise ValueError('작품 또는 회차 지문이 올바르지 않습니다.')
    path = str(database_path)
    if not path or '\x00' in path or path.startswith(('file:', '\\\\', '//')):
        raise ValueError('로컬 작가 데이터베이스를 확인하세요.')
    with sqlite3.connect(path, timeout=10) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        if not db.execute('SELECT 1 FROM bible_projects WHERE project_id=?',
                          (project_id,)).fetchone():
            raise ValueError('저장된 작가 프로젝트를 찾을 수 없습니다.')
        tables = {
            name: _rows(db, name, project_id) for name in (
                'bible_characters', 'bible_relationship_events',
                'bible_knowledge_facts', 'bible_knowledge_events',
                'bible_foreshadow_threads', 'bible_foreshadow_events',
                'bible_timeline_events', 'bible_timeline_order')
        }
    names = {r['character_id']: r['name'] for r in tables['bible_characters']}
    facts = {r['fact_id']: r['description']
             for r in tables['bible_knowledge_facts']}
    threads = {r['thread_id']: r['title']
               for r in tables['bible_foreshadow_threads']}
    events = {r['event_id']: r for r in tables['bible_timeline_events']}

    relation_latest: dict[tuple[str, str], dict] = {}
    for row in sorted(tables['bible_relationship_events'],
                      key=lambda r: (r['episode'], r['revision'])):
        if row['episode'] <= episode:
            relation_latest[(row['first_character_id'],
                             row['second_character_id'])] = row
    relations = tuple(sorted((
        names[r['first_character_id']], names[r['second_character_id']],
        r['episode'], r['relationship'], r['notes'])
        for r in relation_latest.values()
        if (r['first_character_id'] in names
            and r['second_character_id'] in names)))

    knowledge_latest: dict[tuple[str, str], dict] = {}
    for row in sorted(tables['bible_knowledge_events'],
                      key=lambda r: (r['episode'], r['revision'])):
        if row['episode'] <= episode:
            knowledge_latest[(row['character_id'], row['fact_id'])] = row
    knowledge = tuple(sorted((
        names[r['character_id']], r['episode'], facts[r['fact_id']],
        bool(r['knows'])) for r in knowledge_latest.values()
        if r['character_id'] in names and r['fact_id'] in facts))

    foreshadow_latest: dict[str, dict] = {}
    for row in sorted(tables['bible_foreshadow_events'],
                      key=lambda r: (r['episode'], r['sequence'])):
        if row['episode'] <= episode:
            foreshadow_latest[row['thread_id']] = row
    foreshadow = tuple(sorted((
        threads[r['thread_id']], r['episode'], r['action'], r['note'])
        for r in foreshadow_latest.values() if r['thread_id'] in threads))

    timeline = tuple(sorted((r['event_id'], r['title'],
                             r['when_value'] or (
                                 ('상대 ' + str(r['offset_minutes']) + '분; 기준 사건: '
                                  + events[r['anchor_event_id']]['title'])
                                 if r['anchor_event_id'] in events
                                 else '시점 미지정'))
                            for r in events.values()))
    chronology = tuple(sorted((r['before_id'], r['after_id'])
                              for r in tables['bible_timeline_order']
                              if r['before_id'] in events and r['after_id'] in events))
    return EpisodeCanonFocus(episode, relations, knowledge, foreshadow,
                             timeline, chronology)


def focus_episode_canon(snapshot: EpisodeCanonFocus, participants: tuple[str, ...],
                        cues: tuple[str, ...], *, max_chars: int = 1950) -> str:
    """Render relevant *stored author facts* for actual local-model calls.

    Story text is only a retrieval cue. Omitted unrelated facts are not assumed
    false. A planned change in this same chapter is never described as already
    completed in the scene; next chapter's events are wholly absent.
    """
    if (type(snapshot) is not EpisodeCanonFocus
            or type(participants) is not tuple or type(cues) is not tuple
            or any(type(s) is not str for s in (*participants, *cues))
            or type(max_chars) is not int or not 250 <= max_chars <= 4000):
        raise ValueError('장면 인과 관계 문맥의 형식이 올바르지 않습니다.')
    cast = set(participants)
    signal = '\n'.join(cues[:3])[:5000]
    words = {w.casefold() for w in _WORDS.findall(signal)
             if w not in _COMMON}

    def score(text: str) -> int:
        # Exact phrases have precedence; shared non-generic terms can then
        # surface relevant saved facts even without the whole title/description.
        if not text.strip():
            return 0
        phrase = text.strip()[:100]
        exact = 12 if phrase.casefold() in signal.casefold() else 0
        tokens = {w.casefold() for w in _WORDS.findall(text[:180])
                  if w not in _COMMON}
        return exact + min(5, len(words & tokens))

    candidates: list[tuple[int, int, str]] = []
    for a, b, since, relation, note in snapshot.relations:
        cast_score = 18 if a in cast and b in cast else 9 if a in cast or b in cast else 0
        if not cast_score:
            continue
        # 'Effective at N' is not evidence this chapter's future scene
        # has already depicted the transition.
        marker = ('이번 회차부터 지정됨: 아직 장면에서 완료 여부 미확정'
                  if since == snapshot.episode else f'{since}화부터 적용')
        line = (f'관계 {a}—{b}: {relation[:200]} [{marker}]'
                + (f'; 작가 메모: {note[:110]}' if note.strip() else ''))
        candidates.append((cast_score + score(relation + ' ' + note), 0, line))
    for name, since, description, knows in snapshot.knowledge:
        if name not in cast:
            continue
        marker = ('이번 회차 지정(실제 장면 진행 미확정)'
                  if since == snapshot.episode else f'{since}화부터')
        state = '인지함' if knows else '알지 못함/인지 상실'
        candidates.append((9 + score(description), 1,
                           f'인물 지식 {name}: {description[:205]} / {state} [{marker}]. '
                           '대사·행동에서 인물이 모르는 내용을 안다고 가정 금지'))
    for title, since, action, note in snapshot.foreshadow:
        relevance = score(title + ' ' + note)
        if not relevance:
            continue
        marker = ('이번 화 작가 계획(이미 발생했다고 단정 금지)'
                  if since == snapshot.episode else f'{since}화까지 작가 기록')
        candidates.append((relevance + 3, 2,
                           f'복선 {title[:100]}: {action} / {note[:165]} [{marker}]. '
                           '별도 저장된 다음 회차 사건을 앞당기지 말 것'))
    by_id = {event_id: (title, when) for event_id, title, when in snapshot.timeline}
    active_ids: set[str] = set()
    for event_id, title, when in snapshot.timeline:
        relevance = score(title)
        if not relevance:
            continue
        active_ids.add(event_id)
        candidates.append((relevance + 2, 3,
                           f'시간선 계획 {title[:110]}: {when[:110]} '
                           '(작가의 계획일 뿐 본문에서 발생 확정 아님)'))
    for before, after in snapshot.chronology:
        if before in active_ids or after in active_ids:
            candidates.append((8, 4,
                               f'작가가 지정한 사건 순서: {by_id[before][0][:85]} 다음에 '
                               f'{by_id[after][0][:85]} 배치 (시간을 임의 확정 금지)'))
    if not candidates:
        return ''
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    heading = (f'{snapshot.episode}화 실제 장면에서 유효한 작가 저장 Novel Bible 사실 '
               '(AI 플롯은 선택 단서일 뿐 사실 아님; 미기록은 추측 금지):\n')
    selected = heading
    omitted = 0
    for _, _, entry in candidates:
        line = '- ' + entry.replace('\x00', '') + '\n'
        if len(selected) + len(line) + 55 <= max_chars:
            selected += line
        else:
            omitted += 1
    if omitted:
        selected += f'[관련 기록 {omitted}건 문맥 용량 때문에 생략: 미검토]\n'
    return selected[:max_chars]