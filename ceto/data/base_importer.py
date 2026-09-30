"""Reusable reporting foundation for explicit initial-data importers.

Importers locate records by stable business keys, write only the fields they
own, and report every outcome as ``created``, ``updated``, or ``skipped``.
Library classes never commit; the caller owns transaction control.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal, TypedDict

import frappe
from frappe.model.document import Document

from ceto.data.exceptions import AmbiguousIdentityError

ChangeType = Literal["created", "updated", "skipped"]


class Report(TypedDict):
	"""Outcome of an importer run, grouped by doctype and change type."""

	created: dict[str, list[str]]
	updated: dict[str, list[str]]
	skipped: dict[str, list[str]]
	notes: list[str]


def values_differ(current: Any, expected: Any) -> bool:
	"""Compare a stored field value against the configured expectation."""
	if isinstance(expected, Decimal):
		return Decimal(str(current or 0)) != expected
	if isinstance(expected, bool):
		return bool(current) != expected
	if expected is None:
		# A null expectation converges with an unset field: the database may
		# store NULL or an empty string for the same logical "not set" state,
		# and rewriting either on every run would break skip-on-rerun.
		return current is not None and current != ""
	if current is None:
		current = ""
	return current != expected


def apply_values(target: Any, fields: Mapping[str, Any]) -> bool:
	"""Set only the fields that differ on a document or child row; return whether it changed."""
	changed = False
	for fieldname, expected in fields.items():
		if values_differ(target.get(fieldname), expected):
			target.set(fieldname, expected)
			changed = True
	return changed


class BaseImporter:
	"""Shared created/updated/skipped bookkeeping for bootstrap seeders."""

	def __init__(self) -> None:
		self.report: Report = {
			"created": {},
			"updated": {},
			"skipped": {},
			"notes": [],
		}

	def make(self) -> Report:
		raise NotImplementedError

	def record_change(self, change_type: ChangeType, doctype: str, name: str) -> None:
		"""Record one document outcome under its doctype."""
		self.report[change_type].setdefault(doctype, []).append(name)

	def record_note(self, note: str) -> None:
		"""Record context that does not fit the created/updated/skipped report."""
		self.report["notes"].append(note)

	def merge_report(self, report: Report) -> Report:
		"""Merge a nested importer report into this one."""
		for change_type in ("created", "updated", "skipped"):
			for doctype, names in report[change_type].items():
				self.report[change_type].setdefault(doctype, []).extend(names)
		self.report["notes"].extend(report["notes"])
		return self.report

	def resolve_unique_name(self, doctype: str, filters: Mapping, label: str) -> str | None:
		"""Resolve a business key to the single record it identifies.

		Returns ``None`` when nothing matches. Raises ``AmbiguousIdentityError``
		when the key unexpectedly resolves to more than one record.
		"""
		names = frappe.get_all(doctype, filters=filters, pluck="name")
		if len(names) > 1:
			msg = f"{label} matched {len(names)} {doctype} records: {', '.join(sorted(names))}"
			raise AmbiguousIdentityError(msg)
		return names[0] if names else None

	def apply_owned_fields(self, doc: Document, owned_fields: Mapping[str, Any]) -> bool:
		"""Set only the seeder-owned fields that differ; return whether the doc changed."""
		return apply_values(doc, owned_fields)

	def create_and_record(
		self, doc: Document, owned_fields: Mapping[str, Any], doctype: str, name: str
	) -> None:
		"""Insert a new document with the owned fields and report it as created."""
		doc.update(owned_fields)
		doc.insert()
		self.record_change("created", doctype, name)

	def update_and_record(
		self, doc: Document, owned_fields: Mapping[str, Any], doctype: str, name: str
	) -> None:
		"""Apply owned fields to an existing document; report updated or skipped."""
		if self.apply_owned_fields(doc, owned_fields):
			doc.save()
			self.record_change("updated", doctype, name)
		else:
			self.record_change("skipped", doctype, name)
