from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import frappe

from ceto.routing.exceptions import RouteNotFoundError

if TYPE_CHECKING:
	from frappe.model.document import Document


class CartAccess:
	"""Resolve explicit cart IDs without leaking claimed carts."""

	def get(self, cart_id: str) -> tuple["Document", "Document"]:
		reference = self._get_reference(cart_id)
		self._check_owner(reference)
		quotation = self._get_open_quotation(reference.quotation)
		return reference, quotation

	@contextmanager
	def lock(self, cart_id: str) -> Iterator[tuple["Document", "Document"]]:
		reference = self._get_reference(cart_id)
		self._lock_rows(cart_id, reference.quotation)
		reference.reload()
		self._check_owner(reference)
		yield reference, self._get_open_quotation(reference.quotation)

	@contextmanager
	def lock_for_completion(self, cart_id: str) -> Iterator[tuple["Document", "Document"]]:
		"""Row-lock a cart for completion, tolerating an already-completed one.

		Same lock discipline and order as :meth:`lock`, but a *submitted*
		Quotation is yielded instead of rejected: completion itself submits
		the Quotation, and the replay path must still resolve the order an
		earlier completion booked. Anything that cannot complete — unknown
		cart, missing or cancelled Quotation, a draft that is not a Shopping
		Cart — is masked as ``404 not_found``; a draft cart yields normally
		so the preflight can refuse it.
		"""
		reference = self._get_reference(cart_id)
		self._lock_rows(cart_id, reference.quotation)
		reference.reload()
		self._check_owner(reference)
		yield reference, self._get_completion_quotation(reference.quotation)

	@staticmethod
	def _lock_rows(cart_id: str, quotation_name: str) -> None:
		CartAccess._lock_row("Ceto Cart Reference", cart_id)
		CartAccess._lock_row("Quotation", quotation_name)

	@staticmethod
	def _get_completion_quotation(name: str) -> "Document":
		try:
			quotation = frappe.get_doc("Quotation", name)
		except frappe.DoesNotExistError:
			raise RouteNotFoundError("Cart not found")
		if quotation.docstatus == 2:
			# A cancelled cart never completes and has no order to replay.
			raise RouteNotFoundError("Cart not found")
		if quotation.docstatus == 0 and quotation.order_type != "Shopping Cart":
			# Only Shopping Cart Quotations are carts; a submitted (completed)
			# Quotation skips this check — the replay branch owns it.
			raise RouteNotFoundError("Cart not found")
		return quotation

	@staticmethod
	def _lock_row(doctype: str, name: str) -> None:
		table = frappe.qb.DocType(doctype)
		frappe.qb.from_(table).select(table.name).where(table.name == name).for_update().run()

	@staticmethod
	def owner_user() -> str | None:
		user = getattr(frappe.session, "user", None)
		return None if user in (None, "", "Guest") else user

	@staticmethod
	def _get_reference(cart_id: str) -> "Document":
		try:
			return frappe.get_doc("Ceto Cart Reference", cart_id)
		except frappe.DoesNotExistError:
			raise RouteNotFoundError("Cart not found")

	@staticmethod
	def _get_open_quotation(name: str) -> "Document":
		try:
			quotation = frappe.get_doc("Quotation", name)
		except frappe.DoesNotExistError:
			raise RouteNotFoundError("Cart not found")
		if quotation.docstatus != 0 or quotation.order_type != "Shopping Cart":
			raise RouteNotFoundError("Cart not found")
		return quotation

	@classmethod
	def _check_owner(cls, reference: "Document") -> None:
		if reference.owner_user and reference.owner_user != cls.owner_user():
			raise RouteNotFoundError("Cart not found")
