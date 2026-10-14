"""Explicit local command-line artwork generation. No publication behavior."""
from __future__ import annotations
import argparse
import sys
from .cover_art import CoverArtError, CoverSpec, save_cover_pair


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Create offline original-pattern cover and thumbnail JPEG drafts')
    parser.add_argument('--title', required=True)
    parser.add_argument('--author', required=True)
    parser.add_argument('--genre', default='NOVEL')
    parser.add_argument('--palette', choices=('nocturne', 'ember', 'verdant'), default='nocturne')
    parser.add_argument('--style', choices=('orbital', 'horizon', 'spire'), default='orbital')
    parser.add_argument('--variation', default='')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--font-path')
    a = parser.parse_args(argv)
    try:
        saved = save_cover_pair(CoverSpec(a.title,a.author,a.genre,a.palette,a.style,a.variation),
                                a.output_dir, font_path=a.font_path)
    except CoverArtError as exc:
        # No user text or paths emitted on failure.
        print(f'Cover draft failed: {exc}', file=sys.stderr)
        return 2
    print('cover.jpg:', saved.cover_sha256)
    print('thumbnail.jpg:', saved.thumbnail_sha256)
    print('Draft only. Inspect originality, typography and licensing before publication.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
