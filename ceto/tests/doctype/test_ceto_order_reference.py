"""Phase 6 completion record: Ceto Order Reference persistence.

Runs a real guest cart through completion-shaped fixtures on the test site
inside a single rolled-back transaction: the record is named by the public
order id, maps it onto the ERPNext Sales Order the cart Quotation produced
(ERPNext's own mapper, Phase 0), and can only exist once the cart actually
completed — its Quotation submitted and the Sales Order the completion's
own mapper produced from *that* Quotation submitted too. From then on every
cart route masks the completed cart while the order stays resolvable by
``cart_id`` for the complete replay.
"""

import uuid

import frappe
from frappe.utils import add_to_date, today

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.carts.conversion import convert_quotation_to_sales_order
from ceto.services.carts.quotation import CartService
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class TestCetoOrderReference(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.reference, self.quotation = self._make_cart()

	def _make_cart(self):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return CartService().create(StoreCreateCart(email="guest@example.com"))

	def _complete_cart(self, reference=None, quotation=None):
		"""Close a cart the way completion does; return its Sales Order.

		ERPNext requires line items before a Quotation can be submitted, so
		the fixture prices one item, submits the Quotation and maps it into
		a submitted Sales Order through the ERPNext mapper.
		"""
		reference = reference or self.reference
		quotation = quotation or self.quotation
		quotation.append("items", {"item_code": self.masters.item, "qty": 1})
		quotation.flags.ignore_mandatory = True
		quotation.save(ignore_permissions=True)
		quotation.submit()
		return convert_quotation_to_sales_order(quotation.name, submit=True)

	def _make_standalone_sales_order(self, *, submit: bool = False):
		"""A second, unrelated Sales Order (its own customer lineage).

		Uniqueness and lineage assertions must fail on the constraint under
		test, never as a side effect of a draft or a shared quotation.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": self.masters.customer,
				"company": self.masters.company,
				"currency": self.quotation.currency,
				"selling_price_list": self.masters.price_list,
				"transaction_date": today(),
				"delivery_date": add_to_date(today(), days=7),
				"items": [{"item_code": self.masters.item, "qty": 1}],
			}
		).insert(ignore_permissions=True)
		if submit:
			doc.submit()
		return doc

	def _make_order_reference(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Order Reference",
				"order_id": f"order_{uuid.uuid4().hex}",
				"sales_order": self.sales_order.name,
				"cart_id": self.reference.name,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_order_by_public_order_id(self) -> None:
		self.sales_order = self._complete_cart()
		order_id = f"order_{uuid.uuid4().hex}"
		self._make_order_reference(order_id=order_id)

		loaded = frappe.get_doc("Ceto Order Reference", order_id)
		self.assertEqual(loaded.name, order_id)
		self.assertEqual(loaded.sales_order, self.sales_order.name)
		self.assertEqual(loaded.cart_id, self.reference.name)

	def test_order_id_is_unique(self) -> None:
		self.sales_order = self._complete_cart()
		order_id = f"order_{uuid.uuid4().hex}"
		self._make_order_reference(order_id=order_id)
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self._make_order_reference(order_id=order_id)

	def test_one_order_per_cart(self) -> None:
		self.sales_order = self._complete_cart()
		self._make_order_reference()
		# A cart completes once: retries replay the same order instead of
		# mapping a second Sales Order, so the cart id is unique too. A
		# second reference for the same completed cart passes every
		# validation — the placed Sales Order is the genuine completion of
		# exactly this cart — and is rejected by the unique indexes alone.
		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self._make_order_reference()

	def test_rejects_unknown_sales_order(self) -> None:
		self.sales_order = self._complete_cart()
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_order_reference(sales_order=f"SO-missing-{uuid.uuid4().hex}")

	def test_rejects_draft_sales_order(self) -> None:
		self.sales_order = self._complete_cart()
		draft = self._make_standalone_sales_order()
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_order_reference(sales_order=draft.name)

	def test_rejects_foreign_sales_order(self) -> None:
		self.sales_order = self._complete_cart()
		# A submitted Sales Order that was never mapped from this cart's
		# Quotation must not be bookable onto it.
		foreign = self._make_standalone_sales_order(submit=True)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_order_reference(sales_order=foreign.name)

	def test_rejects_unknown_cart(self) -> None:
		self.sales_order = self._complete_cart()
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_order_reference(cart_id=f"cart_{uuid.uuid4().hex}")

	def test_rejects_order_for_an_open_cart(self) -> None:
		self.sales_order = self._complete_cart()
		open_reference, _open_quotation = self._make_cart()

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_order_reference(cart_id=open_reference.name)

	def test_completed_cart_is_masked_but_replayable_by_cart_id(self) -> None:
		self.sales_order = self._complete_cart()
		reference = self._make_order_reference()

		# The submitted Quotation takes the cart off every cart route...
		with self.assertRaises(RouteNotFoundError):
			CartService().retrieve(self.reference.name)

		# ...so the complete replay resolves the order by cart id instead.
		self.assertEqual(
			frappe.db.get_value("Ceto Order Reference", {"cart_id": self.reference.name}, "name"),
			reference.name,
		)
