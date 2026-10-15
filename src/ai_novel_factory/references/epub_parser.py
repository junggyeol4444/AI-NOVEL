"""Offline, bounded EPUB spine XHTML parser; never persists or uploads source text."""
from __future__ import annotations

from io import BytesIO
import posixpath
import re
import stat
import zlib
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from .plaintext_parser import ParsedBlock, ParsedReference, ReferenceParseError

MAX_EPUB_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1024
MAX_SPINE_DOCUMENTS = 500
MAX_TEXT_CHARS = 2_000_000
MAX_BLOCKS = 50_000
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_XHTML_BYTES = 8 * 1024 * 1024
MAX_XML_DEPTH = 128
MAX_XML_ELEMENTS = 100_000
_UNSAFE_XML = re.compile(br'<!\s*(?:DOCTYPE|ENTITY)\b', re.I)
_SKIP = frozenset({'script', 'style', 'svg', 'math', 'noscript', 'iframe', 'head'})
_BLOCK = frozenset({'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote'})


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def _safe_path(name: str) -> str:
    if (not name or name.startswith(('/', '\\')) or '\\' in name or ':' in name
            or '%' in name or '\x00' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ReferenceParseError('EPUB 내부 경로가 안전하지 않습니다.')
    return name


def _relative(base: str, href: str) -> str:
    url = urlsplit(href)
    if not href or url.scheme or url.netloc or url.query or url.fragment:
        raise ReferenceParseError('EPUB 문서 경로가 올바르지 않습니다.')
    # EPUB manifest hrefs are relative to the OPF directory. A single
    # parent segment is legitimate (e.g. OPS/book.opf -> ../Text/1.xhtml),
    # but the *resolved* archive path must remain inside the ZIP root.
    target = url.path
    if (not target or target.startswith(('/', '\\')) or '\\' in target
            or ':' in target or '%' in target or '\x00' in target
            or any(part == '' for part in target.split('/'))):
        raise ReferenceParseError('EPUB 문서 경로가 올바르지 않습니다.')
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
    return _safe_path(resolved)


def _xml(data: bytes) -> ET.Element:
    # ElementTree expands internal entities. Checking the raw bytes alone can
    # miss a UTF-16 encoded DOCTYPE (NUL bytes between ASCII characters).
    # Fail closed on non-UTF-8 XML until a hardened multi-encoding parser exists.
    try:
        decoded = data.decode('utf-8-sig', errors='strict')
    except UnicodeError:
        raise ReferenceParseError('EPUB XML은 UTF-8만 지원합니다.') from None
    if '\ufeff' in decoded or _UNSAFE_XML.search(decoded.encode('utf-8')):
        raise ReferenceParseError('EPUB DTD/ENTITY는 허용하지 않습니다.')
    # ET.fromstring(str) can accept a misleading XML declaration such as
    # encoding="UTF-16" even though the supplied bytes were UTF-8. Require
    # the declaration to agree with the only supported byte encoding.
    declaration = re.match(r'\A<\?xml\b[^>]*\?>', decoded, re.I)
    if declaration:
        declared = re.search(r'\bencoding\s*=\s*([\"\'])([^\"\']+)\1',
                             declaration.group(0), re.I)
        if declared and declared.group(2).lower() != 'utf-8':
            raise ReferenceParseError('EPUB XML 인코딩 선언이 UTF-8과 다릅니다.')
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError:
        raise ReferenceParseError('EPUB XML 형식이 올바르지 않습니다.') from None
    # Bound adversarial nesting and node counts before recursive text walking.
    stack = [(root, 1)]
    seen = 0
    while stack:
        element, depth = stack.pop()
        seen += 1
        if depth > MAX_XML_DEPTH or seen > MAX_XML_ELEMENTS:
            raise ReferenceParseError('EPUB XML 중첩 또는 요소 수 제한을 초과했습니다.')
        stack.extend((child, depth + 1) for child in element)
    return root


def _text(node: ET.Element) -> str:
    """Collect only visible paragraph text, preserving inline tails and breaks."""
    def visit(element: ET.Element) -> str:
        tag = _local(element.tag).lower()
        if tag in _SKIP:
            return ''
        parts = [element.text or '']
        for child in element:
            if _local(child.tag).lower() == 'br':
                parts.append('\n')
            else:
                parts.append(visit(child))
            parts.append(child.tail or '')
        return ''.join(parts)
    return visit(node).strip()


def _visible_blocks(node: ET.Element):
    if _local(node.tag).lower() in _SKIP:
        return
    children = [block for child in node for block in _visible_blocks(child)]
    # A blockquote may wrap paragraphs: do not count the wrapper twice.
    if _local(node.tag).lower() in _BLOCK and not children:
        yield node
    else:
        yield from children


def parse_epub_bytes(raw: bytes, *, max_text_chars: int = MAX_TEXT_CHARS) -> ParsedReference:
    """Read EPUB spine in order. Reject encrypted, malformed and oversized archives."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_EPUB_BYTES:
        raise ReferenceParseError('EPUB 바이트 크기가 올바르지 않습니다.')
    if type(max_text_chars) is not int or not 1 <= max_text_chars <= MAX_TEXT_CHARS:
        raise ReferenceParseError('EPUB 본문 제한이 올바르지 않습니다.')
    try:
        with ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not 3 <= len(infos) <= MAX_ARCHIVE_MEMBERS:
                raise ReferenceParseError('EPUB 압축 항목 수가 올바르지 않습니다.')
            first = infos[0]
            if (first.filename != 'mimetype' or first.compress_type != ZIP_STORED
                    or first.file_size != len(b'application/epub+zip')):
                raise ReferenceParseError('EPUB mimetype이 올바르지 않습니다.')
            names: set[str] = set()
            total = 0
            for info in infos:
                name = _safe_path(info.filename[:-1] if info.is_dir() else info.filename)
                if (name in names or info.flag_bits & 1
                        or stat.S_ISLNK(info.external_attr >> 16)):
                    raise ReferenceParseError('EPUB 중복·암호화·링크 항목이 있습니다.')
                names.add(name)
                if info.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    raise ReferenceParseError('EPUB 압축 형식을 지원하지 않습니다.')
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ReferenceParseError('EPUB 내부 파일이 너무 큽니다.')
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise ReferenceParseError('EPUB 압축 해제 제한을 초과했습니다.')
                if info.file_size and (not info.compress_size or info.file_size > 500 * info.compress_size):
                    raise ReferenceParseError('EPUB 압축 비율이 비정상적입니다.')
            if 'META-INF/encryption.xml' in names:
                raise ReferenceParseError('암호화된 EPUB은 분석할 수 없습니다.')
            if archive.read(first) != b'application/epub+zip':
                raise ReferenceParseError('EPUB mimetype이 올바르지 않습니다.')
            container_path = 'META-INF/container.xml'
            if container_path not in names or archive.getinfo(container_path).file_size > MAX_XML_BYTES:
                raise ReferenceParseError('EPUB container.xml이 없습니다.')
            container = _xml(archive.read(container_path))
            if _local(container.tag) != 'container':
                raise ReferenceParseError('EPUB container 구조가 올바르지 않습니다.')
            roots = [n for n in container.iter() if _local(n.tag) == 'rootfile']
            if len(roots) != 1 or roots[0].get('media-type') != 'application/oebps-package+xml':
                raise ReferenceParseError('EPUB 패키지 정보가 올바르지 않습니다.')
            opf = _safe_path(roots[0].get('full-path', ''))
            if opf not in names or archive.getinfo(opf).file_size > MAX_XML_BYTES:
                raise ReferenceParseError('EPUB OPF 파일이 없습니다.')
            package = _xml(archive.read(opf))
            if _local(package.tag) != 'package':
                raise ReferenceParseError('EPUB OPF 구조가 올바르지 않습니다.')
            manifests = [n for n in package if _local(n.tag) == 'manifest']
            spines = [n for n in package if _local(n.tag) == 'spine']
            if len(manifests) != 1 or len(spines) != 1:
                raise ReferenceParseError('EPUB 목차/본문 구성이 올바르지 않습니다.')
            items: dict[str, str] = {}
            for item in manifests[0]:
                if _local(item.tag) != 'item':
                    continue
                ident = item.get('id', '')
                if not ident or ident in items:
                    raise ReferenceParseError('EPUB 문서 식별자가 중복됐습니다.')
                items[ident] = (_relative(opf, item.get('href', ''))
                                if item.get('media-type') == 'application/xhtml+xml' else '')
            spine = [n.get('idref', '') for n in spines[0]
                     if _local(n.tag) == 'itemref' and n.get('linear', 'yes') != 'no']
            if not 1 <= len(spine) <= MAX_SPINE_DOCUMENTS or len(spine) != len(set(spine)):
                raise ReferenceParseError('EPUB 본문 순서가 올바르지 않습니다.')
            blocks: list[ParsedBlock] = []
            count = 0
            for ident in spine:
                member = items.get(ident)
                if not member or member not in names or archive.getinfo(member).file_size > MAX_XHTML_BYTES:
                    raise ReferenceParseError('EPUB 본문 파일이 없거나 지원하지 않습니다.')
                root = _xml(archive.read(member))
                if _local(root.tag).lower() != 'html':
                    raise ReferenceParseError('EPUB XHTML 구조가 올바르지 않습니다.')
                bodies = [child for child in root if _local(child.tag).lower() == 'body']
                if len(bodies) != 1:
                    raise ReferenceParseError('EPUB XHTML 본문 구조가 올바르지 않습니다.')
                for element in _visible_blocks(bodies[0]):
                    tag = _local(element.tag).lower()
                    if tag not in _BLOCK:
                        continue
                    # Do not accidentally extract content of nested active nodes.
                    value = _text(element)
                    if not value:
                        continue
                    if any((ord(ch) < 32 and ch not in '\n\r\t') or ord(ch) == 127 for ch in value):
                        raise ReferenceParseError('EPUB 본문에 제어 문자가 있습니다.')
                    count += len(value)
                    if count > max_text_chars or len(blocks) >= MAX_BLOCKS:
                        raise ReferenceParseError('EPUB 본문이 길이 제한을 초과했습니다.')
                    number = len(blocks) + 1
                    kind = 'heading' if tag.startswith('h') and len(tag) == 2 else 'paragraph'
                    blocks.append(ParsedBlock(kind, number, number, value,
                                              int(tag[1]) if kind == 'heading' else None))
            if not blocks:
                raise ReferenceParseError('EPUB 본문을 추출할 수 없습니다.')
            return ParsedReference('epub', None, '\n\n'.join(b.text for b in blocks), tuple(blocks))
    except ReferenceParseError:
        raise
    except (BadZipFile, OSError, EOFError, KeyError, ValueError, RuntimeError,
            NotImplementedError, ET.ParseError, zlib.error):
        raise ReferenceParseError('EPUB 파일을 안전하게 해석할 수 없습니다.') from None
