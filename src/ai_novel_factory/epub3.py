"""Stage 93 / ANF-REQ-064: offline, preview-only EPUB 3 generation and validation.

User-original chapters + stage92 unsigned metadata only. No remote resources, model
calls, publication, account upload, approval or manuscript finalization.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from pathlib import Path, PurePosixPath
import os
import re
import stat
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

from ai_novel_factory.publication_metadata import MetadataDraft, validate_metadata, load_metadata


class EpubError(ValueError):
    """Never includes full user text, file paths or secret values."""


EPUB_NAME = 'book.epub'
MIMETYPE = b'application/epub+zip'
OCF = 'META-INF/container.xml'
OPF = 'EPUB/package.opf'
NAV = 'EPUB/nav.xhtml'
STYLE = 'EPUB/styles/book.css'
MAX_CHAPTERS = 200
MAX_CHAPTER_BYTES = 2_000_000
MAX_TOTAL_CHAPTER_BYTES = 20_000_000
MAX_COVER_BYTES = 12_000_000
MAX_ARCHIVE_BYTES = 40_000_000
NS_OPF = 'http://www.idpf.org/2007/opf'
NS_DC = 'http://purl.org/dc/elements/1.1/'
NS_XHTML = 'http://www.w3.org/1999/xhtml'
NS_CONTAINER = 'urn:oasis:names:tc:opendocument:xmlns:container'
NS_EPUB = 'http://www.idpf.org/2007/ops'
_SHA = re.compile(r'[a-f0-9]{64}\Z')


@dataclass(frozen=True, slots=True)
class Chapter:
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class EpubOutput:
    path: Path
    sha256: str
    chapters: int
    contains_cover: bool
    publication_approved: bool = False
    published: bool = False


@dataclass(frozen=True, slots=True)
class EpubVerification:
    valid: bool
    chapters: int
    contains_cover: bool
    publication_approved: bool = False
    published: bool = False


def _text(value: object, field: str, max_chars: int, *, multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise EpubError(f'{field}: text required')
    value = unicodedata.normalize('NFC', value.replace('\r\n', '\n').replace('\r', '\n')).strip()
    if not value or len(value) > max_chars:
        raise EpubError(f'{field}: empty or exceeds size limit')
    for c in value:
        cat = unicodedata.category(c)
        if cat in {'Cc','Cf','Cs','Zl','Zp'} and not (multiline and c == '\n'):
            raise EpubError(f'{field}: control/invisible characters prohibited')
    return value


def _normalize_chapters(chapters: object) -> tuple[Chapter, ...]:
    if not isinstance(chapters, (tuple, list)) or not (1 <= len(chapters) <= MAX_CHAPTERS):
        raise EpubError('chapters: 1 to 200 chapters required')
    norm, total = [], 0
    for chapter in chapters:
        if not isinstance(chapter, Chapter):
            raise EpubError('chapters: Chapter values required')
        title = _text(chapter.title, 'chapter title', 150)
        body = _text(chapter.text, 'chapter text', MAX_CHAPTER_BYTES, multiline=True)
        data_len = len(body.encode('utf-8'))
        if data_len > MAX_CHAPTER_BYTES:
            raise EpubError('chapter: UTF-8 size limit exceeded')
        total += data_len
        if total > MAX_TOTAL_CHAPTER_BYTES:
            raise EpubError('chapters: total size limit exceeded')
        norm.append(Chapter(title, body))
    return tuple(norm)


def _xml(value: str) -> str:
    return escape(value, quote=True).replace("'", '&apos;')


def _chapter_xhtml(chapter: Chapter, ordinal: int, language: str) -> bytes:
    paragraphs = ''.join(f'<p>{_xml(part)}</p>' for part in re.split(r'\n\s*\n', chapter.text)
                         if part.strip())
    # preserve within-paragraph linebreaks without inserting raw HTML from manuscript
    paragraphs = paragraphs.replace('\n', '<br/>')
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<html xmlns="{NS_XHTML}" xml:lang="{language}" lang="{language}">'
            f'<head><title>{_xml(chapter.title)}</title><link rel="stylesheet" '
            f'href="styles/book.css" type="text/css"/></head><body>'
            f'<section><h1>{_xml(chapter.title)}</h1>{paragraphs}</section></body></html>').encode('utf-8')


def _assets(metadata: MetadataDraft, chapters: tuple[Chapter, ...], cover: bytes | None) -> dict[str, bytes]:
    assets: dict[str, bytes] = {}
    assets['mimetype'] = MIMETYPE
    assets[OCF] = (f'<?xml version="1.0" encoding="utf-8"?>'
                   f'<container version="1.0" xmlns="{NS_CONTAINER}">'
                   f'<rootfiles><rootfile full-path="{OPF}" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>').encode()
    assets[STYLE] = b'body{font-family:serif;line-height:1.65}h1{font-size:1.4em}p{margin:.6em 0;text-indent:1em}img{max-width:100%;height:auto}'
    toc = ''.join(f'<li><a href="chapters/ch{n:04}.xhtml">{_xml(ch.title)}</a></li>'
                  for n,ch in enumerate(chapters,1))
    assets[NAV] = (f'<?xml version="1.0" encoding="utf-8"?>'
                   f'<html xmlns="{NS_XHTML}" xmlns:epub="{NS_EPUB}" xml:lang="{metadata.language}">'
                   f'<head><title>{_xml(metadata.title)} — Contents</title></head>'
                   f'<body><nav epub:type="toc" id="toc"><h1>목차</h1><ol>{toc}</ol></nav></body></html>').encode('utf-8')
    if cover is not None:
        assets['EPUB/images/cover.jpg'] = cover
        assets['EPUB/cover.xhtml'] = (f'<?xml version="1.0" encoding="utf-8"?>'
                                      f'<html xmlns="{NS_XHTML}" xml:lang="{metadata.language}"><head>'
                                      f'<title>Cover</title></head><body><div><img src="images/cover.jpg" '
                                      f'alt="{_xml(metadata.title)}"/></div></body></html>').encode('utf-8')
    for n,ch in enumerate(chapters,1):
        assets[f'EPUB/chapters/ch{n:04}.xhtml'] = _chapter_xhtml(ch,n,metadata.language)
    items = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
             '<item id="css" href="styles/book.css" media-type="text/css"/>']
    spine = []
    if cover is not None:
        items.extend(['<item id="coverimage" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>',
                      '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>'])
        spine.append('<itemref idref="cover"/>')
    for n in range(1,len(chapters)+1):
        key=f'c{n:04}'
        items.append(f'<item id="{key}" href="chapters/ch{n:04}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{key}"/>')
    modified=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    subjects=''.join(f'<dc:subject>{_xml(k)}</dc:subject>' for k in metadata.keywords)
    assets[OPF] = (f'<?xml version="1.0" encoding="utf-8"?>'
       f'<package xmlns="{NS_OPF}" xmlns:dc="{NS_DC}" version="3.0" '
       f'unique-identifier="bookid" xml:lang="{metadata.language}">'
       f'<metadata><dc:identifier id="bookid">urn:ai-novel-factory:{_xml(metadata.project_id)}</dc:identifier>'
       f'<dc:title>{_xml(metadata.title)}</dc:title><dc:creator>{_xml(metadata.author)}</dc:creator>'
       f'<dc:language>{metadata.language}</dc:language><dc:description>{_xml(metadata.description)}</dc:description>'
       f'<dc:subject>{_xml(metadata.category)}</dc:subject>{subjects}'
       f'<meta property="dcterms:modified">{modified}</meta></metadata>'
       f'<manifest>{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>').encode('utf-8')
    return assets


def _read_cover(path: str | Path | None) -> bytes | None:
    if path is None:
        return None
    src=Path(path)
    if src.is_symlink() or not src.is_file() or src.stat().st_size > MAX_COVER_BYTES:
        raise EpubError('cover: invalid local JPG')
    data=src.read_bytes()
    if len(data) < 32 or not data.startswith(b'\xff\xd8\xff') or not data.endswith(b'\xff\xd9'):
        raise EpubError('cover: JPEG signature invalid')
    return data


def create_epub(metadata: MetadataDraft, chapters: tuple[Chapter,...] | list[Chapter],
                directory: str | Path, *, cover_path: str | Path | None = None) -> EpubOutput:
    """Export private preview EPUB. Does NOT assert user approval or finalize a manuscript."""
    metadata=validate_metadata(metadata)
    chapters=_normalize_chapters(chapters)
    cover=_read_cover(cover_path)
    dest=Path(directory)
    if dest.is_symlink() or not dest.is_dir():
        raise EpubError('an existing non-symlink output directory is required')
    path=dest/EPUB_NAME
    assets=_assets(metadata,chapters,cover)
    # Exclusive create: no symlink follow, no overwrite. Remove only our incomplete file.
    try:
        fd=os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        raise EpubError('EPUB output already exists or is inaccessible') from exc
    try:
        with os.fdopen(fd,'wb') as handle:
            with zipfile.ZipFile(handle,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
                z.writestr('mimetype', MIMETYPE, compress_type=zipfile.ZIP_STORED)
                for name,body in assets.items():
                    if name != 'mimetype':
                        z.writestr(name,body)
            handle.flush()
            os.fsync(handle.fileno())
        verify_epub(path, expected_chapters=len(chapters), expect_cover=cover is not None)
        return EpubOutput(path,sha256(path.read_bytes()).hexdigest(),len(chapters),cover is not None)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def create_epub_from_metadata_file(metadata_path: str | Path,
                                   chapters: tuple[Chapter,...] | list[Chapter],
                                   directory: str | Path, *, cover_path: str | Path | None = None) -> EpubOutput:
    """Tie EPUB output to a validated stage92 local draft, never to a reference book."""
    return create_epub(load_metadata(metadata_path),chapters,directory,cover_path=cover_path)


def _parse_xml(body: bytes) -> ET.Element:
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper() or len(body)>MAX_CHAPTER_BYTES+30000:
        raise EpubError('unsafe or oversized EPUB XML')
    try:
        return ET.fromstring(body)
    except ET.ParseError as exc:
        raise EpubError('invalid EPUB XML') from exc


def verify_epub(path: str | Path, *, expected_chapters: int | None = None,
                expect_cover: bool | None = None, expected_sha256: str | None = None) -> EpubVerification:
    """Strict offline validator for the EPUB3 subset produced by this generator.

    Does not replace EPUBCheck or validate arbitrary third-party EPUB packages.
    """
    src=Path(path)
    if src.is_symlink() or not src.is_file() or src.stat().st_size>MAX_ARCHIVE_BYTES:
        raise EpubError('EPUB file missing or exceeds limit')
    if expected_sha256 is not None:
        if not isinstance(expected_sha256,str) or not _SHA.fullmatch(expected_sha256) or sha256(src.read_bytes()).hexdigest()!=expected_sha256:
            raise EpubError('EPUB integrity mismatch')
    try:
        with zipfile.ZipFile(src) as z:
            entries=z.infolist()
            if not entries or len(entries)>MAX_CHAPTERS+12:
                raise EpubError('EPUB entries count invalid')
            first=entries[0]
            if first.filename!='mimetype' or first.compress_type != zipfile.ZIP_STORED or first.file_size!=len(MIMETYPE) or z.read(first)!=MIMETYPE:
                raise EpubError('EPUB mimetype must be the first uncompressed entry')
            names=[a.filename for a in entries]
            if (len(names)!=len(set(names)) or any(n.startswith('/') or '\\' in n or '..' in PurePosixPath(n).parts or n.endswith('/') for n in names)
                    or any(stat.S_ISLNK(a.external_attr >> 16) for a in entries)):
                raise EpubError('unsafe or duplicate EPUB paths')
            if any(a.file_size>MAX_CHAPTER_BYTES+30000 for a in entries if a.filename!='EPUB/images/cover.jpg') or sum(a.file_size for a in entries)>MAX_TOTAL_CHAPTER_BYTES+MAX_COVER_BYTES+500_000:
                raise EpubError('EPUB uncompressed size over limit')
            if z.testzip() is not None:
                raise EpubError('EPUB CRC verification failed')
            must={'mimetype',OCF,OPF,NAV,STYLE}
            if not must.issubset(names):
                raise EpubError('required EPUB container files missing')
            container=_parse_xml(z.read(OCF))
            rootfile=container.find(f'.//{{{NS_CONTAINER}}}rootfile')
            if rootfile is None or rootfile.attrib.get('full-path')!=OPF or rootfile.attrib.get('media-type')!='application/oebps-package+xml':
                raise EpubError('EPUB container rootfile invalid')
            pkg=_parse_xml(z.read(OPF))
            if pkg.tag!=f'{{{NS_OPF}}}package' or pkg.attrib.get('version')!='3.0' or pkg.attrib.get('unique-identifier')!='bookid':
                raise EpubError('EPUB 3 package document invalid')
            metadata=pkg.find(f'{{{NS_OPF}}}metadata')
            manifest=pkg.find(f'{{{NS_OPF}}}manifest')
            spine=pkg.find(f'{{{NS_OPF}}}spine')
            if metadata is None or manifest is None or spine is None:
                raise EpubError('EPUB metadata/manifest/spine missing')
            for tag in ('identifier','title','creator','language'):
                el=metadata.find(f'{{{NS_DC}}}{tag}')
                if el is None or not (el.text or '').strip():
                    raise EpubError('required Dublin Core metadata missing')
            mods=[v for v in metadata.findall(f'{{{NS_OPF}}}meta') if v.attrib.get('property')=='dcterms:modified']
            if len(mods)!=1 or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',mods[0].text or ''):
                raise EpubError('EPUB modified timestamp missing')
            if metadata.find(f'{{{NS_DC}}}identifier').attrib.get('id')!='bookid':
                raise EpubError('EPUB identifier ID missing')
            items={}
            paths=set()
            covers=0
            nav_count=0
            for item in manifest.findall(f'{{{NS_OPF}}}item'):
                key=item.attrib.get('id'); href=item.attrib.get('href'); media=item.attrib.get('media-type'); props=item.attrib.get('properties','')
                if not key or not href or not media or key in items or href.startswith('/') or '\\' in href or '..' in PurePosixPath(href).parts or ':' in href or '#' in href:
                    raise EpubError('EPUB manifest item invalid')
                path='EPUB/'+href
                if path not in names or path in paths:
                    raise EpubError('EPUB manifest path not found or duplicate')
                if media not in ('application/xhtml+xml','image/jpeg','text/css'):
                    raise EpubError('unexpected EPUB asset type')
                if media=='image/jpeg' and path!='EPUB/images/cover.jpg':
                    raise EpubError('unexpected EPUB JPG')
                items[key]=(path,media)
                paths.add(path)
                if props=='nav':
                    nav_count+=1
                    if path!=NAV: raise EpubError('EPUB TOC path invalid')
                elif 'nav' in props.split():
                    raise EpubError('multiple EPUB navigation items')
                if props=='cover-image':
                    covers+=1
                    if path!='EPUB/images/cover.jpg': raise EpubError('EPUB cover reference invalid')
                elif 'cover-image' in props.split():
                    raise EpubError('multiple cover images')
            if nav_count!=1 or covers>1 or set(names)!=(must|paths):
                raise EpubError('EPUB manifest does not match its files')
            if 'nav' not in items or items['nav'][0]!=NAV:
                raise EpubError('navigation missing')
            spine_ids=[]
            for ref in spine.findall(f'{{{NS_OPF}}}itemref'):
                rid=ref.attrib.get('idref')
                if rid not in items or items[rid][1]!='application/xhtml+xml' or rid in spine_ids or rid=='nav':
                    raise EpubError('EPUB spine invalid')
                spine_ids.append(rid)
            chapters=[item[0] for k,item in items.items() if re.fullmatch(r'c\d{4}',k)]
            if not chapters or len(chapters)>MAX_CHAPTERS or len(spine_ids)!=len(chapters)+covers:
                raise EpubError('EPUB chapter count or spine invalid')
            ordered=[f'EPUB/chapters/ch{n:04}.xhtml' for n in range(1,len(chapters)+1)]
            if [items[k][0] for k in spine_ids] != (['EPUB/cover.xhtml'] if covers else [])+ordered:
                raise EpubError('EPUB chapter order invalid')
            if expected_chapters is not None and len(chapters)!=expected_chapters:
                raise EpubError('EPUB chapter count differs from source')
            if expect_cover is not None and bool(covers)!=expect_cover:
                raise EpubError('EPUB cover expectation differs')
            if bool(covers)!=('EPUB/cover.xhtml' in paths):
                raise EpubError('EPUB cover page mismatch')
            if covers:
                jpg=z.read('EPUB/images/cover.jpg')
                if len(jpg)>MAX_COVER_BYTES or not jpg.startswith(b'\xff\xd8\xff') or not jpg.endswith(b'\xff\xd9'):
                    raise EpubError('EPUB cover format invalid')
            nav=_parse_xml(z.read(NAV))
            toc=nav.find(f'.//{{{NS_XHTML}}}nav')
            if toc is None or toc.attrib.get(f'{{{NS_EPUB}}}type')!='toc':
                raise EpubError('EPUB navigation table of contents missing')
            links=toc.findall(f'.//{{{NS_XHTML}}}a')
            if [a.attrib.get('href') for a in links]!=[p.removeprefix('EPUB/') for p in ordered]:
                raise EpubError('EPUB navigation links incorrect')
            for name in paths:
                if name.endswith('.xhtml'):
                    node=_parse_xml(z.read(name))
                    if node.tag!=f'{{{NS_XHTML}}}html' or node.find(f'{{{NS_XHTML}}}body') is None:
                        raise EpubError('invalid XHTML chapter/navigation')
                    for element in node.iter():
                        if element.tag.split('}')[-1].lower() in ('script','iframe','object','embed','form'):
                            raise EpubError('active content prohibited')
                        for attr,value in element.attrib.items():
                            if attr.split('}')[-1].lower().startswith('on') or value.lower().startswith(('http:','https:','javascript:','data:','file:')):
                                raise EpubError('external or active references prohibited')
            return EpubVerification(True,len(chapters),bool(covers))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, KeyError, EOFError) as exc:
        raise EpubError('invalid or unreadable EPUB archive') from exc
