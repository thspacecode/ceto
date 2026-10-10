import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

_COLLECTION_ID_PATTERN = re.compile(r"pcol_[0-9a-f]{32}")
_HANDLE_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class CetoCollection(Document):
	"""A Ceto-stored storefront collection.

	Collections have no ERPNext master, so Ceto owns the storage
	(``docs/catalog/field-mapping.md``, Recorded Decision 2): the record is
	named by its public ``collection_id`` (``pcol_`` + 32 lowercase hex, the
	minted shape of ``ceto.services.catalog`` id helpers), carries the served
	``title``, and stores the ``handle`` that is the collection's stable
	public URL segment. The handle is unique as well as normalized —
	whitespace stripped, case folded to lowercase before the slug shape is
	enforced — so presentation variants land on one addressable record and a
	duplicate fails closed at insert. The optional ``external_id`` records an
	external system's identifier verbatim; Ceto never resolves a collection
	by it. The optional ``metadata`` is an arbitrary JSON object, stored
	canonicalized (sorted keys, compact separators) so equal payloads are
	byte-identical on disk and the served projection is reproducible.

	The record is Store-read-only: the Store surface projects it through
	``ceto.services.catalog.collections``, and writes belong to the operators
	and the bootstrap fixtures. There is deliberately no membership column —
	collection-item membership is deferred with the products slice (Recorded
	Decision 4) — and no soft-delete column: Ceto deletes collections hard.
	"""

	def validate(self) -> None:
		self._validate_collection_id()
		self._validate_title()
		self._validate_handle()
		self._validate_external_id()
		self._validate_metadata()

	def _validate_collection_id(self) -> None:
		"""Pin the public id to its minted shape; an id is never normalized."""
		if not _COLLECTION_ID_PATTERN.fullmatch(self.collection_id or ""):
			frappe.throw(_("Collection ID must be 'pcol_' followed by 32 lowercase hex characters"))

	def _validate_title(self) -> None:
		self.title = (self.title or "").strip()
		if not self.title:
			frappe.throw(_("Title is required"))

	def _validate_handle(self) -> None:
		"""Normalize the handle, then pin it to the lowercase slug shape.

		The handle is the stable public URL segment, so it is validated
		strictly after normalization: a padded or mixed-case presentation is
		folded to its stored value, and anything that is not a nonempty
		lowercase slug of letters, digits and single inner hyphens is refused
		outright instead of being silently rewritten into a different
		address.
		"""
		self.handle = (self.handle or "").strip().lower()
		if not _HANDLE_PATTERN.fullmatch(self.handle or ""):
			frappe.throw(_("Handle must be a lowercase slug of letters, digits and hyphens"))

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
