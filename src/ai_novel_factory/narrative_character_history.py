"""Read-only character-specific long-range memory from saved local prose.

Extract excerpts of existing episodes (at most the previous 250) for the
characters actually selected for a current real GGUF scene. Never infer a
character fact or treat unreviewed drafts or an AI summary as author canon.
The indexed text stays in process memory; no manuscript or DB is modified.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


@dataclass(frozen=True)
class SavedCharacterEvent:
    episode: int
    source_kind: str
    characters: tuple[str, ...]
    excerpt: str


@dataclass(frozen=True)
class CharacterHistoryIndex:
    before_episode: int
    stored_episodes_scanned: int
    records: tuple[SavedCharacterEvent, ...]


_IGNORE = frozenset((
    '소설', '장면', '이번', '기획', '미검수', '인물', '저장', '사건',
    '작가', '세계관', '사용자', '원고', '작성', '선택', '전개',
    '현재', '다음', '이전', '목표', '그리고', '그러나', '하지만',
))


def build_saved_character_history(
    episodes: Mapping[int, object], before_episode: int,
    saved_names: tuple[str, ...],
    *, max_per_episode: int = 9,
) -> CharacterHistoryIndex:
    """Index only real saved, earlier-chapter text; never read future plans.

    In each eligible stored chapter, draw examples from both the beginning
    and end of the *whole saved text* so a long-running series can recover
    earlier character actions and dialogue instead of summary-only clues.
    """
    if (type(before_episode) is not int or not 1 <= before_episode <= 1000
            or type(saved_names) is not tuple
            or any(type(name) is not str for name in saved_names)
            or type(max_per_episode) is not int
            or not 2 <= max_per_episode <= 16):
        raise ValueError('장편 인물 기억의 회차 또는 이름 정보가 올바르지 않습니다.')
    clean_names = tuple(dict.fromkeys(name.strip() for name in saved_names
                                     if name.strip()))
    if not clean_names or before_episode == 1:
        return CharacterHistoryIndex(before_episode, 0, ())
    # Longest-first literal matching avoids counting one saved name nested in
    # another as a separate person's action. No model-derived names are added.
    alternatives = sorted(clean_names, key=lambda name: (-len(name), name))
    pattern = re.compile('|'.join(re.escape(name) for name in alternatives),
                         re.IGNORECASE)
    lookup = {name.casefold(): name for name in clean_names}
    records: list[SavedCharacterEvent] = []
    scanned = 0
    for n in range(max(1, before_episode - 250), before_episode):
        row = episodes.get(n)
        if row is None:
            continue
        final = getattr(row, 'final_text', '') or ''
        draft = getattr(row, 'draft', '') or ''
        summary = getattr(row, 'summary', '') or ''
        if isinstance(final, str) and final.strip():
            body, kind = final, '저장 최종본(별도 승인 확인 필요)'
        elif isinstance(draft, str) and draft.strip():
            body, kind = draft, '미검수 AI 초고'
        elif isinstance(summary, str) and summary.strip():
            body, kind = summary, '미확정 AI 요약'
        else:
            continue
        scanned += 1
        # Source is local. Limit memory while retaining early/late events.
        text = body[:100_000]
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        front = max_per_episode // 2
        selected = matches[:front] + matches[-(max_per_episode - front):]
        starts: set[int] = set()
        for match in selected:
            if match.start() in starts:
                continue
            starts.add(match.start())
            excerpt = text[max(0, match.start() - 90):
                           min(len(text), match.end() + 160)].strip()
            if not excerpt:
                continue
            names_found = tuple(name for name in clean_names
                                if re.search(re.escape(name), excerpt,
                                             re.IGNORECASE) is not None)
            if not names_found:
                name = lookup.get(match.group().casefold())
                names_found = (name,) if name else ()
            records.append(SavedCharacterEvent(
                n, kind, names_found, excerpt.replace('\x00', '')))
    return CharacterHistoryIndex(before_episode, scanned, tuple(records))


def focus_saved_character_history(
    index: CharacterHistoryIndex, participants: tuple[str, ...],
    cues: tuple[str, ...], *, max_chars: int = 1400,
) -> str:
    """Rank actual earlier prose for the people and action of THIS scene.

    Older 25-chapter milestones have an explicit chance to survive alongside
    recent events. Quoted excerpts are evidence, not a model instruction,
    a definitive character fact, or a human-reviewed final manuscript.
    """
    if (not isinstance(index, CharacterHistoryIndex)
            or type(participants) is not tuple
            or any(type(name) is not str for name in participants)
            or type(cues) is not tuple
            or any(type(cue) is not str for cue in cues)
            or type(max_chars) is not int or not 700 <= max_chars <= 2500):
        raise ValueError('인물별 이전 회차 기억 문맥의 형식이 올바르지 않습니다.')
    chosen_names = set(participants)
    if not chosen_names or not index.records:
        return ''
    cue_text = ' '.join(cues[:3])[:2600]
    cue_tokens = tuple(dict.fromkeys(
        word.casefold() for word in re.findall(
            r'[가-힣]{2,}|[A-Za-z][A-Za-z0-9_]{2,}', cue_text)
        if word not in _IGNORE and len(word) <= 18
    ))[:24]
    ranked: list[tuple[int, int, SavedCharacterEvent]] = []
    for order, event in enumerate(index.records):
        matched = chosen_names.intersection(event.characters)
        if not matched:
            continue
        lowered = event.excerpt.casefold()
        relevance = sum(1 for token in cue_tokens if token in lowered)
        recent = event.episode >= index.before_episode - 8
        milestone = event.episode == 1 or event.episode % 25 == 0
        # Mentioned participants score first; plot-term hits then recency.
        score = (12 * len(matched) + min(6, relevance) * 2
                 + (8 if recent else 0) + (3 if milestone else 0))
        ranked.append((score, order, event))
    if not ranked:
        return ''
    ranked.sort(key=lambda item: (-item[0], -item[2].episode, item[1]))
    # Cover more than only the most frequently mentioned protagonist.
    shortlisted: list[SavedCharacterEvent] = []
    used: set[int] = set()
    for name in participants:
        for score, order, event in ranked:
            if order not in used and name in event.characters:
                shortlisted.append(event)
                used.add(order)
                break
    for _, order, event in ranked:
        if order in used:
            continue
        shortlisted.append(event)
        used.add(order)
        if len(shortlisted) >= 7:
            break
    shortlisted = shortlisted[:7]
    header = ('[실제 SQLite 저장 원고에서 발췌한 인물별 과거 기억 '
              '/ 250화 이내 / 사용자 Novel Bible 및 현재 장면 사건 우선]\n'
              '이 기록은 과거 미검수 원문의 일부이며 현재의 확정 인물 관계나 '
              '미래 사건을 증명하지 않는다. 과거 대사를 그대로 복제하지 말 것.\n')
    footer = '\n[미표시 과거 회차와 생략된 문단 존재. 자동 품질 인증 아님]'
    budget = max_chars - len(header) - len(footer)
    lines = []
    # Chronological presentation prevents ranking order becoming a false
    # narrative event order when the local model reads the context.
    for event in sorted(shortlisted, key=lambda item: item.episode):
        allowance = min(210, max(70, budget - 65))
        excerpt = event.excerpt
        if len(excerpt) > allowance:
            excerpt = excerpt[:allowance // 2] + ' …[중간 생략]… ' + excerpt[-allowance // 2:]
        line = f'{event.episode}화 {event.source_kind} · {", ".join(event.characters)}: {excerpt}\n'
        if len(line) <= budget:
            lines.append(line)
            budget -= len(line)
    return header + ''.join(lines) + footer if lines else ''
