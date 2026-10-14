import frappe
from frappe import _
from frappe.model.document import Document


class CetoProductMerchandising(Document):
	"""The Ceto-owned storefront merchandising assignment of one ERPNext Item.

	No ERPNext master links an ``Item`` to a ``Ceto Collection`` or a
	``Ceto Product Type`` (products field-mapping Recorded Decision 4), so
	Ceto owns the link as one cohesive record: named by the exact Item code
	— one record per Item, the uniqueness the served singular
	``collection_id`` / ``type_id`` semantics need — it carries the
	collection the storefront merchandising groups the product into and the
	curated product type. Both links are optional, but a record without
	either is refused: an empty assignment stores nothing. The references
	are validated Links, never core ERPNext custom fields; whether the
	assigned Item is published stays a read-time decision of
	``ceto.services.catalog.publication``.

	The record is Store-read-only until the products behavior slice; writes
	belong to the operators and the bootstrap fixtures. Deleting a
	collection or a product type is handled by the masters' ``on_trash``:
	every naming record is detached and a record left without any link is
	deleted outright, so the storage never carries dangling references.
	Deleting the Item itself stays blocked while its record exists — the
	assignment is a stable reference that must be lifted explicitly.
	"""

	def validate(self) -> None:
		if not self.collection and not self.product_type:
			frappe.throw(_("Assign a collection or a product type"))
