"""Stage 11: in-memory reference-novel file selection (no file I/O).

This module intentionally does NOT validate file contents, read, hash, copy,
parse, upload, persist, or log user-selected files. Those are later stages.
"""
from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from collections.abc import Iterable

SUPPORTED_REFERENCE_SUFFIXES: tuple[str, ...] = (
    ".txt", ".md", ".markdown", ".epub", ".docx", ".pdf"
)
REFERENCE_FILE_FILTER = (
    "참고소설 (*.txt *.md *.markdown *.epub *.docx *.pdf)"
)


def display_filename(path: str) -> str:
    """Show only a filename, never the containing directory in the UI."""
    return PureWindowsPath(path).name if "\\" in path else PurePosixPath(path).name


class ReferenceFileSelection:
    """Temporary selection only; file existence/format checks belong to stage 12."""

    def __init__(self) -> None:
        self._paths: tuple[str, ...] = ()

    @property
    def selected_paths(self) -> tuple[str, ...]:
        return self._paths

    @property
    def display_names(self) -> tuple[str, ...]:
        return tuple(display_filename(path) for path in self._paths)

    def add_paths(self, paths: Iterable[str]) -> None:
        """Append unique paths in selection order without touching the filesystem."""
        seen = set(self._paths)
        selected = list(self._paths)
        for path in paths:
            if not isinstance(path, str) or not path.strip() or path in seen:
                continue
            seen.add(path)
            selected.append(path)
        self._paths = tuple(selected)

    def clear(self) -> None:
        self._paths = ()
