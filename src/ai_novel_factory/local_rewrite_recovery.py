"""Author-initiated, offline recovery of unsaved longform GGUF rewrite candidates.

A recovery file is NOT a manuscript revision, SQLite write, QC pass, final
text, publication approval, model invocation, or autosave. It can be imported
only while the EXACT original project/episode/revision/draft/final state still
matches. A new local file is created exclusively; never overwrite originals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path

from .database.episodes import EpisodeStore, MAX_FIELD_BYTES
from .manual_rewrite_workspace import (
    RewriteLease, begin_manual_rewrite, preview_manual_rewrite,
)

_FORMAT = 'ANF_PRIVATE_UNSAVED_REWRITE_RECOVERY_V1'
_MAX_FILE_BYTES = 1_250_000


class LocalRewriteRecoveryError(ValueError):
    """Errors deliberately omit private manuscript text and local paths."""


@dataclass(frozen=True)
class LocalRewriteRecoveryReceipt:
    episode: int
    candidate_chars: int
    candidate_sha256: str
    file_sha256: str
    source_revision: int
    publication_approved: bool = False
    sqlite_modified: bool = False


@dataclass(frozen=True)
class LocalRewriteRecoveredDraft:
    episode: int
    candidate_text: str = field(repr=False)
    candidate_sha256: str = ''
    source_revision: int = 0
    publication_approved: bool = False
    sqlite_modified: bool = False


def _sha(text: str) -> str:
    return sha256(text.encode('utf-8')).hexdigest()


def _serialize(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _target(path: str | Path, *, for_write: bool) -> Path:
    p = Path(path)
    if (not p.is_absolute() or p.suffix.casefold() != '.json'
            or p.is_symlink() or not p.parent.is_dir()
            or p.parent.is_symlink()):
        raise LocalRewriteRecoveryError(
            '사용자가 선택한 기존 로컬 폴더의 JSON 파일만 사용할 수 있습니다.')
    if for_write and p.exists():
        raise LocalRewriteRecoveryError(
            '기존 파일을 덮어쓰지 않습니다. 새 복구 파일 이름을 선택하세요.')
    if not for_write and not p.is_file():
        raise LocalRewriteRecoveryError('기존 복구 JSON 파일을 선택하세요.')
    return p


def _require_current(store: EpisodeStore, lease: RewriteLease,
                     candidate: str) -> None:
    if (not isinstance(store, EpisodeStore) or type(lease) is not RewriteLease
            or type(candidate) is not str or not candidate.strip()):
        raise LocalRewriteRecoveryError('기존 저장 초고와 복구할 수정 후보를 선택하세요.')
    if len(candidate.encode('utf-8')) > MAX_FIELD_BYTES['draft']:
        raise LocalRewriteRecoveryError('복구할 초고가 기존 SQLite 입력 한도를 초과했습니다.')
    try:
        preview_manual_rewrite(store, lease, candidate)
    except (ValueError, UnicodeError, OSError):
        raise LocalRewriteRecoveryError(
            '원본·최종본·작품 revision이 바뀌었거나 수정 후보가 올바르지 않습니다.') from None


def export_unsaved_rewrite(
    store: EpisodeStore, lease: RewriteLease, candidate: str,
    destination: str | Path, *, explicit_author_export: bool,
) -> LocalRewriteRecoveryReceipt:
    """Write ONLY a new, manually selected private recovery JSON file."""
    if explicit_author_export is not True:
        raise LocalRewriteRecoveryError('이번 1회 복구 파일 저장 승인이 필요합니다.')
    _require_current(store, lease, candidate)
    path = _target(destination, for_write=True)
    body = {
        'format': _FORMAT,
        'project_id': lease.project_id,
        'episode': lease.episode,
        'episode_revision': lease.revision,
        'project_revision': lease.project_revision,
        'original_draft_sha256': lease.original_draft_sha256,
        'original_final_sha256': lease.final_sha256,
        'candidate_sha256': _sha(candidate),
        'candidate_text': candidate,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'state': 'UNSAVED_AUTHOR_REVIEW_REQUIRED',
        'publication_approved': False,
    }
    envelope = {'payload': body, 'integrity_sha256': sha256(_serialize(body)).hexdigest()}
    raw = _serialize(envelope)
    if len(raw) > _MAX_FILE_BYTES:
        raise LocalRewriteRecoveryError('복구 파일 크기가 안전 한도를 초과했습니다.')
    # Check again immediately before file creation. This does not lock the
    # SQLite writer, so import also REQUIRES an exact current-source match.
    _require_current(store, lease, candidate)
    try:
        # xb = O_EXCL: cannot replace an existing author file or symlink.
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError):
        raise LocalRewriteRecoveryError(
            '복구 파일을 새로 저장하지 못했습니다. 기존 원고는 변경되지 않았습니다.') from None
    return LocalRewriteRecoveryReceipt(
        lease.episode, len(candidate), body['candidate_sha256'],
        sha256(raw).hexdigest(), lease.revision)


def import_unsaved_rewrite(
    store: EpisodeStore, lease: RewriteLease, source: str | Path,
    *, explicit_author_import: bool,
) -> LocalRewriteRecoveredDraft:
    """Load a candidate into memory only; never write author SQLite."""
    if explicit_author_import is not True:
        raise LocalRewriteRecoveryError('이번 1회 복구 파일 불러오기 승인이 필요합니다.')
    if not isinstance(store, EpisodeStore) or type(lease) is not RewriteLease:
        raise LocalRewriteRecoveryError('현재 작품의 저장 초고를 다시 불러오세요.')
    path = _target(source, for_write=False)
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise LocalRewriteRecoveryError('복구 파일의 크기가 허용 범위 밖입니다.')
    try:
        with path.open('rb') as stream:
            raw = stream.read(_MAX_FILE_BYTES + 1)
        if len(raw) > _MAX_FILE_BYTES:
            raise ValueError
        doc = json.loads(raw.decode('utf-8'))
        if type(doc) is not dict or set(doc) != {'payload', 'integrity_sha256'}:
            raise ValueError
        body = doc['payload']
        if type(body) is not dict or set(body) != {
                'format', 'project_id', 'episode', 'episode_revision',
                'project_revision', 'original_draft_sha256',
                'original_final_sha256', 'candidate_sha256',
                'candidate_text', 'created_utc', 'state',
                'publication_approved'}:
            raise ValueError
        checksum = sha256(_serialize(body)).hexdigest()
        if (type(doc['integrity_sha256']) is not str
                or not hmac.compare_digest(checksum, doc['integrity_sha256'])
                or body['format'] != _FORMAT
                or body['state'] != 'UNSAVED_AUTHOR_REVIEW_REQUIRED'
                or body['publication_approved'] is not False
                or type(body['episode']) is not int
                or type(body['episode_revision']) is not int
                or type(body['project_revision']) is not int
                or type(body['candidate_text']) is not str
                or type(body['candidate_sha256']) is not str):
            raise ValueError
        expected = (
            lease.project_id, lease.episode, lease.revision,
            lease.project_revision, lease.original_draft_sha256,
            lease.final_sha256)
        actual = (
            body['project_id'], body['episode'], body['episode_revision'],
            body['project_revision'], body['original_draft_sha256'],
            body['original_final_sha256'])
        if actual != expected:
            raise ValueError
        if not hmac.compare_digest(_sha(body['candidate_text']),
                                   body['candidate_sha256']):
            raise ValueError
        candidate = body['candidate_text']
        _require_current(store, lease, candidate)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            RecursionError, OverflowError):
        raise LocalRewriteRecoveryError(
            '복구 파일의 무결성 또는 현재 원고의 revision이 일치하지 않습니다. '
            '원본을 변경하지 않았습니다.') from None
    return LocalRewriteRecoveredDraft(
        lease.episode, candidate, body['candidate_sha256'], lease.revision)
