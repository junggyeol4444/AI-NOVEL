"""Stage 95, ANF-REQ-066: extra *local* review for publisher assets.

This supplements, never replaces, stage 89 manuscript approval. It binds the
stage 92 metadata file and stage 94 titles/author-notes to the current draft
and current approval. All operations are local. NO official platform upload.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from uuid import uuid4

from .publication_metadata import load_metadata, MetadataError
from .publication_approval import PublicationApprovalStore, PublicationReviewEvidence
from .publisher_adapter import (
    PublisherDryRunPlan, PublisherMockReceipt, PublisherAdapterError,
    prepare_offline_publisher_plan, simulate_offline_upload,
)

_SHA = re.compile(r'[0-9a-f]{64}\Z')


class PublisherAssetReviewError(ValueError):
    """Never interpolate untrusted manuscript text, credentials or paths."""


@dataclass(frozen=True, slots=True)
class AssetReviewChallenge:
    review_id: str
    confirmation_code: str  # One-time caller-facing code; NEVER stored or logged.
    asset_fingerprint: str

    def confirmation(self) -> str:
        return f'CONFIRM-PUBLISHER-ASSETS {self.review_id} {self.confirmation_code}'


@dataclass(frozen=True, slots=True)
class AssetReviewReceipt:
    review_id: str
    project_id: str
    approval_request_id: str
    fingerprint: str
    status: str
    publication_executed: bool = False
    official_sandbox_upload_verified: bool = False


def _checked_binding(plan: PublisherDryRunPlan, directory: str | Path,
                     metadata_path: str | Path, expected_metadata_sha256: str,
                     approval_store: PublicationApprovalStore,
                     evidence: PublicationReviewEvidence) -> str:
    if (type(plan) is not PublisherDryRunPlan or
            type(expected_metadata_sha256) is not str or
            _SHA.fullmatch(expected_metadata_sha256) is None):
        raise PublisherAssetReviewError('invalid publisher asset review input')
    try:
        current = prepare_offline_publisher_plan(
            directory, expected_draft_sha256=plan.draft_manifest_sha256,
            project_id=plan.project_id, approval_request_id=plan.request_id,
            approval_store=approval_store, evidence=evidence)
        if current != plan:
            raise PublisherAssetReviewError('publisher plan no longer current')
        path = Path(metadata_path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
            raise PublisherAssetReviewError('metadata is unavailable')
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != expected_metadata_sha256:
            raise PublisherAssetReviewError('metadata file changed')
        metadata = load_metadata(path)
        if metadata.project_id != plan.project_id:
            raise PublisherAssetReviewError('metadata project mismatch')
        # The plan has already bound EVERY episode's title/author-note sha256,
        # the body and current stage-89 approval via the checked manifest.
        payload = [plan.project_id, plan.request_id, plan.approval_snapshot_sha256,
                   plan.plan_sha256, plan.draft_manifest_sha256,
                   expected_metadata_sha256,
                   [[a.episode, a.title_sha256, a.body_sha256,
                     a.author_note_sha256] for a in plan.artifacts]]
        return sha256(json.dumps(payload, ensure_ascii=True,
                      separators=(',', ':')).encode('ascii')).hexdigest()
    except PublisherAssetReviewError:
        raise
    except (PublisherAdapterError, MetadataError, OSError, ValueError, TypeError, KeyError):
        raise PublisherAssetReviewError('publisher assets failed local verification') from None


class PublisherAssetReviewStore:
    """Local hash-only extra review; not identity authentication or permission to publish."""

    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        if path != Path(':memory:') and (path.is_symlink() or not path.parent.is_dir()):
            raise PublisherAssetReviewError('invalid local review database path')
        existed = path.exists()
        self._db = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        self._db.row_factory = sqlite3.Row
        if not existed and path != Path(':memory:'):
            os.chmod(path, 0o600)
        self._db.execute('''CREATE TABLE IF NOT EXISTS local_publisher_asset_reviews (
           review_id TEXT PRIMARY KEY,
           project_id TEXT NOT NULL,
           approval_request_id TEXT NOT NULL,
           fingerprint TEXT NOT NULL,
           confirmation_sha256 TEXT NOT NULL,
           status TEXT NOT NULL CHECK(status IN ('PENDING','REVIEWED','REJECTED','REVOKED'))
        )''')

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> 'PublisherAssetReviewStore':
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def request_review(self, plan: PublisherDryRunPlan, directory: str | Path,
                       metadata_path: str | Path, *, expected_metadata_sha256: str,
                       approval_store: PublicationApprovalStore,
                       evidence: PublicationReviewEvidence) -> AssetReviewChallenge:
        fingerprint = _checked_binding(plan, directory, metadata_path,
                                       expected_metadata_sha256, approval_store, evidence)
        review_id, code = uuid4().hex, secrets.token_hex(16)
        try:
            with self._db:
                self._db.execute('''INSERT INTO local_publisher_asset_reviews
                    VALUES (?, ?, ?, ?, ?, 'PENDING')''',
                    (review_id, plan.project_id, plan.request_id, fingerprint,
                     sha256(code.encode('ascii')).hexdigest()))
        except sqlite3.Error:
            raise PublisherAssetReviewError('cannot store local asset review') from None
        return AssetReviewChallenge(review_id, code, fingerprint)

    def _row(self, review_id: str) -> sqlite3.Row:
        if type(review_id) is not str or re.fullmatch(r'[0-9a-f]{32}', review_id) is None:
            raise PublisherAssetReviewError('invalid review identifier')
        row = self._db.execute('''SELECT * FROM local_publisher_asset_reviews
                                     WHERE review_id=?''', (review_id,)).fetchone()
        if row is None or row['status'] not in ('PENDING','REVIEWED','REJECTED','REVOKED'):
            raise PublisherAssetReviewError('local review record unavailable')
        return row

    def decide(self, review_id: str, plan: PublisherDryRunPlan, directory: str | Path,
               metadata_path: str | Path, *, expected_metadata_sha256: str,
               approval_store: PublicationApprovalStore,
               evidence: PublicationReviewEvidence,
               decision: str, confirmation: str) -> AssetReviewReceipt:
        if decision not in ('REVIEW', 'REJECT') or type(confirmation) is not str or len(confirmation) > 150:
            raise PublisherAssetReviewError('explicit asset review decision required')
        fingerprint = _checked_binding(plan, directory, metadata_path,
                                       expected_metadata_sha256, approval_store, evidence)
        row = self._row(review_id)
        if (row['status'] != 'PENDING' or row['project_id'] != plan.project_id or
                row['approval_request_id'] != plan.request_id or
                row['fingerprint'] != fingerprint or
                not _SHA.fullmatch(row['confirmation_sha256'])):
            raise PublisherAssetReviewError('asset review is stale or already decided')
        label = 'CONFIRM-PUBLISHER-ASSETS' if decision == 'REVIEW' else 'REJECT-PUBLISHER-ASSETS'
        prefix = f'{label} {review_id} '
        code = confirmation[len(prefix):] if confirmation.startswith(prefix) else ''
        if not re.fullmatch(r'[0-9a-f]{32}', code) or sha256(code.encode('ascii')).hexdigest() != row['confirmation_sha256']:
            raise PublisherAssetReviewError('explicit asset review confirmation mismatch')
        status = 'REVIEWED' if decision == 'REVIEW' else 'REJECTED'
        with self._db:
            changed = self._db.execute('''UPDATE local_publisher_asset_reviews SET status=?
                WHERE review_id=? AND status='PENDING' AND fingerprint=?''',
                (status, review_id, fingerprint)).rowcount
        if changed != 1:
            raise PublisherAssetReviewError('asset review changed concurrently')
        return AssetReviewReceipt(review_id, plan.project_id, plan.request_id, fingerprint, status)

    def revoke(self, review_id: str, *, confirmation: str) -> None:
        row = self._row(review_id)
        if confirmation != f'REVOKE-PUBLISHER-ASSETS {review_id}' or row['status'] != 'REVIEWED':
            raise PublisherAssetReviewError('explicit asset review revocation required')
        with self._db:
            changed = self._db.execute('''UPDATE local_publisher_asset_reviews SET status='REVOKED'
                WHERE review_id=? AND status='REVIEWED' ''', (review_id,)).rowcount
        if changed != 1:
            raise PublisherAssetReviewError('asset review revocation failed')

    def require_current_review(self, review_id: str, plan: PublisherDryRunPlan,
                               directory: str | Path, metadata_path: str | Path, *,
                               expected_metadata_sha256: str,
                               approval_store: PublicationApprovalStore,
                               evidence: PublicationReviewEvidence) -> AssetReviewReceipt:
        fingerprint = _checked_binding(plan, directory, metadata_path,
                                       expected_metadata_sha256, approval_store, evidence)
        row = self._row(review_id)
        if (row['status'] != 'REVIEWED' or row['fingerprint'] != fingerprint or
                row['project_id'] != plan.project_id or
                row['approval_request_id'] != plan.request_id):
            raise PublisherAssetReviewError('publisher asset review not current')
        return AssetReviewReceipt(review_id, plan.project_id, plan.request_id,
                                  fingerprint, 'REVIEWED')


def simulate_reviewed_offline_upload(plan: PublisherDryRunPlan, directory: str | Path,
                                    metadata_path: str | Path, *,
                                    expected_metadata_sha256: str, review_id: str,
                                    review_store: PublisherAssetReviewStore,
                                    approval_store: PublicationApprovalStore,
                                    evidence: PublicationReviewEvidence) -> PublisherMockReceipt:
    """Only LOCAL mock after separate title/note/metadata review. Never transmit."""
    if type(review_store) is not PublisherAssetReviewStore:
        raise PublisherAssetReviewError('local asset review store required')
    review_store.require_current_review(
        review_id, plan, directory, metadata_path,
        expected_metadata_sha256=expected_metadata_sha256,
        approval_store=approval_store, evidence=evidence)
    return simulate_offline_upload(plan, directory, approval_store=approval_store, evidence=evidence)
