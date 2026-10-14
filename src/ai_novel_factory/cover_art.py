"""Stage 91, ANF-REQ-062: offline, asset-free procedural cover and thumbnail.

Never ingests reference-book covers or images. Output is a local *draft* requiring
human originality/trademark/licensing review; no publication or upload occurs.
Pillow (optional ``graphics`` extra) is required only when rendering.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import math
import os
from pathlib import Path
import random
import re
from typing import Final


class CoverArtError(ValueError):
    """Input, font, or output failure; never silently return incomplete art."""


COVER_SIZE: Final = (1600, 2560)
THUMBNAIL_SIZE: Final = (400, 640)
PALETTES: Final = {
    'nocturne': ((9, 19, 45), (28, 70, 92), (244, 194, 121)),
    'ember': ((33, 14, 36), (113, 38, 59), (252, 177, 110)),
    'verdant': ((6, 39, 40), (29, 91, 66), (232, 213, 150)),
}
STYLES: Final = frozenset(('orbital', 'horizon', 'spire'))


@dataclass(frozen=True, slots=True)
class CoverSpec:
    title: str
    author: str
    genre: str = 'NOVEL'
    palette: str = 'nocturne'
    style: str = 'orbital'
    variation: str = ''


@dataclass(frozen=True, slots=True)
class CoverOutput:
    cover_path: Path
    thumbnail_path: Path
    cover_sha256: str
    thumbnail_sha256: str
    cover_size: tuple[int, int] = COVER_SIZE
    thumbnail_size: tuple[int, int] = THUMBNAIL_SIZE
    published: bool = False
    originality_reviewed: bool = False


def _text(value: str, name: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise CoverArtError(f'{name} must be text')
    value = value.strip()
    if required and not value:
        raise CoverArtError(f'{name} is required')
    if len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise CoverArtError(f'invalid {name} length or control characters')
    # Dangerous BiDi overrides/invisible formatting can make visible text differ from metadata.
    if any('\u202a' <= c <= '\u202e' or '\u2066' <= c <= '\u2069' for c in value):
        raise CoverArtError(f'invalid {name} direction controls')
    return value


def _validate(spec: CoverSpec) -> CoverSpec:
    if not isinstance(spec, CoverSpec):
        raise CoverArtError('a CoverSpec is required')
    if spec.palette not in PALETTES or spec.style not in STYLES:
        raise CoverArtError('unknown palette or artwork style')
    return CoverSpec(_text(spec.title, 'title', 90),
                     _text(spec.author, 'author', 70),
                     _text(spec.genre, 'genre', 50),
                     spec.palette, spec.style,
                     _text(spec.variation, 'variation', 80, required=False))


def _find_font(font_path: str | Path | None) -> Path:
    if font_path is not None:
        path = Path(font_path)
        if not path.is_file():
            raise CoverArtError('specified font is unavailable')
        return path
    # Font files are OS/user-provided; never downloaded or bundled into the ZIP.
    options = (
        'C:/Windows/Fonts/malgun.ttf', 'C:/Windows/Fonts/malgunbd.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/AppleSDGothicNeo.ttc',
    )
    for item in options:
        if Path(item).is_file():
            return Path(item)
    raise CoverArtError('no suitable system font found; provide a Korean-capable font_path')


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(c * (1 - t) + d * t) for c, d in zip(a, b))


def _layout_title(draw, title: str, font_file: Path, *, max_width: int = 1310):
    from PIL import ImageFont

    # All lines are measured with the actual chosen typeface, including Hangul.
    for size in range(152, 43, -4):
        font = ImageFont.truetype(str(font_file), size)
        result: list[str] = []
        line = ''
        for word in re.findall(r'\S+\s*', title):
            chunk = word.strip()
            candidate = f'{line} {chunk}'.strip() if line else chunk
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                line = candidate
                continue
            if line:
                result.append(line)
                line = ''
            # Very long unspaced words are broken by rendered character width.
            for char in chunk:
                candidate = line + char
                if line and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                    result.append(line)
                    line = char
                else:
                    line = candidate
        if line:
            result.append(line)
        if len(result) <= 4 and len(result) * (size + 23) <= 580:
            return font, result, size + 23
    raise CoverArtError('title cannot fit on cover')


def render_cover(spec: CoverSpec, *, font_path: str | Path | None = None) -> bytes:
    """Return original procedural JPEG bytes; no disk/network side effects."""
    spec = _validate(spec)
    font_file = _find_font(font_path)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise CoverArtError('Pillow is required: install the optional graphics extra offline') from exc

    seed = int.from_bytes(hashlib.sha256(('ANF91\0' + '\0'.join((
        spec.title, spec.author, spec.genre, spec.palette, spec.style, spec.variation
    ))).encode('utf-8')).digest()[:16], 'big')
    rng = random.Random(seed)
    dark, medium, accent = PALETTES[spec.palette]
    img = Image.new('RGB', COVER_SIZE, dark)
    draw = ImageDraw.Draw(img)
    for y in range(COVER_SIZE[1]):
        fraction = y / (COVER_SIZE[1] - 1)
        draw.line((0, y, 1599, y), fill=_blend(dark, medium, (0.43 * fraction + 0.11)))
    # Abstract, mathematically generated art; absolutely no reference-cover pixels.
    center_x, center_y = 800, 1000
    if spec.style == 'orbital':
        center_x += rng.randrange(-110, 111)
        center_y += rng.randrange(-140, 140)
        for radius in (710, 566, 400, 254):
            color = _blend(medium, accent, 0.23 + (710-radius)/900)
            draw.ellipse((center_x-radius, center_y-radius, center_x+radius,
                          center_y+radius), outline=color, width=3 + radius//200)
        for i in range(14):
            a = 2 * math.pi * (i / 14 + rng.random() * .04)
            radius = rng.randint(180, 660)
            x = center_x + int(math.cos(a) * radius)
            y = center_y + int(math.sin(a) * radius)
            r = rng.randint(4, 12)
            draw.ellipse((x-r, y-r, x+r, y+r), fill=accent)
    elif spec.style == 'horizon':
        for layer in range(11):
            base_y = 450 + layer * 133 + rng.randint(-45, 45)
            coordinates = [(0, base_y)]
            for x in range(0, 1601, 80):
                y = base_y + int(95 * math.sin(x / 165 + layer*.8) + rng.randrange(-12, 13))
                coordinates.append((x, y))
            coordinates.append((1600, base_y))
            draw.line(coordinates, fill=_blend(medium, accent, layer / 19), width=7)
        draw.ellipse((580, 470, 1040, 930), outline=accent, width=9)
    else:  # spire: overlapping prisms, varied via deterministic random
        for layer in range(9):
            x = 140 + layer * 170 + rng.randint(-45, 45)
            peak = rng.randint(300, 980)
            foot = rng.randint(1400, 1770)
            color = _blend(medium, accent, layer / 14)
            draw.polygon([(x, foot), (x + 40, peak), (x + 260, foot)], outline=color, width=8)
            draw.line((x+40, peak, x+110, foot), fill=color, width=4)

    for i in range(125):
        x, y = rng.randrange(60, 1540), rng.randrange(100, 1750)
        r = rng.choice((1, 1, 2, 2, 3))
        draw.ellipse((x-r, y-r, x+r, y+r), fill=_blend(medium, accent, .35 + rng.random()*.65))

    # Text panel with continuous dark fill protects legibility at thumbnail size.
    panel = _blend(dark, (0, 0, 0), .24)
    draw.rectangle((0, 1790, 1600, 2560), fill=panel)
    draw.line((140, 1825, 1460, 1825), fill=accent, width=5)
    label_font = ImageFont.truetype(str(font_file), 43)
    author_font = ImageFont.truetype(str(font_file), 61)
    label = spec.genre.upper()
    # Very long genre is shrunk to fit.
    while draw.textbbox((0, 0), label, font=label_font)[2] > 1280:
        label_font = ImageFont.truetype(str(font_file), max(18, label_font.size-2))
        if label_font.size == 18:
            raise CoverArtError('genre cannot fit on cover')
    draw.text((800, 1875), label, fill=accent, font=label_font, anchor='mt')
    title_font, lines, leading = _layout_title(draw, spec.title, font_file)
    start_y = 2010 + max(0, (570 - len(lines)*leading)//2) // 2
    for line in lines:
        draw.text((800, start_y), line, fill=(250, 245, 232), font=title_font, anchor='mt',
                  stroke_width=1, stroke_fill=panel)
        start_y += leading
    author_font_size = author_font.size
    while draw.textbbox((0, 0), spec.author, font=author_font)[2] > 1250:
        author_font_size -= 2
        if author_font_size < 24:
            raise CoverArtError('author cannot fit on cover')
        author_font = ImageFont.truetype(str(font_file), author_font_size)
    draw.text((800, 2440), spec.author, fill=accent, font=author_font, anchor='mm')

    out = BytesIO()
    img.save(out, format='JPEG', quality=91, optimize=True, subsampling=0)
    return out.getvalue()


def _thumbnail(cover: bytes) -> bytes:
    from PIL import Image
    with Image.open(BytesIO(cover)) as src:
        image = src.convert('RGB').resize(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
    result = BytesIO()
    image.save(result, format='JPEG', quality=89, optimize=True, subsampling=0)
    return result.getvalue()


def save_cover_pair(spec: CoverSpec, directory: str | Path, *,
                    font_path: str | Path | None = None) -> CoverOutput:
    """Write both JPGs to an existing local directory, never replacing originals.

    Renders everything in memory first, reserves final paths with O_EXCL, and
    rolls back self-created files on any write error. No publish/approval calls.
    """
    target = Path(directory)
    if target.is_symlink() or not target.is_dir():
        raise CoverArtError('choose an existing non-symlink local output directory')
    cover_path = target / 'cover.jpg'
    thumb_path = target / 'thumbnail.jpg'
    if cover_path.is_symlink() or thumb_path.is_symlink() or any(
        p.exists() for p in (cover_path, thumb_path)
    ):
        raise CoverArtError('cover.jpg or thumbnail.jpg exists; never overwrite existing artwork')
    cover = render_cover(spec, font_path=font_path)
    thumb = _thumbnail(cover)
    created: list[Path] = []
    try:
        for path, content in ((cover_path, cover), (thumb_path, thumb)):
            # File creation is exclusive to prevent lost artwork under concurrent runs.
            with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as f:
                created.append(path)
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
    except OSError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        raise CoverArtError('artwork could not be safely saved; new files rolled back') from exc
    return CoverOutput(cover_path, thumb_path,
                       hashlib.sha256(cover).hexdigest(),
                       hashlib.sha256(thumb).hexdigest())
