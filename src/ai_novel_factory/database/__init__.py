"""Local metadata storage for AI Novel Factory (no manuscript content)."""

from .reference_catalog import (
    CatalogError,
    ReferenceCatalog,
    ReferenceRecord,
)

__all__ = ["CatalogError", "ReferenceCatalog", "ReferenceRecord"]
