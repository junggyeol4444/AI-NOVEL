"""Stage 78: explicit local similarity review receipts, without manuscript text.

Saving a receipt is an explicit opt-in operation. It is NOT approval or
publication. A later caller must recompute similarity before trusting a receipt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .reference_similarity_checker import (
    ReferenceSimilarityReport, ReferenceSimilarityError,
    check_reference_similarity,
)


@dataclass(frozen=True)
class ReviewReceipt:
    project_id: str
    episode_number: int
    draft_sha256: str
    reference_set_sha256: str
    status: str
    recorded_at: str
    manuscript_approved: bool = False
    publication_approved: bool = False


def _reference_set_digest(report: ReferenceSimilarityReport) -> str:
    # Order-independent, but binds each source ID to the checked extracted text.
    items = sorted(zip(report.reference_ids, report.reference_text_sha256))
    return sha256(json.dumps(items, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


class ReferenceSimilarityReviewStore:
    """Local SQLite-only opt-in audit; never contains original manuscript prose."""

    def __init__(self, path: str | Path = ':memory:'):
        if isinstance(path, Path):
            path = str(path)
        if (type(path) is not str or not path or '\x00' in path or
                (path != ':memory:' and not Path(path).parent.is_dir())):
            raise ReferenceSimilarityError('invalid local review database')
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute('''CREATE TABLE IF NOT EXISTS similarity_review (
            project_id TEXT NOT NULL,
            episode_number INTEGER NOT NULL,
            draft_sha256 TEXT NOT NULL,
            reference_set_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY(project_id, episode_number, draft_sha256, reference_set_sha256)
        )''')

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def record(self, report: ReferenceSimilarityReport) -> ReviewReceipt:
        if (type(report) is not ReferenceSimilarityReport or not report.registration_checked
                or report.status not in {'blocked', 'review', 'inconclusive', 'clear'}
                or report.persisted is not False or report.manuscript_approved is not False
                or report.publication_approved is not False
                or not report.reference_ids or len(report.reference_ids) != len(report.reference_text_sha256)
                or (report.status == 'clear' and report.unexamined)):
            raise ReferenceSimilarityError('invalid similarity review report')
        fingerprint = _reference_set_digest(report)
        timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self._db:
            self._db.execute('''INSERT INTO similarity_review
                (project_id, episode_number, draft_sha256, reference_set_sha256, status, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, episode_number, draft_sha256, reference_set_sha256)
                DO UPDATE SET status=excluded.status, recorded_at=excluded.recorded_at''',
                (report.project_id, report.episode_number, report.draft_sha256,
                 fingerprint, report.status, timestamp))
        return ReviewReceipt(report.project_id, report.episode_number, report.draft_sha256,
                             fingerprint, report.status, timestamp)

    def require_current_clear_review(self, project_id, episode_number, manuscript, *,
                                     references, draft_scenes, draft_beats,
                                     required_reference_ids, catalog) -> ReviewReceipt:
        """Re-run against current inputs AND require a matching recorded clear result.

        Does not finalize/approve anything; stage 89 must implement the actual
        user approval gate and independently check the reference selection.
        """
        report = check_reference_similarity(
            project_id, episode_number, manuscript, references=references,
            draft_scenes=draft_scenes, draft_beats=draft_beats,
            required_reference_ids=required_reference_ids, catalog=catalog,
        )
        if not report.passed_checked_scope or not report.registration_checked:
            raise ReferenceSimilarityError('reference similarity review required')
        row = self._db.execute('''SELECT * FROM similarity_review WHERE
            project_id=? AND episode_number=? AND draft_sha256=? AND reference_set_sha256=?''',
            (report.project_id, report.episode_number, report.draft_sha256,
             _reference_set_digest(report))).fetchone()
        if row is None or row['status'] != 'clear':
            raise ReferenceSimilarityError('matching clear review record required')
        return ReviewReceipt(**dict(row))
