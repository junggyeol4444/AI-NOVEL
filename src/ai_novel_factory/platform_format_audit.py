"""Stage 96: offline comparison against *unverified, user-supplied* format rules.

Never asserts an official platform specification, upload capability, or publication.
No HTTP, credentials, or upload routines exist in this module. This is not a
substitute for stage 95 official-API verification or stage 89 user consent.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from .episode_upload_files import UploadDraftError, verify_upload_drafts
from .publication_metadata import MetadataError, load_metadata
from .epub3 import verify_epub

_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SLUG = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
_FORMATS = frozenset(('TXT_EPISODES', 'EPUB3'))


class PlatformAuditError(ValueError):
    """Does not expose supplied prose, file paths or secrets."""


@dataclass(frozen=True, slots=True)
class UnverifiedPlatformRules:
    """Declarative local comparison rules, NOT sourced/verified official policy."""
    profile_id: str
    accepted_formats: tuple[str, ...]
    max_title_characters: int
    max_body_bytes: int
    max_author_note_bytes: int
    max_episodes: int
    languages: tuple[str, ...]
    require_category: bool = True
    max_keywords: int = 12
    source: str = 'USER_SUPPLIED_UNVERIFIED'


@dataclass(frozen=True, slots=True)
class PlatformFormatResult:
    profile_id: str
    project_id: str
    inspected_format: str
    status: str
    finding_codes: tuple[str, ...]
    episode_count: int
    evidence_sha256: str
    rules_origin: str = 'USER_SUPPLIED_UNVERIFIED'
    official_rules_verified: bool = False
    official_api_verified: bool = False
    actual_upload_tested: bool = False
    actual_upload_possible: str = 'UNKNOWN'
    publication_executed: bool = False


def _limit(value: object, *, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise PlatformAuditError(f'{field}: invalid local comparison limit')
    return value


def validate_rules(rules: UnverifiedPlatformRules) -> UnverifiedPlatformRules:
    if type(rules) is not UnverifiedPlatformRules or not isinstance(rules.profile_id, str) or not _SLUG.fullmatch(rules.profile_id):
        raise PlatformAuditError('invalid local profile identifier')
    if (rules.source != 'USER_SUPPLIED_UNVERIFIED' or
            not isinstance(rules.accepted_formats, tuple) or
            not rules.accepted_formats or len(set(rules.accepted_formats)) != len(rules.accepted_formats) or
            any(type(f) is not str or f not in _FORMATS for f in rules.accepted_formats)):
        raise PlatformAuditError('rules are not an unverified local format profile')
    if (not isinstance(rules.languages, tuple) or not rules.languages or
            len(set(rules.languages)) != len(rules.languages) or
            any(type(x) is not str or x not in ('ko', 'en', 'ja') for x in rules.languages)):
        raise PlatformAuditError('invalid local language limits')
    for field, max_v in (('max_title_characters', 20000), ('max_body_bytes', 20_000_000),
                         ('max_author_note_bytes', 1_000_000), ('max_episodes', 10000),
                         ('max_keywords', 200)):
        _limit(getattr(rules, field), minimum=0 if field in ('max_author_note_bytes', 'max_keywords') else 1,
               maximum=max_v, field=field)
    if type(rules.require_category) is not bool:
        raise PlatformAuditError('category rule must be boolean')
    return rules


def _digest_json(data: object) -> str:
    payload = json.dumps(data, ensure_ascii=True, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('ascii')
    return sha256(payload).hexdigest()


def check_platform_format(
    rules: UnverifiedPlatformRules, *,
    draft_directory: str | Path, expected_draft_sha256: str,
    metadata_file: str | Path, expected_metadata_sha256: str,
    content_format: str = 'TXT_EPISODES',
    epub_path: str | Path | None = None,
    expected_epub_sha256: str | None = None,
) -> PlatformFormatResult:
    """Validate anchored local files and compare against declared rules only.

    Mismatch != upload impossible; match != upload possible. No platform requests.
    Raises on unreliable file evidence rather than generating a reassuring report.
    """
    rules = validate_rules(rules)
    if type(content_format) is not str or content_format not in _FORMATS:
        raise PlatformAuditError('unsupported local input format')
    for dig in (expected_draft_sha256, expected_metadata_sha256):
        if type(dig) is not str or not _SHA.fullmatch(dig):
            raise PlatformAuditError('anchored SHA-256 evidence required')
    meta_path = Path(metadata_file)
    if meta_path.is_symlink() or not meta_path.is_file() or meta_path.stat().st_size > 16384:
        raise PlatformAuditError('metadata evidence unavailable')
    try:
        raw = meta_path.read_bytes()
        if sha256(raw).hexdigest() != expected_metadata_sha256:
            raise PlatformAuditError('metadata evidence changed')
        meta = load_metadata(meta_path)
        verified = verify_upload_drafts(draft_directory, expected_manifest_sha256=expected_draft_sha256)
        manifest = json.loads((Path(draft_directory) / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['project_id'] != meta.project_id:
            raise PlatformAuditError('metadata and upload draft project mismatch')
        if len(manifest['episodes']) != verified.episode_count:
            raise PlatformAuditError('local draft episode count changed')
    except (MetadataError, UploadDraftError, UnicodeError, OSError, ValueError, KeyError, TypeError):
        raise PlatformAuditError('local content evidence invalid or changed') from None
    findings: set[str] = set()
    if content_format not in rules.accepted_formats:
        findings.add('DECLARED_FORMAT_NOT_ACCEPTED')
    if len(meta.title) > rules.max_title_characters:
        findings.add('DECLARED_WORK_TITLE_LIMIT_EXCEEDED')
    if meta.language not in rules.languages:
        findings.add('DECLARED_LANGUAGE_NOT_ACCEPTED')
    if rules.require_category and not meta.category.strip():
        findings.add('DECLARED_CATEGORY_REQUIRED')
    if len(meta.keywords) > rules.max_keywords:
        findings.add('DECLARED_KEYWORDS_LIMIT_EXCEEDED')
    if verified.episode_count > rules.max_episodes:
        findings.add('DECLARED_EPISODE_LIMIT_EXCEEDED')
    for episode in manifest['episodes']:
        entries = episode['files']
        if entries['body']['utf8_bytes'] > rules.max_body_bytes:
            findings.add('DECLARED_BODY_SIZE_LIMIT_EXCEEDED')
        if entries['author_note']['utf8_bytes'] > rules.max_author_note_bytes:
            findings.add('DECLARED_AUTHOR_NOTE_LIMIT_EXCEEDED')
        name = entries['title']['filename']
        title = (Path(draft_directory) / name).read_text(encoding='utf-8')
        if len(title) > rules.max_title_characters:
            findings.add('DECLARED_EPISODE_TITLE_LIMIT_EXCEEDED')
    epub_digest = None
    if content_format == 'EPUB3':
        if epub_path is None or type(expected_epub_sha256) is not str or not _SHA.fullmatch(expected_epub_sha256):
            raise PlatformAuditError('anchored EPUB3 evidence required')
        epub_file = Path(epub_path)
        if epub_file.is_symlink() or not epub_file.is_file():
            raise PlatformAuditError('EPUB3 file unavailable')
        try:
            epub_digest = sha256(epub_file.read_bytes()).hexdigest()
            if epub_digest != expected_epub_sha256:
                raise PlatformAuditError('EPUB3 evidence changed')
            verified_epub = verify_epub(epub_file, expected_chapters=verified.episode_count)
            if not verified_epub.valid:
                raise PlatformAuditError('EPUB3 failed local structural verification')
        except PlatformAuditError:
            raise
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            raise PlatformAuditError('EPUB3 structure invalid') from None
    elif epub_path is not None or expected_epub_sha256 is not None:
        raise PlatformAuditError('TXT comparison must not supply EPUB3 evidence')
    fingerprint = _digest_json([
        rules.profile_id, rules.accepted_formats, rules.max_title_characters,
        rules.max_body_bytes, rules.max_author_note_bytes, rules.max_episodes,
        rules.languages, rules.require_category, rules.max_keywords, rules.source,
        expected_draft_sha256, expected_metadata_sha256, epub_digest, content_format,
    ])
    return PlatformFormatResult(
        profile_id=rules.profile_id, project_id=meta.project_id,
        inspected_format=content_format,
        status='LOCAL_DECLARED_MISMATCH' if findings else 'LOCAL_DECLARED_MATCH_ONLY',
        finding_codes=tuple(sorted(findings)), episode_count=verified.episode_count,
        evidence_sha256=fingerprint,
    )


def write_local_audit_report(result: PlatformFormatResult, output_directory: str | Path) -> Path:
    """Write an exclusive local report without any original text or credentials."""
    if (type(result) is not PlatformFormatResult or
            type(result.profile_id) is not str or not _SLUG.fullmatch(result.profile_id) or
            type(result.project_id) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', result.project_id) or
            type(result.evidence_sha256) is not str or not _SHA.fullmatch(result.evidence_sha256) or
            type(result.episode_count) is not int or result.episode_count < 1 or
            type(result.finding_codes) is not tuple or
            any(type(code) is not str or not re.fullmatch(r'[A-Z_]{3,80}', code) for code in result.finding_codes) or
            len(set(result.finding_codes)) != len(result.finding_codes) or
            (result.status == 'LOCAL_DECLARED_MATCH_ONLY') != (not result.finding_codes)):
        raise PlatformAuditError('invalid local audit result')
    if (result.official_rules_verified is not False or result.official_api_verified is not False or
            result.actual_upload_tested is not False or result.actual_upload_possible != 'UNKNOWN' or
            result.publication_executed is not False or
            result.rules_origin != 'USER_SUPPLIED_UNVERIFIED' or
            result.status not in ('LOCAL_DECLARED_MATCH_ONLY', 'LOCAL_DECLARED_MISMATCH')):
        raise PlatformAuditError('false platform approval or verification fields forbidden')
    dest = Path(output_directory)
    if dest.is_symlink() or not dest.is_dir():
        raise PlatformAuditError('existing local output directory required')
    path = dest / f'platform_audit_{result.profile_id}.json'
    fields = {
        'schema_version': 1, 'profile_id': result.profile_id, 'project_id': result.project_id,
        'inspected_format': result.inspected_format, 'status': result.status,
        'finding_codes': list(result.finding_codes), 'episode_count': result.episode_count,
        'evidence_sha256': result.evidence_sha256, 'rules_origin': result.rules_origin,
        'official_rules_verified': False, 'official_api_verified': False,
        'actual_upload_tested': False, 'actual_upload_possible': 'UNKNOWN',
        'publication_executed': False,
    }
    content = (json.dumps(fields, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode('ascii')
    try:
        with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600), 'wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        raise PlatformAuditError('report already exists or cannot be created') from None
    return path
