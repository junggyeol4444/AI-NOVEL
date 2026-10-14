"""Stage 94 / ANF-REQ-065: export UTF-8 per-episode *local draft files*.

This is not a publisher adapter, user approval, upload, or finalization.
No reference novels, outside resources, or service connections are consulted.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import unicodedata

from ai_novel_factory.publication_metadata import MetadataDraft, validate_metadata, load_metadata


class UploadDraftError(ValueError):
    """Error messages intentionally exclude original manuscript and path values."""


DIR_NAME = 'upload_drafts'
MANIFEST_NAME = 'manifest.json'
STATUS = 'DRAFT_REQUIRES_USER_REVIEW'
SCHEMA_VERSION = 1
MAX_EPISODES = 200
MAX_BODY_BYTES = 2_000_000
MAX_TOTAL_BYTES = 25_000_000
MAX_TITLE_CHARS = 150
MAX_NOTE_BYTES = 50_000
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_NAME = re.compile(r'episode_[0-9]{4}_(?:title|body|author_note)\.txt\Z')


@dataclass(frozen=True, slots=True)
class UploadEpisode:
    episode_number: int
    title: str
    body: str
    author_note: str = ''


@dataclass(frozen=True, slots=True)
class UploadDraftOutput:
    directory: Path
    episode_count: int
    manifest_sha256: str
    files_created: int
    publication_approved: bool = False
    published: bool = False


@dataclass(frozen=True, slots=True)
class UploadDraftVerification:
    valid: bool
    episode_count: int
    files_verified: int
    publication_approved: bool = False
    published: bool = False


def _normalized_text(value: object, label: str, *, allow_newline: bool,
                     allow_empty: bool, max_bytes: int) -> str:
    if not isinstance(value, str):
        raise UploadDraftError(f'{label}: UTF-8 text required')
    # Explicit, documented newline-only canonicalization. Do not strip original prose.
    result = value.replace('\r\n', '\n').replace('\r', '\n')
    if (not allow_empty and not result.strip()) or ('\ufeff' in result):
        raise UploadDraftError(f'{label}: empty/BOM text prohibited')
    if not allow_newline and ('\n' in result or result != result.strip()):
        raise UploadDraftError(f'{label}: title must be single line without surrounding whitespace')
    for char in result:
        cat = unicodedata.category(char)
        if cat in {'Cc', 'Cf', 'Cs', 'Zl', 'Zp'} and not (allow_newline and char == '\n'):
            raise UploadDraftError(f'{label}: control/invisible character prohibited')
    try:
        size = len(result.encode('utf-8', errors='strict'))
    except UnicodeError as exc:
        raise UploadDraftError(f'{label}: invalid Unicode') from exc
    if size > max_bytes:
        raise UploadDraftError(f'{label}: UTF-8 size limit exceeded')
    if label == 'title' and len(result) > MAX_TITLE_CHARS:
        raise UploadDraftError('title: character limit exceeded')
    return result


def _validate_episodes(episodes: object) -> list[tuple[int, dict[str, bytes]]]:
    if not isinstance(episodes, (list, tuple)) or not 1 <= len(episodes) <= MAX_EPISODES:
        raise UploadDraftError('episodes: 1 to 200 required')
    result: list[tuple[int, dict[str, bytes]]] = []
    seen: set[int] = set()
    total = 0
    for ep in episodes:
        if not isinstance(ep, UploadEpisode):
            raise UploadDraftError('episodes: UploadEpisode items required')
        number = ep.episode_number
        if type(number) is not int or not (1 <= number <= 9999) or number in seen:
            raise UploadDraftError('episode_number: duplicate or invalid')
        seen.add(number)
        texts = {
            'title': _normalized_text(ep.title, 'title', allow_newline=False,
                                      allow_empty=False, max_bytes=1200),
            'body': _normalized_text(ep.body, 'body', allow_newline=True,
                                     allow_empty=False, max_bytes=MAX_BODY_BYTES),
            'author_note': _normalized_text(ep.author_note, 'author_note', allow_newline=True,
                                            allow_empty=True, max_bytes=MAX_NOTE_BYTES),
        }
        files = {f'episode_{number:04d}_{kind}.txt': value.encode('utf-8') for kind, value in texts.items()}
        total += sum(map(len, files.values()))
        if total > MAX_TOTAL_BYTES:
            raise UploadDraftError('episodes: total UTF-8 size limit exceeded')
        result.append((number, files))
    return sorted(result, key=lambda item: item[0])


def _canonical(body: object) -> bytes:
    return (json.dumps(body, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def _pairs_no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, item in pairs:
        if name in result:
            raise UploadDraftError('duplicate JSON key')
        result[name] = item
    return result


def _manifest(metadata: MetadataDraft, normalized: list[tuple[int, dict[str, bytes]]]) -> bytes:
    items = []
    for number, files in normalized:
        items.append({'episode_number': number, 'files': {
            kind: {'filename': f'episode_{number:04d}_{kind}.txt',
                   'sha256': sha256(files[f'episode_{number:04d}_{kind}.txt']).hexdigest(),
                   'utf8_bytes': len(files[f'episode_{number:04d}_{kind}.txt'])}
            for kind in ('title', 'body', 'author_note')
        }})
    return _canonical({'schema_version': SCHEMA_VERSION, 'project_id': metadata.project_id,
                       'metadata_version': metadata.version, 'status': STATUS,
                       'publication_approved': False, 'published': False,
                       'encoding': 'UTF-8', 'line_endings': 'LF',
                       'episodes': items})


def export_upload_drafts(metadata: MetadataDraft, episodes: list[UploadEpisode] | tuple[UploadEpisode, ...],
                         output_parent: str | Path) -> UploadDraftOutput:
    """Create *only* a new local upload_drafts/ folder; never overwrite or publish."""
    metadata = validate_metadata(metadata)
    normalized = _validate_episodes(episodes)
    parent = Path(output_parent)
    if parent.is_symlink() or not parent.is_dir():
        raise UploadDraftError('output parent: existing real directory required')
    dest = parent / DIR_NAME
    try:
        dest.mkdir(mode=0o700, exist_ok=False)
    except OSError as exc:
        raise UploadDraftError('output folder exists or is inaccessible') from exc
    try:
        # No user text or paths in the manifest: hashes and byte lengths only.
        for _, group in normalized:
            for name, contents in group.items():
                path = dest / name
                with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as handle:
                    handle.write(contents)
                    handle.flush()
                    os.fsync(handle.fileno())
        manifest = _manifest(metadata, normalized)
        with os.fdopen(os.open(dest / MANIFEST_NAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as handle:
            handle.write(manifest)
            handle.flush()
            os.fsync(handle.fileno())
        verify_upload_drafts(dest, expected_manifest_sha256=sha256(manifest).hexdigest())
        return UploadDraftOutput(dest, len(normalized), sha256(manifest).hexdigest(), len(normalized)*3)
    except BaseException:
        # Roll back only the directory that mkdir above exclusively created.
        shutil.rmtree(dest)
        raise


def verify_upload_drafts(directory: str | Path, *, expected_manifest_sha256: str | None = None) -> UploadDraftVerification:
    """Strict local verification: file list, hashes, canonical UTF-8, schema, and status.

    A hash is NOT a digital signature; an attacker able to rewrite both files and
    manifest can recompute it. Supply a previously saved expected digest to anchor.
    """
    dest = Path(directory)
    if dest.is_symlink() or not dest.is_dir() or dest.name != DIR_NAME:
        raise UploadDraftError('invalid draft directory')
    manifest_path = dest / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 100_000:
        raise UploadDraftError('invalid draft manifest')
    data = manifest_path.read_bytes()
    digest = sha256(data).hexdigest()
    if expected_manifest_sha256 is not None:
        if not isinstance(expected_manifest_sha256, str) or not _SHA.fullmatch(expected_manifest_sha256):
            raise UploadDraftError('invalid expected manifest digest')
        if digest != expected_manifest_sha256:
            raise UploadDraftError('manifest digest changed')
    try:
        obj = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs_no_duplicates,
                         parse_constant=lambda _: (_ for _ in ()).throw(UploadDraftError('invalid number')))
        if _canonical(obj) != data or not isinstance(obj, dict) or set(obj) != {
            'schema_version', 'project_id', 'metadata_version', 'status',
            'publication_approved', 'published', 'encoding', 'line_endings', 'episodes'}:
            raise UploadDraftError('invalid manifest format')
        if (type(obj['schema_version']) is not int or obj['schema_version'] != 1 or
                type(obj['metadata_version']) is not int or obj['metadata_version'] != 1 or
                not isinstance(obj['project_id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', obj['project_id']) or
                obj['status'] != STATUS or obj['encoding'] != 'UTF-8' or obj['line_endings'] != 'LF' or
                obj['publication_approved'] is not False or obj['published'] is not False):
            raise UploadDraftError('invalid manifest status')
        items = obj['episodes']
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_EPISODES:
            raise UploadDraftError('invalid episode count')
        actual = {p.name for p in dest.iterdir() if p.is_file() or p.is_symlink()}
        if len(list(dest.iterdir())) != len(actual):
            raise UploadDraftError('unexpected directory entry')
        required = {MANIFEST_NAME}
        last = 0
        total = 0
        for item in items:
            if not isinstance(item, dict) or set(item) != {'episode_number','files'}:
                raise UploadDraftError('invalid episode record')
            num = item['episode_number']
            if type(num) is not int or not last < num <= 9999:
                raise UploadDraftError('episode ordering invalid')
            last = num
            files = item['files']
            if not isinstance(files, dict) or set(files) != {'title','body','author_note'}:
                raise UploadDraftError('invalid episode file list')
            for kind in ('title','body','author_note'):
                ent=files[kind]
                name=f'episode_{num:04d}_{kind}.txt'
                if (not isinstance(ent, dict) or set(ent) != {'filename','sha256','utf8_bytes'} or
                        ent['filename'] != name or not _NAME.fullmatch(name) or
                        not isinstance(ent['sha256'], str) or not _SHA.fullmatch(ent['sha256']) or
                        type(ent['utf8_bytes']) is not int or ent['utf8_bytes'] < 0):
                    raise UploadDraftError('invalid episode file metadata')
                required.add(name)
                path=dest/name
                if path.is_symlink() or not path.is_file():
                    raise UploadDraftError('missing or linked draft file')
                size=path.stat().st_size
                limit={'title':1200,'body':MAX_BODY_BYTES,'author_note':MAX_NOTE_BYTES}[kind]
                if size > limit or size != ent['utf8_bytes']:
                    raise UploadDraftError('draft file byte length differs')
                contents=path.read_bytes()
                if sha256(contents).hexdigest() != ent['sha256']:
                    raise UploadDraftError('draft file checksum differs')
                decoded=contents.decode('utf-8', errors='strict')
                normalized=_normalized_text(decoded,kind,allow_newline=(kind!='title'),
                                             allow_empty=(kind=='author_note'),max_bytes=limit)
                if normalized.encode('utf-8') != contents:
                    raise UploadDraftError('draft file is not normalized UTF-8')
                total+=size
                if total>MAX_TOTAL_BYTES:
                    raise UploadDraftError('draft total byte limit exceeded')
        if actual != required:
            raise UploadDraftError('missing or unexpected files')
    except (UnicodeError, ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        if isinstance(exc, UploadDraftError):
            raise
        raise UploadDraftError('unreadable or invalid draft files') from exc
    return UploadDraftVerification(True, len(items), len(items)*3)


def export_from_metadata_file(metadata_file: str | Path, episodes: list[UploadEpisode] | tuple[UploadEpisode, ...],
                              output_parent: str | Path) -> UploadDraftOutput:
    return export_upload_drafts(load_metadata(metadata_file), episodes, output_parent)
