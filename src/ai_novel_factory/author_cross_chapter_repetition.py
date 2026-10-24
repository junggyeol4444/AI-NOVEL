"""작가가 선택한 1~1000화 저장 최종본 사이의 장문 중복 검토 후보.

실제 원문을 로컬 메모리에서만 대조한다. 짧은 상투어는 제외하며,
문단 동일성과 긴 연속 문자열의 일부 표본이 다른 회차에 등장하는지
찾는다. 표본 검색은 전수 유사성/표절 검사나 문학 품질 판정이 아니다.
SQLite, QC, 참고작, 모델, 출판 상태를 수정하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re

from .author_workflow_dependencies import build_author_workflow_dependencies
from .database.episodes import EpisodeStore


class CrossChapterRepetitionError(ValueError):
    """사용자 원고와 개인 경로를 노출하지 않는 조회 오류."""


@dataclass(frozen=True)
class CrossChapterRepetitionRow:
    episode: int
    revision: int | None
    final_present: bool
    nonspace_chars: int
    identical_long_paragraphs: int
    repeated_long_windows: int
    related_episodes: tuple[int, ...]
    review_status: str
    reference_status: str
    action: str
    publication_approved: bool = False


@dataclass(frozen=True)
class CrossChapterRepetitionReport:
    project_id: str = field(repr=False)
    through_episode: int = 0
    rows: tuple[CrossChapterRepetitionRow, ...] = ()
    missing_final: int = 0
    paragraph_review_chapters: int = 0
    window_review_chapters: int = 0
    fingerprint: str = field(default='', repr=False)
    status: str = 'AUTHOR_CROSS_CHAPTER_REVIEW_REQUIRED'
    publication_approved: bool = False


def _compact(value: str) -> str:
    return re.sub(r'\s+', '', value)


def _long_paragraph_hashes(value: str) -> set[str]:
    """원문 줄/문단의 공백 차이만 정규화한 80자 이상 정확 일치 후보."""
    found = set()
    for paragraph in re.split(r'\n+', value):
        compact = _compact(paragraph)
        if len(compact) >= 80:
            found.add(sha256(compact.encode('utf-8')).hexdigest())
    return found


def _long_window_hashes(value: str) -> set[str]:
    """120자 장문 창을 회차당 최대 약 1000개 간격으로 표본 추출."""
    compact = _compact(value)
    if len(compact) < 120:
        return set()
    stride = max(40, (len(compact) - 120) // 999 + 1)
    offsets = range(0, len(compact) - 119, stride)
    found = {sha256(compact[pos:pos + 120].encode('utf-8')).hexdigest()
             for pos in offsets}
    # 마지막 장문도 포함하되 표본 방식이라는 사실을 명확히 유지한다.
    found.add(sha256(compact[-120:].encode('utf-8')).hexdigest())
    return found


def build_cross_chapter_repetition(
    store: EpisodeStore, project_id: str, *, through_episode: int,
) -> CrossChapterRepetitionReport:
    """1~N화 저장 최종본을 대조하고 QC/참고작 상태 변경도 추적한다."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise CrossChapterRepetitionError('현재 작품과 1~1000화 범위를 직접 선택하세요.')
    try:
        workflow = build_author_workflow_dependencies(
            store, project_id, through_episode=through_episode)
        saved = {ep.episode: ep for ep in store.list_episodes(project_id)
                 if ep.episode <= through_episode}
        paragraph_owner: dict[str, int] = {}
        window_owner: dict[str, int] = {}
        paragraph_counts = [0] * (through_episode + 1)
        window_counts = [0] * (through_episode + 1)
        related = [set() for _ in range(through_episode + 1)]
        evidence = []
        for chapter in workflow.chapters:
            number = chapter.episode
            ep = saved.get(number)
            text = ep.final_text if ep is not None else ''
            if text.strip():
                for digest in _long_paragraph_hashes(text):
                    other = paragraph_owner.setdefault(digest, number)
                    if other != number:
                        paragraph_counts[number] += 1
                        paragraph_counts[other] += 1
                        related[number].add(other)
                        related[other].add(number)
                for digest in _long_window_hashes(text):
                    other = window_owner.setdefault(digest, number)
                    if other != number:
                        window_counts[number] += 1
                        window_counts[other] += 1
                        related[number].add(other)
                        related[other].add(number)
            checks = tuple((check.check_id, check.content_revision,
                            check.category, check.outcome,
                            sha256(check.note.encode('utf-8')).hexdigest())
                           for check in store.list_checks(project_id, number)) if ep else ()
            evidence.append((number, ep.revision if ep else None,
                             tuple(sha256(getattr(ep, key).encode('utf-8')).hexdigest()
                                   for key in ('plot', 'draft', 'final_text', 'summary'))
                             if ep else (), chapter.review_status,
                             chapter.reference_status, chapter.remaining_actions,
                             checks))
        rows = []
        for chapter in workflow.chapters:
            number = chapter.episode
            ep = saved.get(number)
            text = ep.final_text if ep else ''
            if not text.strip():
                action = 'FINAL_MANUSCRIPT_REQUIRED'
            elif paragraph_counts[number] or window_counts[number]:
                action = 'AUTHOR_CROSS_CHAPTER_COMPARISON'
            else:
                action = 'AUTHOR_MANUAL_REVIEW_REQUIRED'
            rows.append(CrossChapterRepetitionRow(
                number, ep.revision if ep else None, bool(text.strip()),
                sum(not char.isspace() for char in text),
                paragraph_counts[number], window_counts[number],
                tuple(sorted(related[number])), chapter.review_status,
                chapter.reference_status, action))
        if len(rows) != through_episode:
            raise CrossChapterRepetitionError('저장 원고 회차 조회가 누락됐습니다.')
        fingerprint = sha256(json.dumps(
            (project_id, through_episode, evidence), ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')).hexdigest()
        return CrossChapterRepetitionReport(
            project_id, through_episode, tuple(rows),
            sum(not row.final_present for row in rows),
            sum(bool(row.identical_long_paragraphs) for row in rows),
            sum(bool(row.repeated_long_windows) for row in rows), fingerprint)
    except CrossChapterRepetitionError:
        raise
    except (ValueError, OSError, LookupError, TypeError, AttributeError, UnicodeError):
        raise CrossChapterRepetitionError(
            '현재 원고·QC·수동 검수·참고작 기록을 읽지 못했습니다.') from None


def require_current_cross_chapter_repetition(
    snapshot: CrossChapterRepetitionReport, store: EpisodeStore, project_id: str,
) -> None:
    """다른 GUI로 이동 직전에 모든 원고와 검수 근거를 다시 확인한다."""
    if (type(snapshot) is not CrossChapterRepetitionReport
            or snapshot.project_id != project_id):
        raise CrossChapterRepetitionError('작품이 변경됐습니다. 다시 조회하세요.')
    latest = build_cross_chapter_repetition(
        store, project_id, through_episode=snapshot.through_episode)
    if latest.fingerprint != snapshot.fingerprint:
        raise CrossChapterRepetitionError(
            '원고·QC·수동 검수·참고작 범위가 변경됐습니다. 다시 조회하세요.')
