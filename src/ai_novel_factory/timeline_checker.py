"""Stage 73: evidence-linked, read-only Timeline chronology checker.

Checks *human-labelled* event mentions and explicit in-story order assertions
against one project's local EventTimelineStore. Manuscript order is NOT treated
as chronological order (flashbacks are possible). Unknown dates and broad day
intervals remain inconclusive. No NLP, network, manuscript persistence or approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from .database.event_timeline import EventTimelineStore, TimelineError, _interval, _when
from .database.novel_bible import NovelBibleError, _id

MAX_MANUSCRIPT_CHARS = 1_000_000
MAX_MENTIONS = 500
MAX_ORDER_CLAIMS = 500


class TimelineCheckerError(ValueError):
    """Safe errors; never echo manuscript text or canon descriptions."""


@dataclass(frozen=True)
class TimelineMention:
    """A reviewer-marked span mentioning an event and optionally its stated time.

    claimed_when is the reviewer's transcription/interpretation, not NLP.
    Use ISO day (YYYY-MM-DD) or timezone-aware ISO datetime; None means no
    date assertion at this span.
    """
    event_id: str
    start: int
    end: int
    evidence: str
    claimed_when: str | None = None


@dataclass(frozen=True)
class TimelineOrderClaim:
    """Reviewer states the first event happened strictly before the second."""
    before_event_id: str
    after_event_id: str


@dataclass(frozen=True)
class TimelineFinding:
    code: str  # TIME_CONFLICT, TIME_UNVERIFIABLE, ORDER_CONFLICT, ORDER_UNVERIFIABLE
    event_id: str
    related_event_id: str | None
    start: int | None
    end: int | None
    evidence_sha256: str | None


@dataclass(frozen=True)
class TimelineCheckReport:
    project_id: str
    episode_number: int
    project_revision: int
    manuscript_sha256: str
    examined_mentions: int
    examined_order_claims: int
    findings: tuple[TimelineFinding, ...]
    status: str = 'REQUIRES_HUMAN_REVIEW_NOT_FULL_QC'
    persisted: bool = False
    publication_approved: bool = False

    @property
    def passed_declared_claims(self) -> bool:
        """No reported issues in supplied claims only, NOT full text QC."""
        return not self.findings


def _digest(text: str) -> str:
    try:
        return sha256(text.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise TimelineCheckerError('invalid manuscript or evidence') from None


def _episode(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise TimelineCheckerError('invalid episode number')
    return value


def _intervals_overlap(left: tuple[datetime, datetime],
                       right: tuple[datetime, datetime]) -> bool:
    """A date is a half-open day; a timestamp is an exact point."""
    a, b = left
    c, d = right
    if a == b and c == d:
        return a == c
    if a == b:
        return c <= a < d
    if c == d:
        return a <= c < b
    return a < d and c < b


def _definite_order(a: tuple[datetime, datetime] | None,
                    b: tuple[datetime, datetime] | None) -> str:
    if a is None or b is None:
        return 'UNKNOWN'
    # Equal point times are simultaneous, not strictly ordered.
    if a[0] == a[1] and b[0] == b[1] and a[0] == b[0]:
        return 'NOT_BEFORE'
    # Half-open day end is strictly before an instant at next midnight.
    if a[1] <= b[0]:
        return 'BEFORE'
    if b[1] <= a[0]:
        return 'NOT_BEFORE'
    return 'UNKNOWN'


def check_timeline(
    store: EventTimelineStore, project_id: str, episode_number: int,
    manuscript: str, mentions: tuple[TimelineMention, ...],
    order_claims: tuple[TimelineOrderClaim, ...] = (),
    *, expected_project_revision: int | None = None,
) -> TimelineCheckReport:
    """Read-only verification of explicitly labelled event/time/order claims.

    Rejects unknown/cross-project event IDs and stale revisions. Checks date
    conflicts only when two time intervals are provably disjoint. Uses declared
    Timeline precedence, derived relative offsets and absolute dates for order;
    missing/ambiguous information is reported as unverifiable, never passed.
    """
    if not isinstance(store, EventTimelineStore):
        raise TimelineCheckerError('invalid timeline store')
    try:
        project_id = _id(project_id)
    except NovelBibleError:
        raise TimelineCheckerError('invalid project identifier') from None
    episode_number = _episode(episode_number)
    if type(manuscript) is not str or not manuscript.strip() or len(manuscript) > MAX_MANUSCRIPT_CHARS:
        raise TimelineCheckerError('invalid manuscript')
    manuscript_sha = _digest(manuscript)
    if type(mentions) is not tuple or len(mentions) > MAX_MENTIONS:
        raise TimelineCheckerError('invalid timeline mentions')
    if type(order_claims) is not tuple or len(order_claims) > MAX_ORDER_CLAIMS:
        raise TimelineCheckerError('invalid timeline order claims')
    if expected_project_revision is not None and (type(expected_project_revision) is not int
            or not 0 <= expected_project_revision <= 2**31 - 1):
        raise TimelineCheckerError('invalid expected revision')
    try:
        revision = store.get_project(project_id).revision
        if expected_project_revision is not None and revision != expected_project_revision:
            raise TimelineCheckerError('stale timeline snapshot')
        store.audit(project_id)  # fail closed for corrupt/cyclic chronology
        events = {e.event_id: e for e in store.list_events(project_id)}
        positions: dict[str, tuple[str, int]] = {}
        intervals: dict[str, tuple[datetime, datetime] | None] = {}

        def resolve(uid: str) -> tuple[tuple[str, int], tuple[datetime, datetime] | None]:
            if uid in positions:
                return positions[uid], intervals[uid]
            event = events[uid]
            if event.anchor_event_id is not None:
                (root, offset), anchor_interval = resolve(event.anchor_event_id)
                new_offset = offset + event.offset_minutes
                interval = (tuple(t + timedelta(minutes=event.offset_minutes)
                                  for t in anchor_interval) if anchor_interval is not None else None)
                position = root, new_offset
            else:
                position = uid, 0
                interval = _interval(event.when) if event.when is not None else None
            positions[uid], intervals[uid] = position, interval
            return position, interval

        for uid in events:
            resolve(uid)
        findings: list[TimelineFinding] = []
        marked: set[str] = set()
        seen_mentions: set[tuple[str, int, int]] = set()
        evidence_for: dict[str, TimelineMention] = {}
        for mention in mentions:
            if type(mention) is not TimelineMention:
                raise TimelineCheckerError('invalid timeline mention')
            try:
                uid = _id(mention.event_id)
            except NovelBibleError:
                raise TimelineCheckerError('invalid timeline event identifier') from None
            if uid not in events:
                raise TimelineCheckerError('timeline event missing from project')
            if (type(mention.start) is not int or type(mention.end) is not int
                    or not 0 <= mention.start < mention.end <= len(manuscript)
                    or type(mention.evidence) is not str or not mention.evidence.strip()
                    or len(mention.evidence) > 4000
                    or manuscript[mention.start:mention.end] != mention.evidence):
                raise TimelineCheckerError('invalid manuscript evidence')
            marker = uid, mention.start, mention.end
            if marker in seen_mentions:
                raise TimelineCheckerError('duplicate timeline mention')
            seen_mentions.add(marker)
            marked.add(uid)
            evidence_for.setdefault(uid, mention)
            if mention.claimed_when is not None:
                try:
                    observed = _interval(_when(mention.claimed_when))
                except (TimelineError, ValueError, OverflowError, TypeError):
                    raise TimelineCheckerError('invalid claimed date or time') from None
                baseline = intervals[uid]
                code = ('TIME_UNVERIFIABLE' if baseline is None else
                        'TIME_CONFLICT' if not _intervals_overlap(baseline, observed) else None)
                if code:
                    findings.append(TimelineFinding(code, uid, None, mention.start,
                                                    mention.end, _digest(mention.evidence)))

        graph: dict[str, set[str]] = {uid: set() for uid in events}
        for row in store._db.execute(
            'SELECT before_id, after_id FROM bible_timeline_order WHERE project_id=?',
            (project_id,),
        ):
            graph[row['before_id']].add(row['after_id'])
        reachable: dict[str, set[str]] = {}

        def walk(uid: str) -> set[str]:
            if uid not in reachable:
                found: set[str] = set()
                for target in graph[uid]:
                    found.add(target)
                    found.update(walk(target))
                reachable[uid] = found
            return reachable[uid]

        for uid in events:
            walk(uid)
        seen_orders: set[tuple[str, str]] = set()
        for claim in order_claims:
            if type(claim) is not TimelineOrderClaim:
                raise TimelineCheckerError('invalid order claim')
            try:
                first, second = _id(claim.before_event_id), _id(claim.after_event_id)
            except NovelBibleError:
                raise TimelineCheckerError('invalid order claim identifiers') from None
            if first not in marked or second not in marked:
                raise TimelineCheckerError('order claim requires cited event mentions')
            if (first, second) in seen_orders:
                raise TimelineCheckerError('duplicate order claim')
            seen_orders.add((first, second))
            if first == second:
                result = 'NOT_BEFORE'
            elif second in reachable[first]:
                result = 'BEFORE'
            elif first in reachable[second]:
                result = 'NOT_BEFORE'
            elif positions[first][0] == positions[second][0]:
                a, b = positions[first][1], positions[second][1]
                result = 'BEFORE' if a < b else 'NOT_BEFORE' if a >= b else 'UNKNOWN'
            else:
                result = _definite_order(intervals[first], intervals[second])
            if result != 'BEFORE':
                evidence = evidence_for[first]
                findings.append(TimelineFinding(
                    'ORDER_CONFLICT' if result == 'NOT_BEFORE' else 'ORDER_UNVERIFIABLE',
                    first, second, evidence.start, evidence.end, _digest(evidence.evidence)))
        if store.get_project(project_id).revision != revision:
            raise TimelineCheckerError('timeline changed during check')
        return TimelineCheckReport(project_id, episode_number, revision, manuscript_sha,
                                   len(mentions), len(order_claims), tuple(findings))
    except TimelineCheckerError:
        raise
    except (TimelineError, NovelBibleError, TypeError, ValueError, OverflowError,
            KeyError, RecursionError):
        raise TimelineCheckerError('timeline lookup failed') from None


def check_episode_timeline(
    store: EventTimelineStore, preview: object,
    mentions: tuple[TimelineMention, ...], order_claims: tuple[TimelineOrderClaim, ...] = (),
    *, expected_project_revision: int | None = None,
) -> TimelineCheckReport:
    """Check a stage-65 unsigned/unpersisted EpisodeDraftPreview."""
    from .episode_assembler import EpisodeDraftPreview

    if (type(preview) is not EpisodeDraftPreview
            or preview.status != 'DRAFT_REQUIRES_USER_APPROVAL'
            or preview.persisted is not False
            or preview.publication_approved is not False
            or type(preview.draft) is not str or not preview.draft.strip()
            or len(preview.draft) > MAX_MANUSCRIPT_CHARS
            or type(preview.draft_sha256) is not str
            or preview.draft_sha256 != _digest(preview.draft)):
        raise TimelineCheckerError('invalid or altered episode draft')
    return check_timeline(store, preview.project_id, preview.episode_number,
                          preview.draft, mentions, order_claims,
                          expected_project_revision=expected_project_revision)
