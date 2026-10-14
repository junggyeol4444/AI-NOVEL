"""Local metadata storage for AI Novel Factory (no manuscript content)."""

from .reference_catalog import (
    CatalogError,
    ReferenceCatalog,
    ReferenceRecord,
)

__all__ = ["CatalogError", "ReferenceCatalog", "ReferenceRecord"]

# Stage 32 - explicitly assigned, offline genre tags and statistics selections.
from .genre_patterns import GenrePatternStore, GenreStorageError, SavedGenreSelection
__all__.extend(["GenrePatternStore", "GenreStorageError", "SavedGenreSelection"])

# Stage 34: per-reference integer pattern strengths in local SQLite.
from .pattern_strengths import (
    DEFAULT_STRENGTH, MAX_STRENGTH, PatternStrengthStorageError,
    PatternStrengthStore, StrengthSetting,
)
__all__.extend([
    "DEFAULT_STRENGTH", "MAX_STRENGTH", "PatternStrengthStorageError",
    "PatternStrengthStore", "StrengthSetting",
])

# Stage 35: SQLite recipes for safe user-selected statistical features.
from .element_selections import (
    ElementSelectionStore, ElementSelectionStorageError, SavedElementSelection,
)
__all__.extend(["ElementSelectionStore", "ElementSelectionStorageError", "SavedElementSelection"])
