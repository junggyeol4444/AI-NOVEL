"""기존 SQLite의 장면·초고·최종본·QC를 회차별로 실제 대조하는 작가 화면 근거.

저장된 장면의 표현은 최종본에서 바뀔 수 있으므로 불일치가 곧 오류는 아니다.
검토 후보만 제시하며 사용자 원고·DB·참고작·승인 기록을 변경하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re

from .author_chapter_text_delta import compare_saved_draft_final
from .author_workflow_dependencies import build_author_workflow_dependencies
from .database.episodes import EpisodeStore


class SceneFinalAlignmentError(ValueError):
    """개인 원고·장면 본문·파일 경로를 포함하지 않는 오류."""


@dataclass(frozen=True)
class SceneFinalAlignmentRow:
    episode: int
    revision: int | None
    saved_scene_count: int
    exact_scene_count: int
    rewritten_or_missing_scene_count: int
    order_review_count: int
    draft_retained_percent: int
    draft_changed_paragraphs: int
    final_new_paragraphs: int
    final_nonspace_chars: int
    review_status: str
    reference_status: str
    next_action: str
    publication_approved: bool = False


@dataclass(frozen=True)
class SceneFinalAlignment:
    project_id: str = field(repr=False)
    through_episode: int = 0
    rows: tuple[SceneFinalAlignmentRow, ...] = ()
    missing_final: int = 0
    scenes_needing_comparison: int = 0
    chapters_without_scenes: int = 0
    fingerprint: str = field(default='', repr=False)
    status: str = 'AUTHOR_SCENE_FINAL_REVIEW_REQUIRED'
    publication_approved: bool = False


def _compact(text: str) -> str:
    return re.sub(r'\s+', '', text)


def _scene_alignment(scenes, final_text: str) -> tuple[int, int, int]:
    """저장 장면의 공백 제외 원문이 최종본에 등장하는지 순서대로 조회."""
    normalized_final = _compact(final_text)
    exact = out_of_order = 0
    previous = -1
    for scene in scenes:
        candidate = _compact(scene.text)
        if not candidate:
            continue
        offset = normalized_final.find(candidate)
        if offset < 0:
            continue
        exact += 1
        if offset < previous:
            out_of_order += 1
        previous = max(previous, offset)
    return exact, len(scenes) - exact, out_of_order


def build_scene_final_alignment(
    store: EpisodeStore, project_id: str, *, through_episode: int,
) -> SceneFinalAlignment:
    """1~N화 전체를 빠짐없이 읽고 현재 revision·검수 지문을 묶는다."""
    if (not isinstance(store, EpisodeStore) or type(project_id) is not str
            or not project_id or type(through_episode) is not int
            or not 1 <= through_episode <= 1000):
        raise SceneFinalAlignmentError('기존 작품과 1~1000화 범위를 직접 선택하세요.')
    try:
        workflow = build_author_workflow_dependencies(
            store, project_id, through_episode=through_episode)
        saved = {item.episode: item for item in store.list_episodes(project_id)}
        rows = []
        evidence = []
        for chapter in workflow.chapters:
            episode = saved.get(chapter.episode)
            if episode is None:
                rows.append(SceneFinalAlignmentRow(
                    chapter.episode, None, 0, 0, 0, 0, 0, 0, 0, 0,
                    chapter.review_status, chapter.reference_status,
                    'CREATE_SAVED_EPISODE'))
                evidence.append((chapter.episode, None))
                continue
            scenes = store.list_scenes(project_id, chapter.episode)
            exact, missing, order = _scene_alignment(scenes, episode.final_text)
            delta = compare_saved_draft_final(episode.draft, episode.final_text)
            if not episode.final_text.strip():
                action = 'WRITE_OR_REVIEW_FINAL'
            elif not scenes:
                action = 'AUTHOR_SCENE_PLAN_REVIEW'
            elif missing or order:
                action = 'AUTHOR_SCENE_TEXT_COMPARISON'
            else:
                action = 'AUTHOR_MANUAL_COMPARISON_REQUIRED'
            rows.append(SceneFinalAlignmentRow(
                chapter.episode, episode.revision, len(scenes), exact, missing,
                order, delta.retained_percent, delta.removed_or_rewritten,
                delta.new_or_rewritten, delta.final_nonspace_chars,
                chapter.review_status, chapter.reference_status, action))
            checks = tuple((c.check_id, c.category, c.outcome,
                            c.content_revision, sha256(c.note.encode('utf-8')).hexdigest())
                           for c in store.list_checks(project_id, chapter.episode))
            evidence.append((
                chapter.episode, episode.revision,
                tuple(sha256(getattr(episode, field).encode('utf-8')).hexdigest()
                      for field in ('plot', 'draft', 'final_text', 'summary')),
                tuple((scene.scene_id, scene.position, scene.updated_at,
                       sha256(scene.text.encode('utf-8')).hexdigest())
                      for scene in scenes),
                checks, chapter.review_status, chapter.reference_status,
                exact, missing, order, delta.retained_paragraphs))
        if len(rows) != through_episode:
            raise SceneFinalAlignmentError('회차 전수 대조가 누락됐습니다.')
        fingerprint = sha256(json.dumps(
            (project_id, through_episode, evidence), ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')).hexdigest()
        return SceneFinalAlignment(
            project_id, through_episode, tuple(rows),
            sum(row.revision is None or row.next_action == 'WRITE_OR_REVIEW_FINAL'
                for row in rows),
            sum(row.rewritten_or_missing_scene_count + row.order_review_count
                for row in rows),
            sum(row.revision is not None and row.saved_scene_count == 0
                for row in rows), fingerprint)
    except SceneFinalAlignmentError:
        raise
    except (ValueError, OSError, LookupError, TypeError, AttributeError, UnicodeError):
        raise SceneFinalAlignmentError(
            '현재 저장 원고·장면·QC·수동 검수·참고작 범위를 읽지 못했습니다.') from None


def require_current_scene_final_alignment(
    snapshot: SceneFinalAlignment, store: EpisodeStore, project_id: str,
) -> None:
    """작가가 다른 기존 화면으로 이동하기 직전에 전체 지문을 재확인."""
    if type(snapshot) is not SceneFinalAlignment or snapshot.project_id != project_id:
        raise SceneFinalAlignmentError('작품이 변경됐습니다. 다시 조회하세요.')
    current = build_scene_final_alignment(
        store, project_id, through_episode=snapshot.through_episode)
    if current.fingerprint != snapshot.fingerprint:
        raise SceneFinalAlignmentError(
            '원고·장면·QC·수동 검수·참고작 기록이 변경됐습니다. 다시 조회하세요.')

@dataclass(frozen=True)
class SceneEpisodeDetailRow:
    """선택 회차 저장 장면 원문과 현재 최종본의 문자 위치. 품질 판정 아님."""
    scene_id: str = field(repr=False)
    position: int = 0
    original_text: str = field(default='', repr=False)
    original_sha256: str = field(default='', repr=False)
    exact_literal: bool = False
    normalized_occurrences: int = 0
    first_start: int | None = None
    first_end: int | None = None
    order_review: bool = False


@dataclass(frozen=True)
class SceneEpisodeDetail:
    project_id: str = field(repr=False)
    episode: int = 0
    revision: int = 0
    draft_text: str = field(default='', repr=False)
    final_text: str = field(default='', repr=False)
    final_sha256: str = field(default='', repr=False)
    scenes: tuple[SceneEpisodeDetailRow, ...] = ()
    review_status: str = ''
    reference_status: str = ''
    next_action: str = ''
    source_fingerprint: str = field(default='', repr=False)
    publication_approved: bool = False


def read_scene_episode_detail(
    snapshot: SceneFinalAlignment, store: EpisodeStore, project_id: str, *,
    episode: int,
) -> SceneEpisodeDetail:
    """작가가 별도 선택한 저장 회차의 초고·장면·최종본 원문을 메모리에서만 대조.

    공백을 제거한 장면 검색 위치는 실제 최종본의 Python 문자 위치로 역매핑한다.
    첫 번째 등장만 위치로 보여 주며 복수 등장·순서 변경은 수동 검토 후보로 남긴다.
    """
    if (type(snapshot) is not SceneFinalAlignment or type(episode) is not int
            or not 1 <= episode <= snapshot.through_episode
            or not isinstance(store, EpisodeStore)
            or type(project_id) is not str or snapshot.project_id != project_id):
        raise SceneFinalAlignmentError('작품·회차를 다시 직접 선택하세요.')
    require_current_scene_final_alignment(snapshot, store, project_id)
    expected = snapshot.rows[episode - 1]
    if expected.episode != episode or expected.revision is None:
        raise SceneFinalAlignmentError('저장된 원고가 없는 회차입니다.')
    try:
        saved = store.get_episode(project_id, episode)
        scenes = store.list_scenes(project_id, episode)
        if saved.revision != expected.revision or len(scenes) != expected.saved_scene_count:
            raise SceneFinalAlignmentError('원고·장면 기록이 변경됐습니다. 다시 조회하세요.')
        # Python 문자열 오프셋으로 매핑하며 Qt UTF-16 커서 위치와 혼동하지 않는다.
        positions = [i for i, char in enumerate(saved.final_text) if not char.isspace()]
        compact_final = ''.join(saved.final_text[i] for i in positions)
        details = []
        exact = order = 0
        previous = -1
        for scene in scenes:
            candidate = _compact(scene.text)
            at = compact_final.find(candidate) if candidate else -1
            occurrences = compact_final.count(candidate) if candidate else 0
            reordered = at >= 0 and at < previous
            if at >= 0:
                exact += 1
                order += int(reordered)
                previous = max(previous, at)
            details.append(SceneEpisodeDetailRow(
                scene.scene_id, scene.position, scene.text,
                sha256(scene.text.encode('utf-8')).hexdigest(),
                bool(scene.text) and scene.text in saved.final_text,
                occurrences,
                positions[at] if at >= 0 else None,
                positions[at + len(candidate) - 1] + 1 if at >= 0 else None,
                reordered))
        if (exact != expected.exact_scene_count
                or len(scenes) - exact != expected.rewritten_or_missing_scene_count
                or order != expected.order_review_count):
            raise SceneFinalAlignmentError('저장 장면 대조 결과가 변경됐습니다. 다시 조회하세요.')
        # 저장 초고·최종본과 장면별 원문이 조회 도중 변경되지 않았는지 다시 확인.
        saved_again = store.get_episode(project_id, episode)
        scenes_again = store.list_scenes(project_id, episode)
        if saved_again != saved or scenes_again != scenes:
            raise SceneFinalAlignmentError('원고·장면 기록이 변경됐습니다. 다시 조회하세요.')
        require_current_scene_final_alignment(snapshot, store, project_id)
        return SceneEpisodeDetail(
            project_id, episode, saved.revision, saved.draft, saved.final_text,
            sha256(saved.final_text.encode('utf-8')).hexdigest(),
            tuple(details), expected.review_status, expected.reference_status,
            expected.next_action, snapshot.fingerprint)
    except SceneFinalAlignmentError:
        raise
    except (ValueError, OSError, LookupError, TypeError, AttributeError, UnicodeError):
        raise SceneFinalAlignmentError(
            '선택 회차의 저장 장면·초고·최종본을 다시 읽지 못했습니다.') from None
