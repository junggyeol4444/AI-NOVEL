"""Stage 92 / ANF-REQ-063: draft-only, offline publication metadata.

Only user-original inputs; references, manuscript and secrets are never read.
No pricing service, inferred price, auto approval, upload or publication.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import unicodedata


class MetadataError(ValueError):
    """Sanitized message that does not echo user prose or the output path."""


CURRENCY_DECIMALS = {'KRW': 0, 'JPY': 0, 'USD': 2, 'EUR': 2}
LANGUAGES = frozenset(('ko', 'en', 'ja'))
STATUS = 'DRAFT_REQUIRES_USER_REVIEW'
SOURCE = 'USER_ORIGINAL_INPUT_ONLY'
FILE_NAME = 'publication_metadata.json'
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')


@dataclass(frozen=True, slots=True)
class MetadataDraft:
    project_id: str
    title: str
    author: str
    description: str
    category: str
    keywords: tuple[str, ...]
    price_amount: str
    currency: str = 'KRW'
    language: str = 'ko'
    status: str = STATUS
    source: str = SOURCE
    version: int = 1
    publication_approved: bool = False
    published: bool = False


@dataclass(frozen=True, slots=True)
class MetadataOutput:
    path: Path
    sha256: str
    publication_approved: bool = False
    published: bool = False


def _safe_text(value: str, field: str, limit: int, *, multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise MetadataError(f'{field}: text required')
    value = unicodedata.normalize('NFC', value.replace('\r\n', '\n'))
    value = value.strip()
    if not value or len(value) > limit:
        raise MetadataError(f'{field}: empty or too long')
    for c in value:
        category = unicodedata.category(c)
        if category in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp') and not (multiline and c == '\n'):
            raise MetadataError(f'{field}: control or invisible text')
        if c == '\n' and not multiline:
            raise MetadataError(f'{field}: multiline not allowed')
    return value


def _price(value: str, currency: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?', value):
        raise MetadataError('price: explicit nonnegative decimal text required')
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise MetadataError('price: invalid decimal') from exc
    if d > 10_000_000:
        raise MetadataError('price: over local maximum')
    decimals = CURRENCY_DECIMALS[currency]
    if d != d.quantize(Decimal(1).scaleb(-decimals)):
        raise MetadataError('price: unsupported currency fraction')
    return f'{d:.{decimals}f}'


def validate_metadata(value: MetadataDraft, *, cover_title: str | None = None,
                      cover_author: str | None = None) -> MetadataDraft:
    """Local cross-platform draft contract, not any publisher's platform schema."""
    if not isinstance(value, MetadataDraft):
        raise MetadataError('MetadataDraft required')
    if not isinstance(value.project_id, str) or not _ID.fullmatch(value.project_id):
        raise MetadataError('project_id: invalid identifier')
    if value.currency not in CURRENCY_DECIMALS:
        raise MetadataError('currency: unsupported local currency')
    if value.language not in LANGUAGES:
        raise MetadataError('language: unsupported local language')
    if (value.status != STATUS or value.source != SOURCE or type(value.version) is not int or
            value.version != 1 or value.publication_approved is not False or value.published is not False):
        raise MetadataError('only unsigned, unpublished version-one drafts supported')
    title = _safe_text(value.title, 'title', 90)
    author = _safe_text(value.author, 'author', 70)
    description = _safe_text(value.description, 'description', 2000, multiline=True)
    category = _safe_text(value.category, 'category', 60)
    if not isinstance(value.keywords, tuple) or not 1 <= len(value.keywords) <= 12:
        raise MetadataError('keywords: 1 to 12 text keywords required')
    keywords = tuple(_safe_text(k, 'keyword', 40) for k in value.keywords)
    if len(set(k.casefold() for k in keywords)) != len(keywords):
        raise MetadataError('keywords: duplicates not allowed')
    price = _price(value.price_amount, value.currency)
    if cover_title is not None and title != _safe_text(cover_title, 'cover title', 90):
        raise MetadataError('title differs from cover title')
    if cover_author is not None and author != _safe_text(cover_author, 'cover author', 70):
        raise MetadataError('author differs from cover author')
    return replace(value, title=title, author=author, description=description,
                   category=category, keywords=keywords, price_amount=price)


def draft_from_original_premise(*, project_id: str, title: str, author: str,
                                original_logline: str, category: str,
                                keywords: tuple[str, ...], price_amount: str,
                                currency: str = 'KRW', language: str = 'ko') -> MetadataDraft:
    """Make an editable candidate only from fields explicitly provided by its owner.

    Does not read or derive phrases from reference fiction or auto-determine price.
    """
    return validate_metadata(MetadataDraft(project_id, title, author,
                                            original_logline, category, keywords,
                                            price_amount, currency, language))


def _payload(value: MetadataDraft) -> dict:
    return dict(version=value.version, project_id=value.project_id,
                title=value.title, author=value.author,
                description=value.description, category=value.category,
                keywords=list(value.keywords), price=dict(amount=value.price_amount,
                currency=value.currency), language=value.language, status=value.status,
                source=value.source, publication_approved=value.publication_approved,
                published=value.published)


def _canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def save_metadata(value: MetadataDraft, directory: str | Path, *,
                  cover_title: str | None = None,
                  cover_author: str | None = None) -> MetadataOutput:
    """Create local UTF-8 draft JSON once, exclusively; never overwrite another file."""
    value = validate_metadata(value, cover_title=cover_title, cover_author=cover_author)
    target = Path(directory)
    if target.is_symlink() or not target.is_dir():
        raise MetadataError('an existing, non-symlink output directory is required')
    path = target / FILE_NAME
    body = _payload(value)
    digest = sha256(_canonical(body)).hexdigest()
    contents = _canonical({'metadata': body, 'sha256': digest})
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
            try:
                f.write(contents)
                f.flush()
                os.fsync(f.fileno())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
    except FileExistsError as exc:
        raise MetadataError('metadata file already exists; never overwrite') from exc
    except OSError as exc:
        raise MetadataError('unable to save metadata draft') from exc
    return MetadataOutput(path, digest)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    d: dict = {}
    for k, v in pairs:
        if k in d:
            raise MetadataError('duplicate metadata keys')
        d[k] = v
    return d


def load_metadata(path: str | Path) -> MetadataDraft:
    """Reject missing/tampered/unknown schema; never turn a draft into publication approval."""
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16384:
        raise MetadataError('invalid local metadata file')
    try:
        document = json.loads(source.read_text(encoding='utf-8'), object_pairs_hook=_unique_pairs)
        if not isinstance(document, dict) or set(document) != {'metadata', 'sha256'}:
            raise MetadataError('invalid document envelope')
        body, digest = document['metadata'], document['sha256']
        if not isinstance(body, dict) or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise MetadataError('invalid draft checksum')
        if sha256(_canonical(body)).hexdigest() != digest:
            raise MetadataError('draft metadata integrity check failed')
        if set(body) != {'version','project_id','title','author','description','category',
                         'keywords','price','language','status','source','publication_approved','published'}:
            raise MetadataError('unknown metadata fields')
        price = body['price']
        if not isinstance(price, dict) or set(price) != {'amount', 'currency'}:
            raise MetadataError('invalid price object')
        keywords = body['keywords']
        if not isinstance(keywords, list):
            raise MetadataError('invalid keywords')
        item = MetadataDraft(project_id=body['project_id'], title=body['title'],
                             author=body['author'], description=body['description'],
                             category=body['category'], keywords=tuple(keywords),
                             price_amount=price['amount'], currency=price['currency'],
                             language=body['language'], status=body['status'],
                             source=body['source'], version=body['version'],
                             publication_approved=body['publication_approved'],
                             published=body['published'])
        return validate_metadata(item)
    except (UnicodeError, OSError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, MetadataError):
            raise
        raise MetadataError('invalid or unreadable draft metadata') from exc
