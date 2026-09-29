"""Promotion domain service for Ceto carts.

Maps Medusa promotion codes onto ERPNext's native coupon model: a
``Coupon Code`` record linked to a ``Pricing Rule``, applied to the cart's
Quotation through the Quotation's single ``coupon_code`` link. ERPNext's
document model natively supports exactly one coupon per transaction, so that
is the honest capacity exposed here: applying or holding two distinct codes
at once is rejected instead of being silently dropped.

All discount values are produced by ERPNext pricing rules when the Quotation
is saved through its controllers; this module never computes a discount.
"""

from typing import TYPE_CHECKING

import frappe
from erpnext.accounts.doctype.pricing_rule.utils import validate_coupon_code

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.line_items import CartLineItems

if TYPE_CHECKING:
	from frappe.model.document import Document

UNKNOWN_CODE = "Unknown promotion code"
MULTIPLE_CODES = "Only one promotion code can be applied to a cart at a time"
CODE_NOT_APPLIED = "Promotion code is not applied to the cart"


class CartPromotions:
	"""Coupon-code operations on the Quotation backing a cart."""

	@classmethod
	def apply(cls, quotation: "Document", codes: list[str]) -> None:
		"""Validate and set the cart's single coupon code.

		Called with the request's ``promo_codes`` list. Duplicates of the same
		code are collapsed; more than one distinct code is rejected because the
		Quotation carries exactly one ``coupon_code`` link.
		"""
		distinct = cls._distinct(codes)
		if len(distinct) > 1:
			raise InvalidDataError(MULTIPLE_CODES)
		current = quotation.get("coupon_code")
		if current and cls._code_of(current) != distinct[0]:
			raise InvalidDataError(MULTIPLE_CODES)
		coupon = cls._resolve(distinct[0])
		cls._validate(coupon)
		# The Quotation field is a Link, so it stores the Coupon Code document
		# name; ERPNext's own pricing-rule pipeline (run on save/validate via
		# set_missing_values with coupon_code in args) applies the discount.
		quotation.coupon_code = coupon.name
		CartLineItems.save(quotation)

	@classmethod
	def remove(cls, quotation: "Document", codes: list[str]) -> None:
		"""Remove the applied coupon code if it matches the request."""
		distinct = cls._distinct(codes)
		if len(distinct) > 1:
			raise InvalidDataError(MULTIPLE_CODES)
		current = quotation.get("coupon_code")
		if not current:
			return
		if distinct[0] != cls._code_of(current):
			raise InvalidDataError(CODE_NOT_APPLIED)
		cls.clear(quotation)
		CartLineItems.save(quotation)

	@classmethod
	def set_promo_codes(cls, quotation: "Document", codes: list[str]) -> None:
		"""Replace the cart's promo codes (Medusa update semantics).

		Accepts an empty list (clears the coupon), a single code (idempotent
		if already applied, otherwise replaces the current one), and rejects
		more than one distinct code like :meth:`apply`. Only mutates the
		Quotation in memory; the caller persists through the controllers.
		"""
		distinct = cls._distinct(codes)
		if len(distinct) > 1:
			raise InvalidDataError(MULTIPLE_CODES)
		if not distinct:
			cls.clear(quotation)
			return
		current = quotation.get("coupon_code")
		if current and cls._code_of(current) == distinct[0]:
			return
		coupon = cls._resolve(distinct[0])
		cls._validate(coupon)
		cls.clear(quotation)
		quotation.coupon_code = coupon.name

	@staticmethod
	def clear(quotation: "Document") -> None:
		"""Drop the coupon link and the document-level additional discount.

		ERPNext resets the coupon discount itself whenever its pricing-rule
		pass sees an empty ``coupon_code``, but only while the rule still
		matches; zeroing the fields here guarantees a removed coupon can never
		leave a lingering discount. Item-level values are recomputed by
		ERPNext on save.
		"""
		quotation.coupon_code = None
		quotation.discount_amount = 0
		quotation.base_discount_amount = 0
		quotation.additional_discount_percentage = 0

	@staticmethod
	def _distinct(codes: list[str]) -> list[str]:
		"""Collapse exact duplicates while keeping the request's order."""
		return list(dict.fromkeys(codes))

	@staticmethod
	def _resolve(code: str) -> "Document":
		"""Resolve a public code string to its Coupon Code document."""
		name = frappe.db.get_value("Coupon Code", {"coupon_code": code}, "name")
		if not name:
			raise InvalidDataError(UNKNOWN_CODE)
		return frappe.get_cached_doc("Coupon Code", name)

	@classmethod
	def _validate(cls, coupon: "Document") -> None:
		"""Run ERPNext's own coupon validity checks, mapped to 400 responses."""
		try:
			validate_coupon_code(coupon.name)
		except frappe.ValidationError as exc:
			raise InvalidDataError(str(exc) or "Invalid promotion code") from exc

	@staticmethod
	def _code_of(coupon_name: str) -> str:
		"""Return the public code string of the linked Coupon Code document."""
		return frappe.db.get_value("Coupon Code", coupon_name, "coupon_code") or coupon_name
