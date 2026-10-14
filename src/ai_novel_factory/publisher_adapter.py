"""Stage 95 / ANF-REQ-066 — fail-closed OFFLINE publisher-adapter seam.

NO official platform API has been verified in this build. No URL, HTTP client,
credentials, socket or real publishing/upload operation is implemented. Only
in-memory sandbox simulation is available; it is NOT an official API test.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Protocol, runtime_checkable

from .episode_upload_files import UploadDraftError, verify_upload_drafts
from .manuscript_versions import ManuscriptVersionStore
from .publication_approval import (
    PublicationApprovalStore, PublicationReviewEvidence, PublicationApprovalError,
)

_SHA = re.compile(r'[0-9a-f]{64}\Z')


class PublisherAdapterError(ValueError):
    """Safe public exception: never include original text or secrets."""


@dataclass(frozen=True, slots=True)
class PublisherEpisodeArtifact:
    episode: int
    title_sha256: str
    body_sha256: str
    author_note_sha256: str
    body_bytes: int


@dataclass(frozen=True, slots=True)
class PublisherDryRunPlan:
    project_id: str
    request_id: str
    approval_snapshot_sha256: str
    draft_manifest_sha256: str
    artifacts: tuple[PublisherEpisodeArtifact, ...]
    plan_sha256: str
    adapter_id: str = 'local-sandbox-only'
    official_api_spec_verified: bool = False
    official_sandbox_upload_verified: bool = False
    publication_executed: bool = False


@dataclass(frozen=True, slots=True)
class PublisherMockReceipt:
    plan_sha256: str
    accepted_episode_count: int
    status: str = 'LOCAL_SIMULATION_NOT_UPLOADED'
    official_api_spec_verified: bool = False
    official_sandbox_upload_verified: bool = False
    publication_executed: bool = False


@runtime_checkable
class PublisherAdapterContract(Protocol):
    """Future protocol boundary; current build has ONLY the sandbox adapter."""

    def simulate(self, plan: PublisherDryRunPlan) -> PublisherMockReceipt: ...


class LocalSandboxPublisherAdapter:
    """No filesystem writes, sockets, external services or platform credentials."""

    adapter_id = 'local-sandbox-only'

    def simulate(self, plan: PublisherDryRunPlan) -> PublisherMockReceipt:
        if (type(plan) is not PublisherDryRunPlan or
                plan.adapter_id != self.adapter_id or
                plan.official_api_spec_verified is not False or
                plan.official_sandbox_upload_verified is not False or
                plan.publication_executed is not False or
                not plan.artifacts or
                type(plan.plan_sha256) is not str or not _SHA.fullmatch(plan.plan_sha256) or
                any(type(a) is not PublisherEpisodeArtifact for a in plan.artifacts)):
            raise PublisherAdapterError('invalid local publisher simulation plan')
        return PublisherMockReceipt(plan.plan_sha256, len(plan.artifacts))


def _plan_digest(project_id: str, request_id: str, approval_sha: str,
                 draft_sha: str, artifacts: tuple[PublisherEpisodeArtifact, ...]) -> str:
    # Contains no prose, notes, author name, path, platform account or secret.
    payload = [project_id, request_id, approval_sha, draft_sha,
               [[a.episode, a.title_sha256, a.body_sha256,
                 a.author_note_sha256, a.body_bytes] for a in artifacts]]
    return sha256(json.dumps(payload, ensure_ascii=True,
                             separators=(',', ':')).encode('ascii')).hexdigest()


def prepare_offline_publisher_plan(
    directory: str | Path, *, expected_draft_sha256: str,
    project_id: str, approval_request_id: str,
    approval_store: PublicationApprovalStore, evidence: PublicationReviewEvidence,
) -> PublisherDryRunPlan:
    """Recheck local stage-89 consent and stage-94 draft vs currently approved text.

    This method cannot send anything. A publication approval is necessary but is
    NOT sufficient for actual upload, and title/notes are still user-reviewed.
    """
    if (type(approval_store) is not PublicationApprovalStore or
            type(evidence) is not PublicationReviewEvidence or
            type(expected_draft_sha256) is not str or
            not _SHA.fullmatch(expected_draft_sha256)):
        raise PublisherAdapterError('local review and anchored draft required')
    try:
        # Must be invoked freshly; never trust a caller supplied approval receipt.
        consent = approval_store.require_current_publication_approval(
            project_id, approval_request_id, evidence)
        verify_upload_drafts(directory, expected_manifest_sha256=expected_draft_sha256)
        root = Path(directory)
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        request = approval_store.get_request(project_id, approval_request_id)
        items = manifest['episodes']
        if (manifest['project_id'] != project_id or
                len(items) != request.episode_count or
                {ep['episode_number'] for ep in items} != set(range(1, request.episode_count+1))):
            raise PublisherAdapterError('draft does not cover the approved project and episodes')
        artifacts = []
        with ManuscriptVersionStore(approval_store._path) as versions:
            final_texts = {i['episode_number']: versions.get_episode(project_id, i['episode_number']).final_text
                           for i in items}
        for item in items:
            number = item['episode_number']
            # The exported body must be the exact current approved FINAL text
            # under stage-94 documented line-ending normalization.
            normalized = final_texts[number].replace('\r\n', '\n').replace('\r', '\n')
            body = (root / item['files']['body']['filename']).read_bytes()
            if (not normalized.strip() or
                    normalized.encode('utf-8') != body):
                raise PublisherAdapterError('draft body differs from the approved final candidate')
            files = item['files']
            artifacts.append(PublisherEpisodeArtifact(
                number, files['title']['sha256'], files['body']['sha256'],
                files['author_note']['sha256'], files['body']['utf8_bytes']))
        artifacts_tuple = tuple(artifacts)
        digest = _plan_digest(project_id, approval_request_id, consent.manifest_sha256,
                              expected_draft_sha256, artifacts_tuple)
        return PublisherDryRunPlan(project_id, approval_request_id,
                                   consent.manifest_sha256, expected_draft_sha256,
                                   artifacts_tuple, digest)
    except (UploadDraftError, PublicationApprovalError, UnicodeError, OSError,
            KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, PublisherAdapterError):
            raise
        raise PublisherAdapterError('publisher preview blocked: approval or local draft invalid') from None


def simulate_offline_upload(
    plan: PublisherDryRunPlan, directory: str | Path, *,
    approval_store: PublicationApprovalStore, evidence: PublicationReviewEvidence,
    adapter: LocalSandboxPublisherAdapter | None = None,
) -> PublisherMockReceipt:
    """Revalidate everything at use time; call ONLY the in-memory simulator."""
    if type(plan) is not PublisherDryRunPlan:
        raise PublisherAdapterError('invalid local publisher simulation plan')
    current = prepare_offline_publisher_plan(
        directory, expected_draft_sha256=plan.draft_manifest_sha256,
        project_id=plan.project_id, approval_request_id=plan.request_id,
        approval_store=approval_store, evidence=evidence)
    if current != plan or current.plan_sha256 != _plan_digest(
            current.project_id, current.request_id, current.approval_snapshot_sha256,
            current.draft_manifest_sha256, current.artifacts):
        raise PublisherAdapterError('publisher simulation plan changed')
    if adapter is not None and type(adapter) is not LocalSandboxPublisherAdapter:
        raise PublisherAdapterError('non-sandbox adapters disabled in offline build')
    return (adapter or LocalSandboxPublisherAdapter()).simulate(current)


def upload_to_real_platform(*args: object, **kwargs: object) -> None:
    """Explicit hard-block until official API and test upload can be verified.

    Deliberately does not accept/use URLs, credentials, HTTP clients or a transport.
    """
    raise PublisherAdapterError('real platform upload is disabled; official API unverified')
