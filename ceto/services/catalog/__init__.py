"""Catalog domain services over Ceto-owned catalog storage.

Collections and product types have no ERPNext master — Ceto owns their
storage DocTypes (``docs/catalog/field-mapping.md``, Recorded Decisions 2
and 3) — and every projection here is the read-only Store view of those
records. Writes belong to the operators and the bootstrap fixtures; the
Store surface never mutates the catalog.
"""

from ceto.services.catalog.collections import CollectionDirectory, new_collection_id
from ceto.services.catalog.product_types import ProductTypeDirectory, new_product_type_id

__all__ = [
	"CollectionDirectory",
	"ProductTypeDirectory",
	"new_collection_id",
	"new_product_type_id",
]
