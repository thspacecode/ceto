"""Phase 5 loyalty endpoints: gift cards add/remove and store credits.

Covers ``POST /store/carts/{id}/gift-cards``, the **bodyful**
``DELETE /store/carts/{id}/gift-cards`` and ``POST /store/carts/{id}/store-credits``
— success, error shapes, authentication (store credits require a customer
session; the gift-card routes keep the optional cart session), publishable-key
access, ``fields`` selection and the serialized totals (the credit deductions
are carved out of the tax fields and the Medusa summary holds
``total + discount_total + credit_line_total == subtotal + tax_total``).

Note: a failed request rolls back the currently uncommitted transaction
(same as a real failed HTTP request), so every subtest that expects an error
and asserts state afterwards commits its cart first instead of reusing
uncommitted state.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.cart_test_data import (
	ITEM_PRICE,
	SHIPPING_FLAT_RATE_AMOUNT,
	TAX_RATE,
	CartTestData,
	gift_card_code_hint,
	make_customer_with_user,
)
from ceto.tests.utils import CetoTestSuite

PAYABLE = ITEM_PRICE * (1 + TAX_RATE / 100)
PAYABLE_WITH_SHIPPING = PAYABLE + SHIPPING_FLAT_RATE_AMOUNT
LINE_TAX = ITEM_PRICE * TAX_RATE / 100
LOYALTY_FIELDS = "id,gift_cards,credit_lines,gift_card_total,gift_card_tax_total,credit_line_total,total,subtotal,tax_total"


class LoyaltyCartAPITestCase(CetoTestSuite):
	"""Shared dispatch helpers for the three loyalty routes."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000
		self.email, self.customer = make_customer_with_user("loyalty")
		self.credit_wallet = self.masters.make_store_credit_wallet(customer=self.customer, credit_total=20.0)
		self.code = f"GC-API-{self.masters.suffix}"
		self.gift_wallet = self.masters.make_gift_card(self.code, credit_total=100.0)
		# The router rolls back the open transaction when converting an error
		# to a response (mirroring Frappe's commit-on-success). Error subtests
		# below therefore need the fixtures committed to survive that.
		frappe.db.commit()  # nosemgrep - commit the API test fixtures
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {
				"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"},
				"pk_other": {"region_id": "reg_other", "sales_channel_id": "sc_other"},
			},
		}

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _cart(
		self,
		*,
		quantity: int = 1,
		with_shipping: bool = False,
		publishable_key: str = "pk_test",
	) -> str:
		created = self._dispatch("POST", "/ceto/store/carts?fields=id", {}, publishable_key=publishable_key)
		self.assertEqual(created.status_code, 200)
		cart_id = created.get_json()["cart"]["id"]
		if quantity:
			added = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items?fields=id",
				{"variant_id": self.masters.item, "quantity": quantity},
				publishable_key=publishable_key,
			)
			self.assertEqual(added.status_code, 200)
		if with_shipping:
			shipped = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=id",
				{"option_id": self.masters.flat_rate_rule},
				publishable_key=publishable_key,
			)
			self.assertEqual(shipped.status_code, 200)
		return cart_id

	def _commit_cart(self) -> str:
		"""Create a one-line cart and commit it, so it survives rollbacks."""
		cart_id = self._cart()
		frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
		return cart_id

	def _loyalty_view(self, cart_id: str, **kwargs) -> dict:
		response = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields={LOYALTY_FIELDS}", **kwargs)
		self.assertEqual(response.status_code, 200)
		return response.get_json()["cart"]

	def _dispatch(
		self,
		method: str,
		path: str,
		payload: dict | None = None,
		*,
		publishable_key: str | None = "pk_test",
	):
		headers = {"x-publishable-api-key": publishable_key} if publishable_key else None
		builder = EnvironBuilder(
			path=path,
			method=method,
			data=json.dumps(payload) if payload is not None else None,
			content_type="application/json" if payload is not None else None,
			headers=headers,
			environ_base={"REMOTE_ADDR": "127.0.0.1"},
		)
		request = Request(builder.get_environ())
		with self.set_request(request):
			return ceto_router.dispatch(request)


class TestCartGiftCardAPI(LoyaltyCartAPITestCase):
	def test_apply_reports_the_hint_credit_line_and_totals(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/gift-cards?fields={LOYALTY_FIELDS}",
				{"code": self.code},
			)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(response.get_json()), {"cart"})
		cart = response.get_json()["cart"]
		# The response carries the masked hint only — never the submitted code.
		self.assertEqual(cart["gift_cards"], [{"code": gift_card_code_hint(self.code)}])
		self.assertNotIn(self.code, json.dumps(response.get_json()))
		self.assertEqual(len(cart["credit_lines"]), 1)
		line = cart["credit_lines"][0]
		self.assertEqual(line["reference"], "gift-card")
		self.assertEqual(line["reference_id"], self.gift_wallet)
		# The 100 card is capped by the 27.5 payable.
		self.assertAlmostEqual(cart["credit_lines"][0]["amount"], PAYABLE)
		self.assertAlmostEqual(cart["gift_card_total"], PAYABLE)
		self.assertAlmostEqual(cart["credit_line_total"], PAYABLE)
		self.assertAlmostEqual(cart["total"], 0)

	def test_apply_is_idempotent(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart()
			first = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": self.code})
			second = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": self.code})
			cart = self._loyalty_view(cart_id)
		self.assertEqual(first.status_code, 200)
		self.assertEqual(second.status_code, 200)
		self.assertEqual(len(cart["credit_lines"]), 1)
		self.assertEqual(len(cart["gift_cards"]), 1)

	def test_unknown_code_is_invalid_data_without_mutation(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._commit_cart()
			response = self._dispatch(
				"POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": "GC-NOT-A-CARD"}
			)
			cart = self._loyalty_view(cart_id)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")
		self.assertEqual(cart["gift_cards"], [])
		self.assertEqual(cart["credit_lines"], [])
		self.assertAlmostEqual(cart["total"], PAYABLE)

	def test_wrong_currency_card_is_invalid_data(self) -> None:
		self.masters.make_gift_card(f"GC-EUR-{self.masters.suffix}", credit_total=50.0, currency="EUR")
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._commit_cart()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/gift-cards",
				{"code": f"GC-EUR-{self.masters.suffix}"},
			)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_exhausted_card_is_invalid_data(self) -> None:
		self.masters.make_gift_card(f"GC-EMPTY-{self.masters.suffix}", credit_total=0)
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._commit_cart()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/gift-cards",
				{"code": f"GC-EMPTY-{self.masters.suffix}"},
			)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_itemless_cart_is_invalid_data(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart(quantity=0)
			response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": self.code})
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_blank_and_foreign_payload_fields_are_rejected(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart()
			for payload in ({"code": "   "}, {"code": self.code, "gift_card_id": "gc_1"}, {}):
				with self.subTest(payload=payload):
					response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", payload)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_requires_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"POST",
				"/ceto/store/carts/cart_missing/gift-cards",
				{"code": self.code},
				publishable_key=None,
			)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_wrong_scoped_key_is_not_allowed(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._commit_cart()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/gift-cards",
				{"code": self.code},
				publishable_key="pk_other",
			)
			cart = self._loyalty_view(cart_id)
		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.get_json()["type"], "not_allowed")
		self.assertEqual(cart["gift_cards"], [])
		self.assertEqual(cart["credit_lines"], [])


class TestCartRemoveGiftCardAPI(LoyaltyCartAPITestCase):
	def test_bodyful_delete_releases_the_hold(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart()
			applied = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": self.code})
			self.assertEqual(applied.status_code, 200)

			# The pinned removal is a bodyful DELETE: the strict {code} object
			# rides on the DELETE itself.
			removed = self._dispatch(
				"DELETE",
				f"/ceto/store/carts/{cart_id}/gift-cards?fields={LOYALTY_FIELDS}",
				{"code": self.code},
			)
		self.assertEqual(removed.status_code, 200)
		self.assertEqual(set(removed.get_json()), {"cart"})
		cart = removed.get_json()["cart"]
		self.assertEqual(cart["gift_cards"], [])
		self.assertEqual(cart["credit_lines"], [])
		self.assertAlmostEqual(cart["gift_card_total"], 0)
		self.assertAlmostEqual(cart["credit_line_total"], 0)
		# The full payable is restored (item + shipping-free cart).
		self.assertAlmostEqual(cart["total"], PAYABLE)
		self.assertAlmostEqual(cart["tax_total"], LINE_TAX)

	def test_delete_without_body_is_invalid_data(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart()
			applied = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": self.code})
			self.assertEqual(applied.status_code, 200)
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests

			response = self._dispatch("DELETE", f"/ceto/store/carts/{cart_id}/gift-cards", None)
			cart = self._loyalty_view(cart_id)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")
		self.assertEqual([gift["code"] for gift in cart["gift_cards"]], [gift_card_code_hint(self.code)])

	def test_delete_unknown_code_is_invalid_data(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart()
			applied = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": self.code})
			self.assertEqual(applied.status_code, 200)
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests

			response = self._dispatch(
				"DELETE", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": "GC-NOT-A-CARD"}
			)
			cart = self._loyalty_view(cart_id)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")
		self.assertEqual(len(cart["gift_cards"]), 1)

	def test_delete_unapplied_code_is_invalid_data(self) -> None:
		self.masters.make_gift_card(f"GC-OTHER-{self.masters.suffix}", credit_total=50.0)
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart()
			response = self._dispatch(
				"DELETE",
				f"/ceto/store/carts/{cart_id}/gift-cards",
				{"code": f"GC-OTHER-{self.masters.suffix}"},
			)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_requires_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"DELETE",
				"/ceto/store/carts/cart_missing/gift-cards",
				{"code": self.code},
				publishable_key=None,
			)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_wrong_scoped_key_cannot_release(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart()
			applied = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": self.code})
			self.assertEqual(applied.status_code, 200)
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests

			response = self._dispatch(
				"DELETE",
				f"/ceto/store/carts/{cart_id}/gift-cards",
				{"code": self.code},
				publishable_key="pk_other",
			)
			# The hold survives: the guard rejects before the ledger is touched.
			cart = self._loyalty_view(cart_id)
		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.get_json()["type"], "not_allowed")
		self.assertEqual(len(cart["credit_lines"]), 1)


class TestCartStoreCreditAPI(LoyaltyCartAPITestCase):
	def _apply(self, cart_id: str, payload: dict, **kwargs) -> "object":
		return self._dispatch(
			"POST", f"/ceto/store/carts/{cart_id}/store-credits?fields={LOYALTY_FIELDS}", payload, **kwargs
		)

	def test_apply_reserves_the_whole_available_balance(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			cart_id = self._cart()
			response = self._apply(cart_id, {})
		self.assertEqual(response.status_code, 200)
		cart = response.get_json()["cart"]
		self.assertEqual(len(cart["credit_lines"]), 1)
		line = cart["credit_lines"][0]
		self.assertEqual(line["reference"], "store-credit")
		self.assertEqual(line["reference_id"], self.credit_wallet)
		self.assertAlmostEqual(line["amount"], 20.0)
		self.assertEqual(cart["gift_cards"], [])
		self.assertEqual(cart["gift_card_total"], 0)
		self.assertAlmostEqual(cart["credit_line_total"], 20.0)
		self.assertAlmostEqual(cart["total"], PAYABLE - 20.0)

	def test_apply_explicit_amount(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			cart_id = self._cart()
			response = self._apply(cart_id, {"amount": 10})
		self.assertEqual(response.status_code, 200)
		cart = response.get_json()["cart"]
		self.assertAlmostEqual(cart["credit_lines"][0]["amount"], 10.0)
		self.assertAlmostEqual(cart["total"], PAYABLE - 10.0)

	def test_unknown_fields_are_stripped(self) -> None:
		# The pinned plugin validator is a lenient z.object: unknown fields
		# are stripped, not rejected.
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			cart_id = self._cart()
			response = self._apply(cart_id, {"amount": 10, "store_credit_id": "sca_1"})
		self.assertEqual(response.status_code, 200)
		self.assertAlmostEqual(response.get_json()["cart"]["credit_lines"][0]["amount"], 10.0)

	def test_reapplication_replaces_the_prior_hold(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			cart_id = self._cart()
			first = self._apply(cart_id, {"amount": 10})
			second = self._apply(cart_id, {"amount": 15})
		self.assertEqual(first.status_code, 200)
		self.assertEqual(second.status_code, 200)
		cart = second.get_json()["cart"]
		self.assertEqual([line["amount"] for line in cart["credit_lines"]], [15.0])
		self.assertAlmostEqual(cart["total"], PAYABLE - 15.0)

	def test_unauthenticated_is_unauthorized(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._commit_cart()
			response = self._apply(cart_id, {})
			cart = self._loyalty_view(cart_id)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")
		self.assertEqual(cart["credit_lines"], [])
		self.assertAlmostEqual(cart["total"], PAYABLE)

	def test_user_without_customer_is_unauthorized(self) -> None:
		email = f"ceto.api.nocontact.{self.masters.suffix}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Api No Contact",
				"user_type": "Website User",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		)
		with self.bypass_user_creation_throttle():
			user.insert(ignore_permissions=True)
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			cart_id = self._commit_cart()
			response = self._apply(cart_id, {})
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_customer_without_wallet_is_invalid_data(self) -> None:
		other_email, _other_customer = make_customer_with_user("loyalty-other")
		frappe.db.commit()  # nosemgrep - commit the API test fixtures
		with self.set_conf(ceto_cart=self.configuration), self.set_user(other_email):
			cart_id = self._commit_cart()
			response = self._apply(cart_id, {})
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_amount_exceeding_balance_is_invalid_data(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			cart_id = self._commit_cart()
			response = self._apply(cart_id, {"amount": 50})
			cart = self._loyalty_view(cart_id)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")
		self.assertEqual(cart["credit_lines"], [])
		self.assertAlmostEqual(cart["total"], PAYABLE)

	def test_non_positive_amount_is_invalid_data(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			cart_id = self._cart()
			for amount in (0, -5):
				with self.subTest(amount=amount):
					response = self._apply(cart_id, {"amount": amount})
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_requires_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			response = self._dispatch(
				"POST",
				"/ceto/store/carts/cart_missing/store-credits",
				{},
				publishable_key=None,
			)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_wrong_scoped_key_is_not_allowed(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			cart_id = self._cart()
			applied = self._apply(cart_id, {"amount": 10})
			self.assertEqual(applied.status_code, 200)
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests

			response = self._apply(cart_id, {"amount": 15}, publishable_key="pk_other")
			# The prior reservation is untouched.
			cart = self._loyalty_view(cart_id)
		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.get_json()["type"], "not_allowed")
		self.assertEqual([line["amount"] for line in cart["credit_lines"]], [10.0])

	def test_claimed_cart_of_another_customer_is_not_found(self) -> None:
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user("Guest"):
				cart_id = self._commit_cart()
			with self.set_user(self.email):
				claimed = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/customer", None)
				self.assertEqual(claimed.status_code, 200)
			other_email, _other_customer = make_customer_with_user("loyalty-rival")
			frappe.db.commit()  # nosemgrep - commit the API test fixtures
			with self.set_user(other_email):
				response = self._apply(cart_id, {})
		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.get_json()["type"], "not_found")


class TestCartLoyaltyTotalsAPI(LoyaltyCartAPITestCase):
	"""Serialized totals: the carve-out and the Medusa summary invariant."""

	TOTALS_FIELDS = (
		"id,gift_cards,credit_lines,gift_card_total,gift_card_tax_total,credit_line_total,"
		"total,subtotal,tax_total,item_tax_total,discount_total,shipping_total,items"
	)

	@staticmethod
	def _assert_invariant(test: CetoTestSuite, cart: dict) -> None:
		test.assertAlmostEqual(
			cart["total"] + cart["discount_total"] + cart["credit_line_total"],
			cart["subtotal"] + cart["tax_total"],
		)

	def test_gift_card_totals_carve_out_the_charges(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart(with_shipping=True)
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/gift-cards?fields={self.TOTALS_FIELDS}",
				{"code": self.code},
			)
		self.assertEqual(response.status_code, 200)
		cart = response.get_json()["cart"]
		# The shipping charge and the negative deduction row are carved out of
		# the tax fields: only the template's item tax reports.
		self.assertAlmostEqual(cart["subtotal"], ITEM_PRICE + SHIPPING_FLAT_RATE_AMOUNT)
		self.assertAlmostEqual(cart["tax_total"], LINE_TAX)
		self.assertAlmostEqual(cart["item_tax_total"], LINE_TAX)
		self.assertAlmostEqual(cart["items"][0]["tax_total"], LINE_TAX)
		self.assertAlmostEqual(cart["gift_card_tax_total"], 0)
		# The deduction itself stays inside ERPNext's grand total.
		self.assertAlmostEqual(cart["gift_card_total"], PAYABLE_WITH_SHIPPING)
		self.assertAlmostEqual(cart["credit_line_total"], PAYABLE_WITH_SHIPPING)
		self.assertAlmostEqual(cart["total"], 0)
		self._assert_invariant(self, cart)

	def test_store_credit_totals_hold_the_invariant(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user(self.email):
			cart_id = self._cart(with_shipping=True)
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/store-credits?fields={self.TOTALS_FIELDS}",
				{"amount": 20},
			)
		self.assertEqual(response.status_code, 200)
		cart = response.get_json()["cart"]
		self.assertAlmostEqual(cart["tax_total"], LINE_TAX)
		self.assertAlmostEqual(cart["credit_line_total"], 20.0)
		self.assertAlmostEqual(cart["gift_card_total"], 0)
		self.assertAlmostEqual(cart["total"], PAYABLE_WITH_SHIPPING - 20.0)
		self.assertAlmostEqual(cart["items"][0]["tax_total"], LINE_TAX)
		self._assert_invariant(self, cart)

	def test_remove_restores_the_pre_credit_summary(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart(with_shipping=True)
			applied = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/gift-cards", {"code": self.code})
			self.assertEqual(applied.status_code, 200)
			removed = self._dispatch(
				"DELETE",
				f"/ceto/store/carts/{cart_id}/gift-cards?fields={self.TOTALS_FIELDS}",
				{"code": self.code},
			)
		self.assertEqual(removed.status_code, 200)
		cart = removed.get_json()["cart"]
		self.assertEqual(cart["gift_cards"], [])
		self.assertEqual(cart["credit_lines"], [])
		self.assertAlmostEqual(cart["credit_line_total"], 0)
		self.assertAlmostEqual(cart["gift_card_total"], 0)
		# Without credits the identity is the pre-Phase-5 one again.
		self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])
		self.assertAlmostEqual(cart["items"][0]["tax_total"], LINE_TAX)
		self._assert_invariant(self, cart)
