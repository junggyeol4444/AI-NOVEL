"""Stage 92 local CLI. User-owned UTF-8 JSON input; no network or publication."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .publication_metadata import MetadataError, draft_from_original_premise, save_metadata


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Create an offline *unapproved* metadata draft')
    ap.add_argument('--input', required=True, help='user-authored UTF-8 JSON spec')
    ap.add_argument('--directory', required=True, help='existing output directory')
    args = ap.parse_args(argv)
    try:
        spec = Path(args.input)
        if spec.is_symlink() or not spec.is_file() or spec.stat().st_size > 16384:
            raise MetadataError('invalid local input')
        content = json.loads(spec.read_text(encoding='utf-8'))
        if not isinstance(content, dict) or set(content) != {'project_id', 'title', 'author',
                    'original_logline', 'category', 'keywords', 'price_amount',
                    'currency', 'language'}:
            raise MetadataError('input fields must match the documented schema')
        if not isinstance(content['keywords'], list):
            raise MetadataError('keywords must be a list')
        content['keywords'] = tuple(content['keywords'])
        draft = draft_from_original_premise(**content)
        result = save_metadata(draft, args.directory)
        # Only result filename and checksum. Never print original user prose.
        print(json.dumps({'filename': result.path.name, 'sha256': result.sha256,
                          'status': draft.status, 'published': False}))
        return 0
    except (MetadataError, OSError, UnicodeError, ValueError, TypeError) as exc:
        print(f'metadata draft refused: {type(exc).__name__}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
