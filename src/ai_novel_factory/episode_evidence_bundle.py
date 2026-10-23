"""Aggregate author-marked longform evidence using the project's existing checkers.

Development stage: no automatic claim extraction, canon mutation, model calls,
publication approval, reference-novel quotation, or filesystem writes.
Only *explicitly marked* evidence is examined. Unmarked prose is NOT cleared.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .continuity_checker import (
    ContinuityCanon, ManuscriptClaim, check_continuity,
)
from .database.character_knowledge import CharacterKnowledgeStore
from .database.foreshadow import ForeshadowStore
from .database.event_timeline import EventTimelineStore
from .knowledge_checker import KnowledgeUseClaim, check_character_knowledge
from .foreshadow_checker import ForeshadowClaim, check_foreshadowing
from .timeline_checker import TimelineMention, TimelineOrderClaim, check_timeline


class EvidenceBundleError(ValueError):
    """Content-free error; no private manuscript or reference passages."""


@dataclass(frozen=True)
class EvidenceAnnotations:
    canon_claims: tuple[ManuscriptClaim, ...] = ()
    knowledge_uses: tuple[KnowledgeUseClaim, ...] = ()
    foreshadow_claims: tuple[ForeshadowClaim, ...] = ()
    timeline_mentions: tuple[TimelineMention, ...] = ()
    timeline_orders: tuple[TimelineOrderClaim, ...] = ()


@dataclass(frozen=True)
class EvidenceSection:
    category: str
    examined: int
    findings: int
    finding_codes: tuple[str, ...]
    status: str  # NOT_EXAMINED / ISSUES_FOUND / DECLARED_CLAIMS_ONLY


@dataclass(frozen=True)
class EvidenceBundle:
    project_id: str
    episode: int
    project_revision: int
    manuscript_sha256: str
    sections: tuple[EvidenceSection, ...]
    status: str  # HUMAN_REVIEW_REQUIRED or EVIDENCE_INCOMPLETE
    publication_approved: bool = False
    full_manuscript_verified: bool = False


def evaluate_evidence_bundle(
    *, project_id: str, episode: int, manuscript: str,
    expected_manuscript_sha256: str, expected_project_revision: int,
    canon: ContinuityCanon, knowledge_store: CharacterKnowledgeStore,
    foreshadow_store: ForeshadowStore, timeline_store: EventTimelineStore,
    annotations: EvidenceAnnotations,
) -> EvidenceBundle:
    """Run four *existing* read-only structured checkers against one draft.

    Caller must supply stores for the same original project and DB, already
    opened through the existing application. Every checker checks the project
    revision, and all results must match the same manuscript and revision.
    A zero-claim section remains NOT_EXAMINED even if its checker has no issues.
    No report is persisted or converted to a QC PASS automatically.
    """
    if (type(project_id) is not str or type(episode) is not int
            or not 1 <= episode <= 1_000_000
            or type(manuscript) is not str or not manuscript.strip()
            or len(manuscript) > 1_000_000
            or type(expected_project_revision) is not int
            or type(expected_manuscript_sha256) is not str
            or type(annotations) is not EvidenceAnnotations
            or type(canon) is not ContinuityCanon
            or canon.project_id != project_id
            or canon.project_revision != expected_project_revision):
        raise EvidenceBundleError('검토할 회차 또는 설정 스냅샷이 올바르지 않습니다.')
    try:
        digest = sha256(manuscript.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise EvidenceBundleError('원고 인코딩이 올바르지 않습니다.') from None
    if digest != expected_manuscript_sha256:
        raise EvidenceBundleError('원고가 변경되어 근거 검토를 다시 해야 합니다.')
    if any(type(group) is not tuple for group in (
            annotations.canon_claims, annotations.knowledge_uses,
            annotations.foreshadow_claims, annotations.timeline_mentions,
            annotations.timeline_orders)):
        raise EvidenceBundleError('근거 묶음 형식이 올바르지 않습니다.')

    # Existing checkers enforce exact marked span/evidence matches and project
    # identity; do not catch their integrity errors and call them warnings.
    canon_result = check_continuity(
        canon, episode, manuscript, annotations.canon_claims,
        expected_project_revision=expected_project_revision)
    knowledge_result = check_character_knowledge(
        knowledge_store, project_id, episode, manuscript,
        annotations.knowledge_uses,
        expected_project_revision=expected_project_revision)
    foreshadow_result = check_foreshadowing(
        foreshadow_store, project_id, episode, manuscript,
        annotations.foreshadow_claims,
        expected_project_revision=expected_project_revision)
    timeline_result = check_timeline(
        timeline_store, project_id, episode, manuscript,
        annotations.timeline_mentions, annotations.timeline_orders,
        expected_project_revision=expected_project_revision)
    results = (
        ('continuity', canon_result, len(annotations.canon_claims)),
        ('character_knowledge', knowledge_result, len(annotations.knowledge_uses)),
        ('foreshadowing', foreshadow_result, len(annotations.foreshadow_claims)),
        ('timeline', timeline_result,
         len(annotations.timeline_mentions) + len(annotations.timeline_orders)),
    )
    sections = []
    for category, report, examined in results:
        if (report.project_id != project_id or report.episode_number != episode
                or report.project_revision != expected_project_revision
                or report.manuscript_sha256 != digest
                or report.persisted is not False
                or report.publication_approved is not False):
            raise EvidenceBundleError('근거 결과가 현재 원고와 일치하지 않습니다.')
        findings = tuple(report.findings)
        sections.append(EvidenceSection(
            category, examined, len(findings),
            tuple(sorted(set(item.code for item in findings))),
            ('NOT_EXAMINED' if not examined else
             'ISSUES_FOUND' if findings else 'DECLARED_CLAIMS_ONLY')))
    return EvidenceBundle(
        project_id, episode, expected_project_revision, digest, tuple(sections),
        'EVIDENCE_INCOMPLETE' if any(not section.examined for section in sections)
        else 'HUMAN_REVIEW_REQUIRED')
