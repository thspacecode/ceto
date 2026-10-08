"""Shared service helpers used by more than one Ceto domain.

Two concerns recur across domains: the trusted persistence steps behind a
store request need the temporary Administrator elevation of
:func:`privileged_scope`, and the public reference records (carts, lines,
customers) store their Medusa ``metadata`` through the same JSON round-trip
(:func:`dump_metadata`, :func:`merged_metadata`).
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import frappe


def dump_metadata(metadata: dict[str, Any] | None) -> str | None:
	"""Serialize metadata for storage on a reference record."""
	return json.dumps(metadata, separators=(",", ":"), sort_keys=True) if metadata else None


def merged_metadata(current: str | None, update: dict[str, Any] | None) -> str | None:
	"""Merge reference metadata: null values remove keys, ``None`` clears all."""
	if update is None:
		return None
	metadata = json.loads(current) if current else {}
	for key, value in update.items():
		if value is None:
			metadata.pop(key, None)
		else:
			metadata[key] = value
	return dump_metadata(metadata)


@contextmanager
def privileged_scope() -> Iterator[None]:
	"""Run trusted ERPNext controller work as a temporary Administrator.

	The flag alone cannot do this: ERPNext's ``account_perm_check`` resolves
	through ``frappe.has_permission``, which grants only the Administrator
	session user and ignores ``frappe.flags.ignore_permissions``. Both the
	user and the flag are captured and exactly restored in ``finally``, so
	scopes nest safely and leave no elevation behind. Authorization and
	ownership checks must run outside this scope; only trusted persistence
	work belongs inside it.
	"""
	previous_user = frappe.session.user
	previous_flag = frappe.flags.ignore_permissions
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser
	frappe.flags.ignore_permissions = True
	try:
		yield
	finally:
		frappe.flags.ignore_permissions = previous_flag
		frappe.set_user(previous_user)  # nosemgrep: frappe-setuser
