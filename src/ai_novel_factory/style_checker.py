"""Stage 76 / ANF-REQ-053: explicit offline Style Bible checks.

Only well-defined rule keys are executable. Freeform advice remains unexamined,
not misrepresented as a machine-verifiable pass. Novel Bible overrides Style
Bible for matching keys. No NLP viewpoint inference, writer calls, or DB writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from .database.novel_bible import NovelBibleError, _id
from .database.style_bible import StyleBibleStore

MAX_MANUSCRIPT_CHARS = 1_000_000
MAX_FINDINGS = 1000
MAX_VIEWPOINT_CLAIMS = 500
_VIEWPOINTS = frozenset({'first_person', 'third_person_limited', 'third_person_omniscient'})
_FORBIDDEN = re.compile(r'forbidden_phrase_[a-z0-9_]{1,47}\Z')
_SUPPORTED = frozenset({'viewpoint', 'max_sentence_chars', 'max_paragraph_chars'})
_SENTENCES = re.compile(r'[^.!?。！？\n]+(?:[.!?。！？]+|(?=\n|\Z))')
_PARAGRAPHS = re.compile(r'\S(?:[^\n]|\n(?!\s*\n))*')


class StyleCheckerError(ValueError):
    """Safe errors must not reproduce user manuscripts or rule values."""


@dataclass(frozen=True)
class ViewpointClaim:
    start: int
    end: int
    evidence: str
    observed_viewpoint: str


@dataclass(frozen=True)
class StyleFinding:
    code: str
    rule_key: str
    source: str
    start: int
    end: int
    evidence_sha256: str


@dataclass(frozen=True)
class StyleReport:
    project_id: str
    episode_number: int
    project_revision: int
    manuscript_sha256: str
    applied_rules: tuple[str, ...]
    unexamined_rules: tuple[str, ...]
    viewpoint_claims_checked: int
    findings: tuple[StyleFinding, ...]
    status: str = 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC'
    persisted: bool = False
    publication_approved: bool = False

    @property
    def passed_checked_rules(self) -> bool:
        """Only machine-evaluable rules and supplied viewpoint labels are covered."""
        return not self.findings


def _digest(text: str) -> str:
    try:
        return sha256(text.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise StyleCheckerError('invalid unicode') from None


def _validate_text(text: object) -> str:
    if (type(text) is not str or not text.strip() or len(text) > MAX_MANUSCRIPT_CHARS or
            '\x00' in text or any(ord(ch) == 127 for ch in text)):
        raise StyleCheckerError('invalid manuscript')
    _digest(text)
    return text


def _int_rule(value: str) -> int:
    if not re.fullmatch(r'[1-9][0-9]{0,5}', value) or int(value) > MAX_MANUSCRIPT_CHARS:
        raise StyleCheckerError('invalid numeric style rule')
    return int(value)


def check_style(
    store: StyleBibleStore, project_id: str, episode_number: int, manuscript: str,
    viewpoint_claims: tuple[ViewpointClaim, ...] = (), *,
    expected_project_revision: int | None = None,
) -> StyleReport:
    """Check literal forbidden phrases, length bounds, and labelled viewpoint.

    Lengths count stripped Unicode code points, not bytes. Sentence segmentation
    is punctuation/newline-based and cannot understand abbreviations or dialogue.
    Findings contain offsets and hashes but no prose or forbidden expressions.
    """
    if not isinstance(store, StyleBibleStore):
        raise StyleCheckerError('invalid style store')
    try:
        project_id = _id(project_id)
    except NovelBibleError:
        raise StyleCheckerError('invalid project') from None
    if type(episode_number) is not int or not 1 <= episode_number <= 1_000_000:
        raise StyleCheckerError('invalid episode')
    manuscript = _validate_text(manuscript)
    if type(viewpoint_claims) is not tuple or len(viewpoint_claims) > MAX_VIEWPOINT_CLAIMS:
        raise StyleCheckerError('invalid viewpoint labels')
    if (expected_project_revision is not None and
            (type(expected_project_revision) is not int or
             not 0 <= expected_project_revision <= 2**31 - 1)):
        raise StyleCheckerError('invalid expected revision')
    try:
        revision = store.get_project(project_id).revision
        if expected_project_revision is not None and revision != expected_project_revision:
            raise StyleCheckerError('stale style snapshot')
        bible = {rule.key: rule.value for rule in store.list_rules(project_id)}
        style = {rule.key: rule.directive for rule in store.list_style_rules(project_id)}
        if not bible or not style:
            raise StyleCheckerError('missing Novel Bible or Style Bible')
        # All effective canon keys are included to preserve strict precedence.
        effective = {**style, **bible}
        applied: list[str] = []
        unexamined: list[str] = []
        findings: list[StyleFinding] = []
        seen_labels: set[tuple[int, int, str]] = set()
        for claim in viewpoint_claims:
            if (type(claim) is not ViewpointClaim or type(claim.start) is not int or
                    type(claim.end) is not int or
                    not 0 <= claim.start < claim.end <= len(manuscript) or
                    type(claim.evidence) is not str or not claim.evidence.strip() or
                    len(claim.evidence) > 4000 or
                    manuscript[claim.start:claim.end] != claim.evidence or
                    type(claim.observed_viewpoint) is not str or
                    claim.observed_viewpoint not in _VIEWPOINTS):
                raise StyleCheckerError('invalid viewpoint evidence')
            marker = (claim.start, claim.end, claim.observed_viewpoint)
            if marker in seen_labels:
                raise StyleCheckerError('duplicate viewpoint evidence')
            seen_labels.add(marker)
        def add(code: str, key: str, start: int, end: int) -> None:
            if len(findings) >= MAX_FINDINGS:
                raise StyleCheckerError('too many style findings')
            findings.append(StyleFinding(code, key,
                'novel_bible' if key in bible else 'style_bible',
                start, end, _digest(manuscript[start:end])))
        for key, value in sorted(effective.items()):
            if _FORBIDDEN.fullmatch(key):
                if not value.strip() or '\n' in value or '\r' in value:
                    raise StyleCheckerError('invalid forbidden phrase rule')
                applied.append(key)
                pos = 0
                while True:
                    found = manuscript.find(value, pos)
                    if found < 0:
                        break
                    add('FORBIDDEN_PHRASE', key, found, found + len(value))
                    pos = found + len(value)  # non-overlapping literal matches
            elif key == 'max_sentence_chars':
                limit = _int_rule(value)
                applied.append(key)
                for match in _SENTENCES.finditer(manuscript):
                    if len(match.group().strip()) > limit:
                        add('SENTENCE_TOO_LONG', key, match.start(), match.end())
            elif key == 'max_paragraph_chars':
                limit = _int_rule(value)
                applied.append(key)
                for match in _PARAGRAPHS.finditer(manuscript):
                    if len(match.group().strip()) > limit:
                        add('PARAGRAPH_TOO_LONG', key, match.start(), match.end())
            elif key == 'viewpoint':
                if value not in _VIEWPOINTS:
                    unexamined.append(key)  # free-form '3인칭 제한' not parsed as machine code
                    continue
                applied.append(key)
                for claim in viewpoint_claims:
                    if claim.observed_viewpoint != value:
                        add('VIEWPOINT_CONFLICT', key, claim.start, claim.end)
                if not viewpoint_claims:
                    unexamined.append('viewpoint_evidence_missing')
            elif key in style or key in _SUPPORTED or _FORBIDDEN.fullmatch(key):
                unexamined.append(key)
        if not applied:
            unexamined.append('no_executable_style_rules')
        if store.get_project(project_id).revision != revision:
            raise StyleCheckerError('style snapshot changed during check')
        return StyleReport(project_id, episode_number, revision, _digest(manuscript),
                           tuple(applied), tuple(unexamined), len(viewpoint_claims),
                           tuple(findings))
    except StyleCheckerError:
        raise
    except (NovelBibleError, ValueError, TypeError, OverflowError):
        raise StyleCheckerError('style data could not be checked') from None


def check_episode_style(
    store: StyleBibleStore, preview: object,
    viewpoint_claims: tuple[ViewpointClaim, ...] = (), *,
    expected_project_revision: int | None = None,
) -> StyleReport:
    """Check a stage-65 preview only if immutable scene provenance is intact."""
    from .episode_assembler import EpisodeDraftPreview, SceneSpan
    if (type(preview) is not EpisodeDraftPreview or
            preview.status != 'DRAFT_REQUIRES_USER_APPROVAL' or
            preview.persisted is not False or preview.publication_approved is not False or
            type(preview.draft) is not str or
            _digest(preview.draft) != preview.draft_sha256 or
            type(preview.scenes) is not tuple or not preview.scenes):
        raise StyleCheckerError('invalid episode draft')
    start = 0
    for i, span in enumerate(preview.scenes):
        if (type(span) is not SceneSpan or type(span.start) is not int or
                type(span.end) is not int or span.start != start or
                not 0 <= span.start < span.end <= len(preview.draft) or
                _digest(preview.draft[span.start:span.end]) != span.draft_sha256):
            raise StyleCheckerError('invalid scene provenance')
        start = span.end
        if i != len(preview.scenes) - 1:
            if preview.draft[start:start + 2] != '\n\n':
                raise StyleCheckerError('invalid scene separator')
            start += 2
    if start != len(preview.draft):
        raise StyleCheckerError('incomplete scene provenance')
    return check_style(store, preview.project_id, preview.episode_number, preview.draft,
                       viewpoint_claims, expected_project_revision=expected_project_revision)
