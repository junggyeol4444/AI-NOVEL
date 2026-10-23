"""Opt-in final-manuscript comparison against ALL author-selected local references.

This is a development-only bridge for the existing reference-batch checker.
Raw reference prose stays in process memory during the scan. It is not written
into the novel SQLite, QC notes, AI prompts, logs or network requests.

A scan does not approve publication or assert copyright clearance. In
particular, the existing checker cannot inspect unannotated semantic beats,
so an unflagged scan remains WARN / CHECKED_SCOPE_ONLY, never automatic PASS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Callable

from .database.episodes import EpisodeStore
from .reference_batch_context import (
    prepare_reference_batch, review_batch_draft, verify_reference_batch,
)
from .reference_intake_plan import (
    ReferenceIntakePlan, plan_reference_intake, require_current_intake,
)


class FinalReferenceAuditError(ValueError):
    """Do not expose source text, original manuscripts or private paths."""


@dataclass(frozen=True)
class FinalEpisodeReferenceResult:
    episode: int
    revision: int
    final_sha256: str = field(repr=False)
    status: str = 'NOT_RUN'
    selected_count: int = 0
    compared_count: int = 0
    flagged: bool = False
    manuscript_approved: bool = False
    publication_approved: bool = False


@dataclass(frozen=True)
class FinalReferenceAudit:
    project_id: str = field(repr=False)
    selected_fingerprint: str = field(repr=False)
    through_episode: int
    selected_count: int
    results: tuple[FinalEpisodeReferenceResult, ...]
    status: str = 'CHECKED_SCOPE_ONLY'
    publication_approved: bool = False

    @property
    def missing(self) -> tuple[int, ...]:
        return tuple(row.episode for row in self.results if row.status == 'MISSING_FINAL')

    @property
    def flagged(self) -> tuple[int, ...]:
        return tuple(row.episode for row in self.results if row.flagged)


def _hash_final(value: str) -> str:
    return sha256(value.encode('utf-8', 'surrogatepass')).hexdigest()


def audit_saved_final_references(
    database_path: str | Path, project_id: str, *,
    selected_paths: tuple[str, ...], catalog_path: str | Path,
    through_episode: int, progress: Callable[[int], None] | None = None,
) -> tuple[FinalReferenceAudit, ReferenceIntakePlan]:
    """Read all final texts in [1, through_episode]; never silently skip gaps.

    The author must explicitly approve calling this function. Catalog writes
    are confined to the separate local reference statistics database.
    """
    if (type(through_episode) is not int or not 1 <= through_episode <= 1000
            or type(project_id) is not str or not project_id):
        raise FinalReferenceAuditError('검사할 작품 또는 회차 범위를 확인할 수 없습니다.')
    database_path = Path(database_path)
    if not database_path.is_absolute() or not database_path.is_file():
        raise FinalReferenceAuditError('기존 로컬 작품 SQLite를 먼저 선택해야 합니다.')
    if progress is not None and not callable(progress):
        raise FinalReferenceAuditError('검사 진행 알림 형식이 올바르지 않습니다.')
    intake = plan_reference_intake(selected_paths)
    batch = prepare_reference_batch(
        selected_paths, catalog_path=catalog_path,
        manuscript_database_path=database_path)
    if len(batch.references) != len(intake.entries):
        raise FinalReferenceAuditError('선택한 참고작 전체를 분석하지 못했습니다.')
    rows: list[FinalEpisodeReferenceResult] = []
    with EpisodeStore(database_path) as store:
        store.get_project(project_id)
        saved = {row.episode: row for row in store.list_episodes(project_id)}
        for number in range(1, through_episode + 1):
            require_current_intake(intake, selected_paths)
            episode = saved.get(number)
            if episode is None or not episode.final_text.strip():
                rows.append(FinalEpisodeReferenceResult(
                    number, episode.revision if episode else 0,
                    status='MISSING_FINAL', selected_count=len(batch.references)))
            else:
                before = _hash_final(episode.final_text)
                review = review_batch_draft(
                    batch, project_id, number, episode.final_text,
                    (episode.final_text,))
                current = store.get_episode(project_id, number)
                if (current.revision != episode.revision
                        or _hash_final(current.final_text) != before):
                    raise FinalReferenceAuditError(
                        '검사 도중 최종 원고가 변경되었습니다. 결과를 폐기했습니다.')
                # The comparison library reports only its checked scope. It
                # does not have author-annotated source beats/scene boundaries.
                rows.append(FinalEpisodeReferenceResult(
                    number, episode.revision, before,
                    'FLAGGED' if review.blocked else 'CHECKED_SCOPE_ONLY',
                    len(batch.references), len(batch.references), review.blocked))
            if progress is not None:
                progress(number)
        verify_reference_batch(batch)
        require_current_intake(intake, selected_paths)
        # Reopen for a fresh view; reject results if any saved final changed.
        with EpisodeStore(database_path) as latest:
            for result in rows:
                if result.status == 'MISSING_FINAL':
                    try:
                        new = latest.get_episode(project_id, result.episode)
                    except ValueError:
                        continue
                    if new.final_text.strip():
                        raise FinalReferenceAuditError('검사 중 최종 원고가 추가되었습니다.')
                else:
                    new = latest.get_episode(project_id, result.episode)
                    if (new.revision != result.revision
                            or _hash_final(new.final_text) != result.final_sha256):
                        raise FinalReferenceAuditError('검사 중 최종 원고가 변경되었습니다.')
    status = ('INCOMPLETE' if any(r.status == 'MISSING_FINAL' for r in rows)
              else 'FLAGGED' if any(r.flagged for r in rows)
              else 'CHECKED_SCOPE_ONLY')
    return (FinalReferenceAudit(project_id, intake.fingerprint, through_episode,
                                len(batch.references), tuple(rows), status), intake)


def save_explicit_final_reference_qc(
    store: EpisodeStore, project_id: str, result: FinalEpisodeReferenceResult,
    *, intake: ReferenceIntakePlan, selected_paths: tuple[str, ...],
    explicit_author_record: bool,
):
    """Optional *separate* author click to record scoped evidence in SQLite.

    Never stores reference prose or awards PASS. Fails closed on any stale
    source, selection, project or manuscript revision.
    """
    if explicit_author_record is not True:
        raise FinalReferenceAuditError('현재 회차 검사 기록 저장을 직접 승인해야 합니다.')
    if result.status not in {'FLAGGED', 'CHECKED_SCOPE_ONLY'}:
        raise FinalReferenceAuditError('미검사 또는 누락된 회차는 기록할 수 없습니다.')
    require_current_intake(intake, selected_paths)
    if intake.fingerprint == '' or result.selected_count != len(intake.entries):
        raise FinalReferenceAuditError('참고작 전수 검사 범위를 확인할 수 없습니다.')
    current = store.get_episode(project_id, result.episode)
    if (current.revision != result.revision or not current.final_text.strip()
            or _hash_final(current.final_text) != result.final_sha256):
        raise FinalReferenceAuditError('최종본이 변경되어 검사 기록을 저장하지 않았습니다.')
    # Existing EpisodeStore.add_check enforces expected_revision atomically.
    # Explicit WARN is mandatory even when the scoped lexical check was clear.
    outcome = 'FAIL' if result.flagged else 'WARN'
    note = (f'final_reference_scope=checked_only;selected={result.selected_count};'
            f'compared={result.compared_count};final_sha256={result.final_sha256};'
            f'selection_sha256={intake.fingerprint};'
            'human_review_required=true;publication_approved=false')
    return store.add_check(project_id, result.episode, 'reference_similarity',
                           outcome, note, expected_revision=result.revision)
