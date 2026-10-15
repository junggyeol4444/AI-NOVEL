"""Offline Korean UI font fallback for the packaged Windows executable.

Fonts are local application assets with bundled SIL OFL licensing, not network
resources. Neither GUI startup nor testing performs any font download.
"""
from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtGui import QFont, QFontDatabase, QRawFont
from PySide6.QtWidgets import QApplication

_FONT_ID = -1
_FONT_FAMILY = ''


def bundled_font_path() -> Path:
    base = Path(getattr(sys, '_MEIPASS', '') or
                Path(__file__).resolve().parents[3])
    return base / 'assets' / 'NotoSansKR.ttf'


def apply_korean_ui_font() -> bool:
    """Prefer packaged CJK font over host OS code-page/locale-dependent fallback."""
    global _FONT_ID, _FONT_FAMILY
    app = QApplication.instance()
    if app is None:
        return False
    fontfile = bundled_font_path()
    if fontfile.is_file():
        if _FONT_ID < 0:
            font_id = QFontDatabase.addApplicationFont(str(fontfile))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    _FONT_ID, _FONT_FAMILY = font_id, families[0]
        if _FONT_FAMILY:
            font = QFont(_FONT_FAMILY, 10)
            app.setFont(font)
    return korean_glyphs_renderable()


def korean_glyphs_renderable() -> bool:
    """Use actual loaded font glyph coverage, not the Qt label's raw Unicode."""
    app = QApplication.instance()
    if app is None:
        return False
    raw_font = QRawFont.fromFont(app.font())
    return raw_font.isValid() and all(
        raw_font.supportsCharacter(ord(letter)) for letter in '한글작품설정'
    )
