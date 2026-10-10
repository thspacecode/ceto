import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

_TYPE_ID_PATTERN = re.compile(r"ptyp_[0-9a-f]{32}")


class CetoProductType(Document):
	"""A Ceto-stored curated product type.

	ERPNext has no product-type master, so Ceto curates the types itself
	(``docs/catalog/field-mapping.md``, Recorded Decision 3): the record is
	named by its public ``type_id`` (``ptyp_`` + 32 lowercase hex, the minted
	shape of ``ceto.services.catalog`` id helpers) and carries the curated
	``value`` — the served label and the record's stable business key. The
	value is unique (whitespace-stripped, otherwise verbatim: a curated label
	is presentation, not an address, so its case is never folded) and a
	duplicate fails closed at insert — the schema's unique index is
	case-insensitive, so two stored labels can never differ only by case.
	The optional ``external_id`` records an
	external system's identifier verbatim; Ceto never resolves a type by it.
	The optional ``metadata`` is an arbitrary JSON object, stored
	canonicalized (sorted keys, compact separators) so equal payloads are
	byte-identical on disk and the served projection is reproducible.

	The record is Store-read-only: the Store surface projects it through
	``ceto.services.catalog.product_types``, and writes belong to the
	operators and the bootstrap fixtures. There is no soft-delete column and
	no product back-reference: how a published ``Item`` references its type
	is a products-slice decision (Recorded Decision 3), and Ceto deletes
	types hard.
	"""

	def validate(self) -> None:
		self._validate_type_id()
		self._validate_value()
		self._validate_external_id()
		self._validate_metadata()

	def _validate_type_id(self) -> None:
		"""Pin the public id to its minted shape; an id is never normalized."""
		if not _TYPE_ID_PATTERN.fullmatch(self.type_id or ""):
			frappe.throw(_("Type ID must be 'ptyp_' followed by 32 lowercase hex characters"))

	def _validate_value(self) -> None:
		self.value = (self.value or "").strip()
		if not self.value:
			frappe.throw(_("Value is required"))

	def _validate_external_id(self) -> None:
		self.external_id = (self.external_id or "").strip() or None

	def _validate_metadata(self) -> None:
		"""Store metadata as a canonical JSON object; refuse anything else."""
		self.metadata = _canonical_metadata(self.metadata)


def _canonical_metadata(value: object) -> str | None:
	if isinstance(value, str):
		value = value.strip() or None
	if value is None:
		return None
	if isinstance(value, str):
		try:
			parsed = json.loads(value)
		except ValueError:
			frappe.throw(_("Metadata must be a JSON object"))
	else:
		parsed = value
	if not isinstance(parsed, dict):
		frappe.throw(_("Metadata must be a JSON object"))
	return json.dumps(parsed, separators=(",", ":"), sort_keys=True)
