"""Evidence-only side-by-side screen for a *proposed* local novel rewrite.

This is part of the actual author-clicked GGUF rewrite workspace, not a
batch test, publication approval, automatic copy editor or semantic plagiarism
detector. The input is the real saved draft and local GGUF candidate, not
reference-novel prose. Earlier episodes are read from the original SQLite
store and never changed or sent to the model by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .database.episodes import EpisodeStore
from .episode_crosscheck import screen_cross_episode_reuse
from .korean_draft_quality import screen_korean_draft


class RewriteEvidenceError(ValueError):
    """Sanitized: never echo the author's manuscript or source paths."""


@dataclass(frozen=True)
class RewriteEvidenceRow:
    metric: str
    original_value: str
    proposed_value: str
    interpretation: str = 'AUTHOR_REVIEW_ONLY'


@dataclass(frozen=True)
class RewriteCandidateEvidence:
    project_id: str
    episode: int
    source_revision: int
    original_sha256: str
    proposed_sha256: str
    previous_episodes_examined: int
    previous_episodes_missing: int
    previous_episodes_unexamined: int
    rows: tuple[RewriteEvidenceRow, ...]
    status: str = 'EVIDENCE_ONLY_HUMAN_REVIEW_REQUIRED'
    full_literary_quality_verified: bool = False
    semantic_originality_verified: bool = False
    reference_similarity_cleared: bool = False
    publication_approved: bool = False


def compare_actual_rewrite(
    store: EpisodeStore, project_id: str, episode: int,
    saved_original: str, proposed: str, *,
    target_chars: int = 5000, prior_limit: int = 250,
) -> RewriteCandidateEvidence:
    """Compare two manuscripts against SAME original saved SQLite context.

    Full earlier saved-draft/final text is kept local. A missing or too-long
    chapter is explicit; the output does not label an unknown as PASS.
    Numeric changes may be adverse even if the proposed text is longer.
    """
    if (not isinstance(store, EpisodeStore)
            or type(project_id) is not str or not project_id
            or type(episode) is not int or not 1 <= episode <= 1000
            or type(saved_original) is not str or not saved_original.strip()
            or type(proposed) is not str or not proposed.strip()
            or type(target_chars) is not int or not 100 <= target_chars <= 50000
            or type(prior_limit) is not int or not 1 <= prior_limit <= 250
            or len(saved_original) > 100000 or len(proposed) > 100000):
        raise RewriteEvidenceError('실제 저장 초고와 수정 후보의 비교 범위가 올바르지 않습니다.')
    row = store.get_episode(project_id, episode)
    if row.draft != saved_original:
        raise RewriteEvidenceError('비교 전에 원본 초고가 변경되었습니다.')
    before = screen_korean_draft(saved_original, target_chars=target_chars)
    after = screen_korean_draft(proposed, target_chars=target_chars)
    first = max(1, episode - prior_limit)
    expected = tuple(range(first, episode))
    rows_by_episode = {
        item.episode: item for item in store.list_episodes(project_id)
        if first <= item.episode < episode}
    comparison = []
    missing = 0
    unexamined = 0
    for n in expected:
        old = rows_by_episode.get(n)
        if old is None:
            missing += 1
            continue
        final = old.final_text or ''
        draft = old.draft or ''
        text = final if final.strip() else draft
        if not text.strip() or len(text) > 100000:
            unexamined += 1
            continue
        comparison.append(text)
    original_cross = screen_cross_episode_reuse(
        saved_original, tuple(comparison))
    proposed_cross = screen_cross_episode_reuse(
        proposed, tuple(comparison))
    def add(metric: str, old: object, new: object) -> RewriteEvidenceRow:
        return RewriteEvidenceRow(metric, str(old), str(new))
    results = (
        add('공백 제외 실제 글자', before.nonspace_chars, after.nonspace_chars),
        add('한글 음절', before.hangul_syllables, after.hangul_syllables),
        add('한글 비율', before.hangul_share, after.hangul_share),
        add('동일 문장 비율', before.repeated_sentence_share,
            after.repeated_sentence_share),
        add('동일 어절 묶음 비율', before.repeated_chunk_share,
            after.repeated_chunk_share),
        add('형식 표시 후보 수', before.non_prose_markers, after.non_prose_markers),
        add('한자 글자 수', before.han_script_chars, after.han_script_chars),
        add('이전 저장 회차의 정확 동일 문장 수',
            original_cross.exact_sentence_reuses,
            proposed_cross.exact_sentence_reuses),
        add('동일 문장 발견된 이전 회차 수',
            original_cross.affected_prior_episodes,
            proposed_cross.affected_prior_episodes),
        add('한국어 형식 제한 충족(범위 한정)',
            before.format_gate_pass, after.format_gate_pass),
    )
    return RewriteCandidateEvidence(
        project_id=project_id, episode=episode,
        source_revision=row.revision,
        original_sha256=sha256(saved_original.encode('utf-8')).hexdigest(),
        proposed_sha256=sha256(proposed.encode('utf-8')).hexdigest(),
        previous_episodes_examined=len(comparison),
        previous_episodes_missing=missing,
        previous_episodes_unexamined=unexamined,
        rows=results)
