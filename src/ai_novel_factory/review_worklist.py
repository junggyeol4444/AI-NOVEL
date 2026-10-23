"""Manual review worklist for the existing AI Novel Factory episode store.

Only consumes the project's saved episodes and their real persisted checks.
This is a *development feature*, not literary acceptance, automated sign-off,
publication permission or a similarity clearance. It does not mutate SQLite,
invoke a model, upload a manuscript or launch any external API.
"""
from __future__ import annotations

from dataclasses import dataclass

from .database.episodes import EpisodeStore

# These are existing QC categories used by the real multi-episode draft path.
# A missing or stale record is NOT a PASS even if earlier synthetic tests pass.
EXPECTED_CHECKS = (
    'length', 'repetition', 'korean_format', 'reference_similarity',
    'cross_episode_sentence_reuse', 'continuity', 'logic', 'timeline',
    'foreshadowing', 'reader_simulation',
)


@dataclass(frozen=True)
class EpisodeReviewStatus:
    episode: int
    revision: int
    draft_present: bool
    final_present: bool
    missing_checks: tuple[str, ...]
    stale_checks: tuple[str, ...]
    pending_checks: tuple[str, ...]
    failed_checks: tuple[str, ...]
    passed_checks: tuple[str, ...]
    # A saved final text is not proof of publication permission.
    publication_approved: bool = False

    @property
    def needs_human_review(self) -> bool:
        return (not self.final_present or bool(self.missing_checks)
                or bool(self.stale_checks) or bool(self.pending_checks)
                or bool(self.failed_checks))

    @property
    def review_label(self) -> str:
        if not self.draft_present and not self.final_present:
            return '본문 미완성'
        if self.failed_checks:
            return '검사 실패 · 수동 검토 필요'
        if self.missing_checks or self.stale_checks or self.pending_checks:
            return '검사 누락/미완료 · 수동 검토 필요'
        if not self.final_present:
            return '최종본 미저장 · 수동 검수 필요'
        return '검사기록 있음 · 출판 별도 승인 필요'


@dataclass(frozen=True)
class ReviewWorklist:
    project_id: str
    chapters: tuple[EpisodeReviewStatus, ...]
    incomplete_count: int
    review_required_count: int
    publication_approved: bool = False


def get_review_worklist(store: EpisodeStore, project_id: str) -> ReviewWorklist:
    """Read an existing project's stored review status without side effects.

    Real check data are tied to their content revision. A past PASS cannot
    satisfy a later edited manuscript. Repeated categories only count as PASS
    if their newest current-revision record is PASS; historical passes are not
    promoted. No original story, file path, or check note is returned to UI.
    """
    if not isinstance(store, EpisodeStore):
        raise ValueError('기존 로컬 회차 저장소가 필요합니다.')
    episodes = store.list_episodes(project_id)
    result = []
    expected = set(EXPECTED_CHECKS)
    for episode in episodes:
        saved_checks = store.list_checks(project_id, episode.episode)
        current = {}
        seen_old = set()
        for check in saved_checks:
            if check.category not in expected:
                continue
            if check.content_revision != episode.revision:
                seen_old.add(check.category)
                continue
            # The database orders records; the latest is authoritative.
            current[check.category] = check.outcome
        missing = tuple(c for c in EXPECTED_CHECKS
                        if c not in current and c not in seen_old)
        stale = tuple(c for c in EXPECTED_CHECKS
                      if c not in current and c in seen_old)
        pending = tuple(c for c in EXPECTED_CHECKS
                        if current.get(c) in ('WARN', 'NOT_RUN'))
        failed = tuple(c for c in EXPECTED_CHECKS
                       if current.get(c) == 'FAIL')
        passed = tuple(c for c in EXPECTED_CHECKS
                       if current.get(c) == 'PASS')
        result.append(EpisodeReviewStatus(
            episode=episode.episode, revision=episode.revision,
            draft_present=bool(episode.draft.strip()),
            final_present=bool(episode.final_text.strip()),
            missing_checks=missing, stale_checks=stale,
            pending_checks=pending, failed_checks=failed,
            passed_checks=passed))
    chapters = tuple(result)
    return ReviewWorklist(
        project_id=project_id, chapters=chapters,
        incomplete_count=sum(not (s.draft_present or s.final_present)
                             for s in chapters),
        review_required_count=sum(s.needs_human_review for s in chapters),
    )
