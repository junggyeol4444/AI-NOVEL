"""Stage94 CLI: local-only user-authored episode title/body/author-note export."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_novel_factory.episode_upload_files import (UploadEpisode, UploadDraftError,
                                                      export_from_metadata_file)


def _unique_pairs(pairs):
    obj={}
    for k,v in pairs:
        if k in obj:
            raise UploadDraftError('duplicate episode JSON field')
        obj[k]=v
    return obj


def load_user_episodes(path: str | Path) -> list[UploadEpisode]:
    src=Path(path)
    if src.is_symlink() or not src.is_file() or src.stat().st_size > 26_000_000:
        raise UploadDraftError('invalid local episode JSON file')
    try:
        items=json.loads(src.read_text(encoding='utf-8'), object_pairs_hook=_unique_pairs)
        if not isinstance(items,list) or not 1<=len(items)<=200:
            raise UploadDraftError('episode JSON requires nonempty list')
        result=[]
        for item in items:
            if not isinstance(item,dict) or set(item) != {'episode_number','title','body','author_note'}:
                raise UploadDraftError('episode JSON fields invalid')
            result.append(UploadEpisode(**item))
        return result
    except (UnicodeError, OSError, ValueError, TypeError) as exc:
        if isinstance(exc, UploadDraftError):
            raise
        raise UploadDraftError('unreadable local episode JSON') from exc


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description='Prepare local web-novel upload DRAFT files (never uploads)')
    parser.add_argument('--metadata', required=True, help='Existing stage92 unsigned metadata JSON')
    parser.add_argument('--episodes', required=True, help='Owner-authored episode JSON')
    parser.add_argument('--output-dir', required=True, help='Existing private parent directory')
    args=parser.parse_args(argv)
    try:
        result=export_from_metadata_file(args.metadata,load_user_episodes(args.episodes),args.output_dir)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Local upload draft export rejected: {type(exc).__name__}\n')
    print(json.dumps({'folder': 'upload_drafts', 'episodes': result.episode_count,
                      'files': result.files_created, 'manifest_sha256': result.manifest_sha256,
                      'publication_approved': False, 'published': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
