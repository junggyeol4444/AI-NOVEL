"""CI-only fetch of the SIL OFL 1.1 Noto Sans KR CJK UI fallback font.

The GUI is fully offline. Only disposable Windows build jobs fetch this
public upstream font at a pinned Git tree and verify its exact Git blob ID.
No user manuscripts, private data, or credentials used.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen, Request

FONTS_COMMIT = '67bc647ce1910e92f461bcc82aae30f21d21a9cc'
FILES = {
    'NotoSansKR.ttf': (
        'NotoSansKR%5Bwght%5D.ttf',
        'b386890ba945e1f39448a6b59f20c5d194f58808',
        10_414_588),
    'OFL.txt': (
        'OFL.txt',
        '1c9f43281b8f216c5461fe9ac729afbade7724e4',
        4388)
}


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') +
                        b'\x00' + data).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path,
                        default=Path('build/ci/gui_font'))
    args = parser.parse_args(argv)
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for name, (upstream, expected_sha, expected_size) in FILES.items():
        target = folder / name
        if target.is_file():
            raw = target.read_bytes()
        else:
            url = ('https://raw.githubusercontent.com/google/fonts/' +
                   FONTS_COMMIT + '/ofl/notosanskr/' + upstream)
            with urlopen(Request(url, headers={
                    'User-Agent': 'AI-Novel-Factory-validation'}), timeout=90) as response:
                raw = response.read(expected_size + 1)
        if len(raw) != expected_size or git_blob_sha1(raw) != expected_sha:
            raise RuntimeError('Pinned upstream Korean UI font integrity check failed')
        if not target.exists():
            with target.open('xb') as out:
                out.write(raw)
        print(name + ': Git blob SHA-1 verified; bytes=' + str(expected_size))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
