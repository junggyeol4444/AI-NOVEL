"""Author-initiated private EPUB3 multi-volume search and bookmarks.

Only the existing reader's parser handles EPUB text. Bookmark events
contain hashes and positions but NEVER book prose or private source paths.
Bookmark writes require a direct author click and an existing directory;
event files are exclusive new JSON (no overwrite, no automatic syncing).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
import os
import re

from .epub_reader import read_private_epub
from .private_volume_reader import (
    PrivateVolumeCatalog, _digest_file, _selected_file,
    read_selected_volume_chapter)


class PrivateBookmarkError(ValueError):
    """Never includes EPUB prose or user-local paths."""


@dataclass(frozen=True)
class EpubSearchHit:
    volume_index: int
    chapter_index: int
    display_episode: int
    title: str = field(repr=False)
    excerpt: str = field(repr=False)


@dataclass(frozen=True)
class EpubSearchReport:
    total_hits: int
    results: tuple[EpubSearchHit, ...]
    truncated: bool
    status: str = 'PRIVATE_LOCAL_SEARCH_NOT_QC'


@dataclass(frozen=True)
class PrivateBookmark:
    volume_index: int
    chapter_index: int
    display_episode: int
    volume_sha256: str = field(repr=False)
    collection_sha256: str = field(repr=False)
    created_at: str = ''
    event_id: str = ''


def _collection_hash(catalog: PrivateVolumeCatalog) -> str:
    if type(catalog) is not PrivateVolumeCatalog or not catalog.volumes:
        raise PrivateBookmarkError('먼저 직접 선택한 EPUB3 권을 열어 주세요.')
    payload = [(v.index, v.chapters, v.file_sha256) for v in catalog.volumes]
    return sha256(json.dumps(payload, separators=(',', ':'),
                             ensure_ascii=True).encode('ascii')).hexdigest()


def _directory(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise PrivateBookmarkError('책갈피를 저장할 기존 로컬 폴더를 직접 선택해야 합니다.')
    return path


def _assert_unchanged(catalog: PrivateVolumeCatalog) -> None:
    for item in catalog.volumes:
        if _digest_file(_selected_file(item.file_path)) != item.file_sha256:
            raise PrivateBookmarkError('EPUB3 파일이 변경되어 권 목록을 다시 선택해야 합니다.')


def find_private_epub_text(catalog: PrivateVolumeCatalog, keyword: str,
                           *, max_hits: int = 150) -> EpubSearchReport:
    if (type(keyword) is not str or not 2 <= len(keyword.strip()) <= 100
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in keyword)
            or type(max_hits) is not int or not 1 <= max_hits <= 150):
        raise PrivateBookmarkError('검색어는 2~100자의 일반 텍스트여야 합니다.')
    _assert_unchanged(catalog)
    results: list[EpubSearchHit] = []
    count = 0
    expression = re.compile(re.escape(keyword.strip()), re.IGNORECASE)
    for volume in catalog.volumes:
        # Open each EPUB volume only once rather than reparsing an entire
        # book for every matching chapter in a 1000-episode project.
        chapters = read_private_epub(volume.file_path)
        if len(chapters) != volume.chapters:
            raise PrivateBookmarkError('EPUB3 권 구성에 변경이 있습니다.')
        for chapter_index, chapter in enumerate(chapters, 1):
            title, prose = chapter.title, chapter.text
            for match in expression.finditer(prose):
                offset = match.start()
                count += 1
                if len(results) < max_hits:
                    excerpt = prose[max(0, offset-65):min(len(prose),match.end()+65)]
                    results.append(EpubSearchHit(
                        volume.index, chapter_index,
                        volume.first_display_episode+chapter_index-1,
                        title, excerpt.replace('\n',' ')))
    _assert_unchanged(catalog)
    return EpubSearchReport(count, tuple(results), count > len(results))


def save_private_bookmark(catalog: PrivateVolumeCatalog, folder: str | Path,
                          *, volume_index: int, chapter_index: int,
                          explicit_author_save: bool) -> PrivateBookmark:
    if explicit_author_save is not True:
        raise PrivateBookmarkError('이 책갈피를 저장하기 위한 별도 승인이 필요합니다.')
    _assert_unchanged(catalog)
    if (type(volume_index) is not int or type(chapter_index) is not int or
            not 1 <= volume_index <= len(catalog.volumes)):
        raise PrivateBookmarkError('저장할 권과 회차를 먼저 선택하세요.')
    volume = catalog.volumes[volume_index-1]
    if not 1 <= chapter_index <= volume.chapters:
        raise PrivateBookmarkError('저장할 회차를 먼저 선택하세요.')
    directory = _directory(folder)
    snapshot = _collection_hash(catalog)
    stamp = datetime.now(timezone.utc).isoformat()
    event_id = uuid4().hex
    record = PrivateBookmark(volume_index, chapter_index,
        volume.first_display_episode+chapter_index-1,
        volume.file_sha256, snapshot, stamp, event_id)
    data = {'version': 1, 'kind':'private_epub_bookmark',
            'volume_index': volume_index, 'chapter_index': chapter_index,
            'display_episode': record.display_episode,
            'volume_sha256': volume.file_sha256,
            'collection_sha256': snapshot, 'created_at': stamp,
            'event_id': event_id}
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')
    path = directory / ('anf_private_bookmark_' + event_id + '.json')
    try:
        fd = os.open(str(path), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(blob)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        raise PrivateBookmarkError('새 책갈피 파일을 생성하지 못했습니다.') from None
    return record


def list_private_bookmarks(catalog: PrivateVolumeCatalog,
                           folder: str | Path) -> tuple[PrivateBookmark, ...]:
    _assert_unchanged(catalog)
    directory = _directory(folder)
    collection_hash = _collection_hash(catalog)
    records=[]
    candidates = sorted(directory.glob('anf_private_bookmark_*.json'))
    if len(candidates) > 1000:
        raise PrivateBookmarkError('책갈피 파일 개수 제한을 초과했습니다.')
    for path in candidates:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise PrivateBookmarkError('책갈피 파일 상태가 올바르지 않습니다.')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('kind') != 'private_epub_bookmark' or data.get('version') != 1:
                continue
            if data.get('collection_sha256') != collection_hash:
                continue
            vi, ci = data['volume_index'], data['chapter_index']
            if type(vi) is not int or type(ci) is not int or not 1 <= vi <= len(catalog.volumes):
                continue
            vol = catalog.volumes[vi-1]
            if not 1 <= ci <= vol.chapters or data.get('volume_sha256') != vol.file_sha256:
                continue
            if data.get('display_episode') != vol.first_display_episode + ci - 1:
                continue
            records.append(PrivateBookmark(vi, ci, data['display_episode'],
                vol.file_sha256, collection_hash,
                str(data.get('created_at','')), str(data.get('event_id',''))))
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            raise PrivateBookmarkError('일부 책갈피를 읽을 수 없습니다.') from None
    return tuple(sorted(records, key=lambda x:x.created_at))
