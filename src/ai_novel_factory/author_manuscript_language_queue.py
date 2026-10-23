"""작가 직접 조회용 저장 원고 한국어·분량·반복 표현 검토 대기열.

기존 SQLite의 실제 저장 최종본을 읽기 전용으로 전수 분석한다. 분량이나
문자 비율은 자연스러운 문학 품질을 판정할 수 없고 QC PASS도 생성하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from unicodedata import category

from .author_workflow_dependencies import build_author_workflow_dependencies
from .database.episodes import EpisodeStore


TARGET_NONSPACE_CHARS = 5000  # 작가의 기존 목표를 임의로 낮추지 않는다.


class ManuscriptLanguageQueueError(ValueError):
    """원고 원문·경로를 노출하지 않는 조회 오류."""


@dataclass(frozen=True)
class ManuscriptLanguageRow:
    episode: int
    revision: int | None
    final_present: bool
    nonspace_chars: int
    hangul_syllables: int
    non_korean_script_chars: int
    replacement_chars: int
    repeated_12grams: int
    review_status: str
    reference_status: str
    action: str
    publication_approved: bool = False


@dataclass(frozen=True)
class ManuscriptLanguageQueue:
    project_id: str = field(repr=False)
    through_episode: int = 0
    rows: tuple[ManuscriptLanguageRow, ...] = ()
    missing_final: int = 0
    below_target: int = 0
    script_review: int = 0
    repetition_review: int = 0
    fingerprint: str = field(default='', repr=False)
    status: str = 'AUTHOR_LITERARY_REVIEW_REQUIRED'
    publication_approved: bool = False


def _language_evidence(text: str) -> tuple[int, int, int, int, int]:
    """전체 원문을 분석하지만 원문을 반환하거나 영속 저장하지 않는다."""
    nonspace = 0
    hangul = 0
    foreign_script = 0
    replacement = 0
    for char in text:
        code = ord(char)
        if not char.isspace():
            nonspace += 1
        if 0xAC00 <= code <= 0xD7A3:
            hangul += 1
        if (0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF
                or 0x3040 <= code <= 0x30FF
                or 0x0400 <= code <= 0x052F):
            foreign_script += 1
        if char == '\ufffd' or category(char) == 'Cs':
            replacement += 1
    # 정확한 12자 반복 조각을 집계한다. 의도된 후렴/대사일 수 있으므로
    # 반복 자체를 오류나 불합격으로 판정하지 않는다.
    normalized = ''.join(c for c in text if not c.isspace())
    seen: set[str] = set()
    repeats = 0
    for i in range(max(0, len(normalized) - 11)):
        gram = normalized[i:i + 12]
        if gram in seen:
            repeats += 1
        else:
            seen.add(gram)
    return nonspace, hangul, foreign_script, replacement, repeats


def build_manuscript_language_queue(
    store: EpisodeStore, project_id: str, *, through_episode: int,
) -> ManuscriptLanguageQueue:
    """저장 1~N화 전수·기존 검수/참고작 기록의 변경을 함께 추적한다."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise ManuscriptLanguageQueueError('현재 작품과 1~1000화 범위를 선택하세요.')
    try:
        workflow = build_author_workflow_dependencies(
            store, project_id, through_episode=through_episode)
        saved = {ep.episode: ep for ep in store.list_episodes(project_id)
                 if ep.episode <= through_episode}
        rows = []
        evidence = []
        for chapter in workflow.chapters:
            ep = saved.get(chapter.episode)
            text = ep.final_text if ep is not None else ''
            counts = _language_evidence(text) if text.strip() else (0, 0, 0, 0, 0)
            length, hangul, script, replacement, repeats = counts
            if not text.strip():
                action = 'FINAL_MANUSCRIPT_REQUIRED'
            elif script or replacement:
                action = 'AUTHOR_SCRIPT_REVIEW_REQUIRED'
            elif length < TARGET_NONSPACE_CHARS:
                action = 'BELOW_5000_AUTHOR_REVISION'
            elif repeats:
                action = 'AUTHOR_REPETITION_REVIEW'
            else:
                action = 'AUTHOR_LITERARY_REVIEW_REQUIRED'
            rows.append(ManuscriptLanguageRow(
                chapter.episode, chapter.revision, bool(text.strip()),
                length, hangul, script, replacement, repeats,
                chapter.review_status, chapter.reference_status, action))
            checks = tuple((c.check_id, c.content_revision, c.category,
                            c.outcome, sha256(c.note.encode('utf-8')).hexdigest())
                           for c in store.list_checks(project_id, chapter.episode))
            evidence.append((chapter.episode, chapter.revision,
                             sha256(repr((ep.plot, ep.draft, ep.final_text,
                                          ep.summary)).encode('utf-8')).hexdigest()
                             if ep is not None else None,
                             chapter.review_status, chapter.reference_status,
                             checks, counts))
        if len(rows) != through_episode:
            raise ManuscriptLanguageQueueError('저장 회차 전수 조회가 누락됐습니다.')
        fingerprint = sha256(repr((project_id, through_episode,
                                   TARGET_NONSPACE_CHARS, tuple(evidence)))
                             .encode('utf-8')).hexdigest()
        return ManuscriptLanguageQueue(
            project_id=project_id, through_episode=through_episode,
            rows=tuple(rows),
            missing_final=sum(not row.final_present for row in rows),
            below_target=sum(row.final_present and row.nonspace_chars < TARGET_NONSPACE_CHARS
                             for row in rows),
            script_review=sum(bool(row.non_korean_script_chars or row.replacement_chars)
                              for row in rows),
            repetition_review=sum(bool(row.repeated_12grams) for row in rows),
            fingerprint=fingerprint)
    except ManuscriptLanguageQueueError:
        raise
    except (ValueError, OSError, LookupError, TypeError, AttributeError, UnicodeError):
        raise ManuscriptLanguageQueueError(
            '현재 저장 원고·QC·참고작 검수 기록을 읽지 못했습니다.') from None


def require_current_manuscript_language_queue(
    snapshot: ManuscriptLanguageQueue, store: EpisodeStore, project_id: str,
) -> None:
    """다른 기존 GUI로 이동하기 직전에 전체 원고·검수 지문을 재조회."""
    if (type(snapshot) is not ManuscriptLanguageQueue
            or snapshot.project_id != project_id):
        raise ManuscriptLanguageQueueError('작품이 변경됐습니다. 다시 조회하세요.')
    current = build_manuscript_language_queue(
        store, project_id, through_episode=snapshot.through_episode)
    if current.fingerprint != snapshot.fingerprint:
        raise ManuscriptLanguageQueueError(
            '원고·QC·수동 검수·참고작 기록이 변경됐습니다. 다시 조회하세요.')