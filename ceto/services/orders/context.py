"""Bulk-loaded read-model context for one page of placed orders.

The list surface serves the same canonical ``StoreOrder`` JSON the
retrieval surface serves, but a page must not pay the retrieval path's
per-order reads: every lookup ``OrderSerializer`` makes per order — the
completed cart's reference, the Sales Order with its item and tax rows,
the line mappings, the addresses and their countries, the consumed credit
holds with their wallets and the applied shipping rule — is loaded once
for the whole page, so the query count stays constant as the page grows.

The documents are stitched from the bulk rows through the Frappe document
API (``frappe.get_all`` plus document construction, no raw SQL), child
tables ordered the way a document load orders them (``idx asc``), and the
context is handed to ``OrderSerializer.serialize``, which consults it
instead of its single-order reads. The serialized output is identical to
the retrieval path's; the only behavior the context does not cover is the
legacy-ownership fallback (``OrderOwnership``), which stays a per-row read
for the un-backfilled references the one-time patch is meant to erase.
"""

from typing import TYPE_CHECKING

import frappe

from ceto.services.carts.addresses import render_address
from ceto.services.carts.credits import AppliedCredit, CartCredits
from ceto.services.carts.shipping import RULE_FIELDS, AppliedShippingCharge, CartShipping

if TYPE_CHECKING:
	from frappe.model.document import Document

	from ceto.types.http.store.carts.entities import StoreCartAddress

#: The Sales Order child tables the order read model reads: the mapped
#: item rows, the tax rows (shipping charge + credit deductions) and the
#: item-wise tax allocation the line tax totals come from.
SALES_ORDER_TABLES = ("items", "taxes", "item_wise_tax_details")

LINE_REFERENCE_FIELDS = ["name", "line_id", "quotation_item", "metadata", "creation", "modified"]


class OrderPageContext:
	"""Bulk-loaded context for one page of order references."""

	def __init__(self, orders: "list[Document]") -> None:
		self._orders = {row.name: row for row in orders}
		cart_names = {row.cart_id for row in orders}
		self._carts = load_documents("Ceto Cart Reference", cart_names)
		self._sales_orders = load_documents(
			"Sales Order", {row.sales_order for row in orders}, tables=SALES_ORDER_TABLES
		)
		self._line_references = self._grouped(
			"Ceto Cart Line Item Reference",
			"cart_reference",
			cart_names,
			fields=LINE_REFERENCE_FIELDS,
		)
		self._holds = self._grouped(
			"Ceto Cart Credit Reservation",
			"quotation",
			{cart.quotation for cart in self._carts.values()},
			fields=["credit_line_id", "wallet", "amount", "creation", "modified"],
			filters={"status": "Consumed"},
		)
		self._wallets = self._wallet_types(self._holds)
		self._rules = self._shipping_rules(self._sales_orders.values())
		self._addresses = load_documents(
			"Address", self._address_names(self._sales_orders.values()), tables=("links",)
		)
		self._countries = self._country_codes(self._addresses.values())

	def order(self, name: str) -> "Document | None":
		"""Return the page's order reference document by document name."""
		return self._orders.get(name)

	def cart(self, name: str) -> "Document | None":
		"""Return the completed cart's reference document."""
		return self._carts.get(name)

	def sales_order(self, name: str) -> "Document | None":
		"""Return the placed order's Sales Order document."""
		return self._sales_orders.get(name)

	def shipping_charge(self, sales_order: "Document") -> "AppliedShippingCharge | None":
		"""The Sales Order's applied Shipping Rule charge, rule master preloaded."""
		return CartShipping.applied_charge(sales_order, rules=self._rules)

	def consumed_credits(self, quotation_name: str) -> "list[AppliedCredit]":
		"""The quotation's consumed credit holds, rows and wallets preloaded."""
		return CartCredits.consumed_credits(
			quotation_name, holds=self._holds.get(quotation_name, []), wallets=self._wallets
		)

	def address(self, address_name: str | None) -> "StoreCartAddress | None":
		"""Serialize a linked Address, documents and countries preloaded."""
		return render_address(self._addresses.get(address_name), countries=self._countries)

	def line_references(self, cart_reference: str) -> "list[dict]":
		"""The cart's line item reference rows, in stored order."""
		return self._line_references.get(cart_reference, [])

	@staticmethod
	def _grouped(
		doctype: str,
		key: str,
		values: "set[str]",
		*,
		fields: "list[str]",
		filters: "dict | None" = None,
	) -> "dict[str, list[dict]]":
		"""Bulk-read ``doctype`` rows grouped by ``key``, one query for the page.

		The page-wide ``creation asc, name asc`` ordering keeps every
		group's relative order, so grouped rows read the same as the
		per-record reads they replace.
		"""
		values = {value for value in values if value}
		if not values:
			return {}
		rows = frappe.get_all(
			doctype,
			filters={**(filters or {}), key: ("in", values)},
			fields=[key, *fields],
			order_by="creation asc, name asc",
		)
		grouped: dict[str, list[dict]] = {}
		for row in rows:
			grouped.setdefault(row.get(key), []).append(row)
		return grouped

	@staticmethod
	def _wallet_types(holds: "dict[str, list[dict]]") -> "dict[str, Document | dict]":
		"""Map the wallets behind the page's holds, one query for the page."""
		names = {row.wallet for rows in holds.values() for row in rows}
		if not names:
			return {}
		return {
			row.name: row
			for row in frappe.get_all(
				"Ceto Credit Wallet",
				filters={"name": ("in", names)},
				fields=["name", "wallet_type", "code_hint"],
			)
		}

	@staticmethod
	def _shipping_rules(sales_orders: "list[Document]") -> "dict[str, Document | dict]":
		"""Map the rule masters the page's Sales Orders link, one query."""
		names = {row.shipping_rule for row in sales_orders if row.get("shipping_rule")}
		if not names:
			return {}
		return {
			row.name: row
			for row in frappe.get_all(
				"Shipping Rule", filters={"name": ("in", names)}, fields=["name", *RULE_FIELDS]
			)
		}

	@staticmethod
	def _address_names(sales_orders: "list[Document]") -> "set[str]":
		return {
			name for row in sales_orders for name in (row.customer_address, row.shipping_address_name) if name
		}

	@staticmethod
	def _country_codes(addresses: "list[Document]") -> "dict[str, str]":
		"""Map the page's address countries to their ISO codes, one query.

		Resolved per country rather than per address; a country missing
		from the map renders exactly as a lookup miss would.
		"""
		countries = {address.country for address in addresses if address.country}
		if not countries:
			return {}
		return {
			row.name: row.code
			for row in frappe.get_all("Country", filters={"name": ("in", countries)}, fields=["name", "code"])
		}


def load_documents(
	doctype: str, names: "set[str] | list[str]", *, tables: "tuple[str, ...]" = ()
) -> "dict[str, Document]":
	"""Load existing documents in bulk, with the named child tables attached.

	One query loads the parents, one per child table loads the rows of
	every parent (ordered ``idx asc`` like a document load), and each
	document is assembled through :func:`frappe.get_doc` so the results
	are ordinary documents to their readers.
	"""
	names = {name for name in names if name}
	if not names:
		return {}
	docs = {
		row.name: frappe.get_doc({"doctype": doctype, **row})
		for row in frappe.get_all(doctype, filters={"name": ("in", names)}, fields=["*"])
	}
	if not docs:
		return {}
	table_fields = {field.fieldname: field.options for field in frappe.get_meta(doctype).get_table_fields()}
	for fieldname in tables:
		child_doctype = table_fields.get(fieldname)
		if not child_doctype:
			continue
		rows = frappe.get_all(
			child_doctype,
			filters={"parent": ("in", names), "parenttype": doctype, "parentfield": fieldname},
			fields=["*"],
			order_by="idx asc",
		)
		for row in rows:
			if (doc := docs.get(row.parent)) is not None:
				doc.append(fieldname, row)
	return docs
