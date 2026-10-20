"""Strict offline text reader for the EPUB3 subset created by AI Novel Factory.

Validate CRC, asset and archive bounds, manifest, spine and active references
before parsing. Read only local author-owned original text; no HTML rendering,
publication, external model, network access, or writes.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from ai_novel_factory.epub3 import (
    Chapter, EpubError, MAX_CHAPTERS, NS_XHTML, verify_epub,
)


def _paragraph_text(paragraph: ET.Element) -> str:
    pieces: list[str] = []

    def walk(element: ET.Element) -> None:
        if element.text:
            pieces.append(element.text)
        for child in element:
            if child.tag == f'{{{NS_XHTML}}}br':
                pieces.append('\n')
            else:
                walk(child)
            if child.tail:
                pieces.append(child.tail)

    walk(paragraph)
    return ''.join(pieces)


def read_private_epub(path: str | Path) -> tuple[Chapter, ...]:
    if not isinstance(path, (str, Path)):
        raise EpubError('로컬 EPUB 경로가 올바르지 않습니다.')
    name = str(path)
    if (not name or name.startswith(('\\\\', '//', 'file:'))
            or not Path(name).is_absolute()):
        raise EpubError('로컬 EPUB 절대경로만 허용합니다.')
    file = Path(name)
    result = verify_epub(file)
    if not result.valid or not 1 <= result.chapters <= MAX_CHAPTERS:
        raise EpubError('검증되지 않은 EPUB3 파일입니다.')
    chapters = []
    try:
        with ZipFile(file) as archive:
            for number in range(1,result.chapters+1):
                root=ET.fromstring(
                    archive.read(f'EPUB/chapters/ch{number:04}.xhtml'))
                section=root.find(f'.//{{{NS_XHTML}}}section')
                if section is None:
                    raise EpubError('EPUB 회차 본문이 없습니다.')
                title=section.find(f'{{{NS_XHTML}}}h1')
                paragraphs=section.findall(f'{{{NS_XHTML}}}p')
                if title is None or not (title.text or '').strip() or not paragraphs:
                    raise EpubError('EPUB 회차 구조가 올바르지 않습니다.')
                prose='\n\n'.join(_paragraph_text(p) for p in paragraphs)
                if not prose.strip():
                    raise EpubError('EPUB 회차 원고가 비어 있습니다.')
                chapters.append(Chapter(title.text,prose))
    except (OSError, KeyError, ValueError, ET.ParseError, EOFError):
        raise EpubError('검증한 EPUB 본문을 읽지 못했습니다.') from None
    return tuple(chapters)
