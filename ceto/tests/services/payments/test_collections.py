"""Payment collection/session persistence: idempotency and staleness.

Runs against the real cart fixtures on the test site inside one rolled-back
transaction: the service keys session idempotency on provider + cart +
current payable, reuses the collection's current ``pending`` session while
those keys hold, and makes the old session stale (``is_current`` 0) with a
fresh current session booked as soon as the payable or provider changes.
"""

import frappe

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError
from ceto.services.carts.quotation import CartService
from ceto.services.payments.collections import PaymentCollections
from ceto.services.payments.providers import ProviderRegistry
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart

BEAM = "pp_beam_beam"
STRIPE = "pp_stripe_stripe"


class StubProvider:
	"""A registry provider whose enabled state the test controls."""

	def __init__(self, provider_id: str, enabled: bool = True) -> None:
		self.provider_id = provider_id
		self.enabled = enabled

	@property
	def id(self) -> str:
		return self.provider_id

	def is_enabled(self) -> bool:
		return self.enabled


def stub_registry(*providers: StubProvider) -> ProviderRegistry:
	return ProviderRegistry(providers)


class TestPaymentCollections(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.reference, self.quotation = self._make_cart()

	def _make_cart(self):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return CartService().create(StoreCreateCart(email="guest@example.com"))

	@property
	def cart_id(self) -> str:
		return self.reference.cart_id

	def _price_cart(self, *, qty: int = 1) -> None:
		"""Give the cart a positive payable through its Quotation rows."""
		self.quotation.append("items", {"item_code": self.masters.item, "qty": qty})
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()

	def _payable(self) -> float:
		return frappe.utils.flt(self.quotation.grand_total)

	def _currency(self) -> str:
		return str(self.quotation.currency).lower()

	def _collection_names(self) -> list[str]:
		return frappe.get_all(
			"Ceto Payment Collection", filters={"cart_reference": self.cart_id}, pluck="name"
		)

	def test_ensure_collection_creates_one_collection_per_cart(self):
		self._price_cart()
		collection = PaymentCollections.ensure_collection(self.cart_id)

		self.assertEqual(collection.payment_collection_id[:8], "pay_col_")
		self.assertEqual(collection.name, collection.payment_collection_id)
		self.assertEqual(collection.cart_reference, self.cart_id)
		self.assertEqual(collection.currency_code, self._currency())
		self.assertEqual(frappe.utils.flt(collection.amount), self._payable())
		self.assertEqual(collection.status, "not_paid")
		self.assertEqual(PaymentCollections.ensure_collection(self.cart_id).name, collection.name)
		self.assertEqual(len(self._collection_names()), 1)

	def test_ensure_session_books_the_current_pending_session(self):
		self._price_cart()
		session = PaymentCollections.ensure_session(
			self.cart_id, BEAM, registry=stub_registry(StubProvider(BEAM))
		)

		self.assertEqual(session.payment_session_id[:7], "payses_")
		self.assertEqual(session.name, session.payment_session_id)
		self.assertEqual(session.provider_id, BEAM)
		self.assertEqual(frappe.utils.flt(session.amount), self._payable())
		self.assertEqual(session.currency_code, self._currency())
		self.assertEqual(session.status, "pending")
		self.assertEqual(session.is_current, 1)
		collection = PaymentCollections.current_collection(self.cart_id)
		self.assertEqual(session.payment_collection, collection.name)

	def test_duplicate_session_creation_is_idempotent(self):
		self._price_cart()
		registry = stub_registry(StubProvider(BEAM))
		first = PaymentCollections.ensure_session(self.cart_id, BEAM, registry=registry)
		second = PaymentCollections.ensure_session(self.cart_id, BEAM, registry=registry)

		self.assertEqual(second.name, first.name)
		self.assertEqual(
			frappe.get_all(
				"Ceto Payment Session", filters={"payment_collection": first.payment_collection}, pluck="name"
			),
			[first.name],
		)

	def test_changed_amount_makes_the_old_session_stale(self):
		self._price_cart(qty=1)
		registry = stub_registry(StubProvider(BEAM))
		first = PaymentCollections.ensure_session(self.cart_id, BEAM, registry=registry)

		self.quotation.items[0].qty = 3
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()
		second = PaymentCollections.ensure_session(self.cart_id, BEAM, registry=registry)

		self.assertNotEqual(second.name, first.name)
		self.assertEqual(second.status, "pending")
		self.assertEqual(frappe.utils.flt(second.amount), self._payable())
		self.assertEqual(frappe.db.get_value("Ceto Payment Session", first.name, "is_current"), 0)
		self.assertEqual(frappe.db.get_value("Ceto Payment Session", second.name, "is_current"), 1)
		# The stale session stays as a history row; the collection's payable
		# columns track the cart's new total.
		self.assertTrue(frappe.db.exists("Ceto Payment Session", first.name))
		collection = PaymentCollections.current_collection(self.cart_id)
		self.assertEqual(frappe.utils.flt(collection.amount), self._payable())

	def test_changed_provider_makes_the_old_session_stale(self):
		self._price_cart()
		registry = stub_registry(StubProvider(BEAM), StubProvider(STRIPE))
		first = PaymentCollections.ensure_session(self.cart_id, BEAM, registry=registry)
		second = PaymentCollections.ensure_session(self.cart_id, STRIPE, registry=registry)

		self.assertNotEqual(second.name, first.name)
		self.assertEqual(second.provider_id, STRIPE)
		self.assertEqual(frappe.db.get_value("Ceto Payment Session", first.name, "is_current"), 0)

	def test_non_pending_session_is_not_reused(self):
		self._price_cart()
		registry = stub_registry(StubProvider(BEAM))
		first = PaymentCollections.ensure_session(self.cart_id, BEAM, registry=registry)
		frappe.db.set_value("Ceto Payment Session", first.name, "status", "authorized")

		second = PaymentCollections.ensure_session(self.cart_id, BEAM, registry=registry)
		self.assertNotEqual(second.name, first.name)
		self.assertEqual(frappe.db.get_value("Ceto Payment Session", first.name, "is_current"), 0)

	def test_unknown_provider_is_refused_without_booking(self):
		self._price_cart()
		with self.assertRaises(InvalidDataError):
			PaymentCollections.ensure_session(
				self.cart_id, "pp_unknown_unknown", registry=stub_registry(StubProvider(BEAM))
			)
		self.assertEqual(self._collection_names(), [])

	def test_disabled_provider_is_refused(self):
		self._price_cart()
		with self.assertRaises(InvalidDataError):
			PaymentCollections.ensure_session(
				self.cart_id, BEAM, registry=stub_registry(StubProvider(BEAM, enabled=False))
			)
		self.assertEqual(self._collection_names(), [])

	def test_unknown_cart_is_masked_as_not_found(self):
		with self.assertRaises(RouteNotFoundError):
			PaymentCollections.ensure_session(
				"cart_missing", BEAM, registry=stub_registry(StubProvider(BEAM))
			)
		with self.assertRaises(RouteNotFoundError):
			PaymentCollections.ensure_collection("cart_missing")

	def test_completed_cart_is_masked_as_not_found(self):
		# A submitted Quotation means the cart completed; sessions are only
		# created for open carts, masked like every cart route masks them.
		self._price_cart()
		self.quotation.submit()
		with self.assertRaises(RouteNotFoundError):
			PaymentCollections.ensure_session(self.cart_id, BEAM, registry=stub_registry(StubProvider(BEAM)))

	def test_zero_payable_cart_is_refused(self):
		# A free cart has no session to create; paygi gateways require a
		# positive amount anyway.
		with self.assertRaises(InvalidDataError):
			PaymentCollections.ensure_session(self.cart_id, BEAM, registry=stub_registry(StubProvider(BEAM)))
		self.assertEqual(self._collection_names(), [])

	def test_current_session_resolves_the_live_row(self):
		self._price_cart()
		registry = stub_registry(StubProvider(BEAM))
		self.assertIsNone(
			PaymentCollections.current_session(PaymentCollections.ensure_collection(self.cart_id))
		)
		session = PaymentCollections.ensure_session(self.cart_id, BEAM, registry=registry)
		self.assertEqual(
			PaymentCollections.current_session(PaymentCollections.current_collection(self.cart_id)).name,
			session.name,
		)
