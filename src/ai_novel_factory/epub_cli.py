"""Stage93 offline CLI: explicit user-authored chapter JSON -> preview-only EPUB3."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_novel_factory.epub3 import Chapter, EpubError, create_epub_from_metadata_file


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise EpubError('chapter JSON contains duplicate keys')
        result[key] = value
    return result


def load_user_chapters(path: str | Path) -> tuple[Chapter, ...]:
    src=Path(path)
    if src.is_symlink() or not src.is_file() or src.stat().st_size > 25_000_000:
        raise EpubError('invalid local chapter input file')
    try:
        data=json.loads(src.read_text(encoding='utf-8'), object_pairs_hook=_pairs)
    except (UnicodeError, ValueError, OSError, TypeError) as exc:
        raise EpubError('invalid local chapter input JSON') from exc
    if not isinstance(data,list) or not 1<=len(data)<=200:
        raise EpubError('chapters must be a nonempty list')
    chapters=[]
    for item in data:
        if not isinstance(item,dict) or set(item)!={'title','text'}:
            raise EpubError('chapter input fields invalid')
        chapters.append(Chapter(item['title'],item['text']))
    return tuple(chapters)


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description='Offline EPUB3 draft preview (never publishes)')
    parser.add_argument('--metadata',required=True,help='Stage92 draft metadata JSON')
    parser.add_argument('--chapters',required=True,help='User-authored JSON list of {title,text}')
    parser.add_argument('--output-dir',required=True,help='Existing directory for book.epub')
    parser.add_argument('--cover',default=None,help='Optional local cover.jpg from Stage91')
    args=parser.parse_args(argv)
    try:
        result=create_epub_from_metadata_file(args.metadata,load_user_chapters(args.chapters),
                        args.output_dir,cover_path=args.cover)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'EPUB draft export rejected: {type(exc).__name__}\n')
    print(json.dumps({'file': 'book.epub', 'sha256': result.sha256,
                      'chapters': result.chapters, 'publication_approved': False,
                      'published': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
