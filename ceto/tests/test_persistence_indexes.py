"""Release hardening: the schema indexes behind the order read paths.

The order list and the transfer lifecycle are the orders epic's read
paths, and their guarantees live in the database as much as in code:
owner scoping, publishable-key scope filters, the page joins and the
digest-only transfer credential all ride secondary or unique indexes
declared on the Ceto reference DocTypes (audited in
``docs/orders/phase-6.md``). This suite pins those indexes at the schema
level, so a dropped ``search_index`` / ``unique`` flag fails here instead
of in production. Uniqueness *behavior* is proven by the doctype suites;
this is the index-level net beneath them.
"""

import frappe

from ceto.tests.utils import CetoTestSuite


class TestPersistenceIndexes(CetoTestSuite):
	@staticmethod
	def _indexed(table: str, column: str, *, unique: bool = False) -> bool:
		"""Whether an index on ``table`` leads with ``column`` (uniquely)."""
		return bool(frappe.db.get_column_index(table, column, unique=unique))

	def test_order_reference_indexes(self) -> None:
		"""The list filter and page-join columns stay indexed."""
		table = "tabCeto Order Reference"
		for column in ("order_id", "sales_order", "cart_id"):
			self.assertTrue(self._indexed(table, column, unique=True), column)
		for column in ("owner_customer",):
			self.assertTrue(self._indexed(table, column), column)

	def test_order_transfer_indexes(self) -> None:
		"""The credential, recipient and per-order scan columns stay indexed."""
		table = "tabCeto Order Transfer"
		for column in ("transfer_id", "token_hash"):
			self.assertTrue(self._indexed(table, column, unique=True), column)
		for column in ("order_reference", "requested_by"):
			self.assertTrue(self._indexed(table, column), column)

	def test_cart_reference_indexes(self) -> None:
		"""The completed-cart scope and join columns stay indexed."""
		table = "tabCeto Cart Reference"
		for column in ("cart_id", "quotation"):
			self.assertTrue(self._indexed(table, column, unique=True), column)
		for column in ("owner_user", "owner_customer", "region_id", "sales_channel_id"):
			self.assertTrue(self._indexed(table, column), column)

	def test_collection_indexes(self) -> None:
		"""The public id and the unique stored handle stay uniquely indexed."""
		table = "tabCeto Collection"
		for column in ("collection_id", "handle"):
			self.assertTrue(self._indexed(table, column, unique=True), column)

	def test_product_type_indexes(self) -> None:
		"""The public id and the unique curated value stay uniquely indexed."""
		table = "tabCeto Product Type"
		for column in ("type_id", "value"):
			self.assertTrue(self._indexed(table, column, unique=True), column)
