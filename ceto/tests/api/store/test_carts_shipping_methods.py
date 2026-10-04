"""Phase 4 shipping-methods endpoint: ``POST /store/carts/{id}/shipping-methods``.

Note: a failed request rolls back the currently uncommitted transaction
(same as a real failed HTTP request), so every subtest that expects an error
provisions a fresh cart (or commits the preceding state) instead of reusing
earlier uncommitted carts.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite

# Replacement across charge rows needs a rule posting to a dedicated account
# (with the shared fixture account ERPNext rewrites the single row in place).
ALT_SHIPPING_ACCOUNT = "Ceto API Test Alt Shipping Charges"
ALT_RATE_LABEL = "Ceto API Test Alt Account Rate"
ALT_RATE_AMOUNT = 75.0


class TestCartShippingMethodsAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# An earlier test's committed cart (kept to survive a request rollback)
		# leaves its guest-linked temporary Address behind; ERPNext would refill
		# this module's addressless carts from it as the guest party default.
		self.masters.discard_committed_cart_temporaries()
		self.alt_rule = self._make_alt_rate_rule()
		# The router rolls back the open transaction when converting an error
		# to a response (mirroring Frappe's commit-on-success). Error subtests
		# below therefore need the master data committed to survive that.
		frappe.db.commit()
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {
				"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"},
				"pk_other": {"region_id": "reg_other", "sales_channel_id": "sc_other"},
			},
		}

	def _make_alt_rate_rule(self) -> str:
		abbr = frappe.db.get_value("Company", self.masters.company, "abbr")
		account = frappe.db.get_value(
			"Account", {"account_name": ALT_SHIPPING_ACCOUNT, "company": self.masters.company, "is_group": 0}
		)
		if not account:
			account = (
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": ALT_SHIPPING_ACCOUNT,
						"parent_account": f"Direct Income - {abbr}",
						"company": self.masters.company,
						"is_group": 0,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
			frappe.db.commit()  # nosemgrep
		return self.masters.make_shipping_rule(
			ALT_RATE_LABEL, account=account, shipping_amount=ALT_RATE_AMOUNT
		)

	def _cart_with_line(self, **create_kwargs) -> str:
		created = self._dispatch("POST", "/ceto/store/carts?fields=id", create_kwargs or {})
		self.assertEqual(created.status_code, 200)
		cart_id = created.get_json()["cart"]["id"]
		added = self._dispatch(
			"POST",
			f"/ceto/store/carts/{cart_id}/line-items?fields=id",
			{"variant_id": self.masters.item, "quantity": 1},
		)
		self.assertEqual(added.status_code, 200)
		return cart_id

	def _quotation_of(self, cart_id: str):
		quotation = frappe.db.get_value("Ceto Cart Reference", {"cart_id": cart_id}, "quotation")
		return frappe.get_doc("Quotation", quotation)

	def test_apply_fixed_rule(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			applied = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=id,shipping_methods,shipping_total",
				{"option_id": self.masters.flat_rate_rule},
			)
			self.assertEqual(applied.status_code, 200)
			cart = applied.get_json()["cart"]
			self.assertEqual(len(cart["shipping_methods"]), 1)
			method = cart["shipping_methods"][0]
			self.assertEqual(method["shipping_option_id"], self.masters.flat_rate_rule)
			self.assertEqual(method["name"], "Ceto Test Flat Rate")
			self.assertEqual(method["amount"], 50)
			self.assertEqual(method["tax_total"], 0)
			self.assertEqual(cart["shipping_total"], 50)

			# The method persists with the cart.
			fetched = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=shipping_methods")
			self.assertEqual(fetched.get_json()["cart"]["shipping_methods"], cart["shipping_methods"])

	def test_reapplying_the_same_option_keeps_one_charge(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			for _ in range(2):
				applied = self._dispatch(
					"POST",
					f"/ceto/store/carts/{cart_id}/shipping-methods?fields=shipping_methods,subtotal,tax_total,total",
					{"option_id": self.masters.flat_rate_rule},
				)
				self.assertEqual(applied.status_code, 200)
				cart = applied.get_json()["cart"]
				self.assertEqual(len(cart["shipping_methods"]), 1)
				self.assertEqual(cart["shipping_methods"][0]["amount"], 50)
				# The grand total carries the charge exactly once.
				self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])
				rows = self._quotation_of(cart_id).get("taxes", filters={"charge_type": "Actual"})
				self.assertEqual(len(rows), 1)

	def test_replace_option(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods",
				{"option_id": self.masters.flat_rate_rule},
			)

			replaced = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=shipping_methods,subtotal,tax_total,total",
				{"option_id": self.masters.country_rate_rule},
			)
			self.assertEqual(replaced.status_code, 200)
			cart = replaced.get_json()["cart"]
			self.assertEqual(len(cart["shipping_methods"]), 1)
			self.assertEqual(
				cart["shipping_methods"][0]["shipping_option_id"], self.masters.country_rate_rule
			)
			self.assertEqual(cart["shipping_methods"][0]["amount"], 25)
			self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])

	def test_replace_across_accounts_drops_the_previous_charge(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods",
				{"option_id": self.masters.flat_rate_rule},
			)

			replaced = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=shipping_methods,subtotal,tax_total,total",
				{"option_id": self.alt_rule},
			)
			self.assertEqual(replaced.status_code, 200)
			cart = replaced.get_json()["cart"]
			# Exactly one method, on the new account, and the grand total only
			# carries the new charge (subtotal + tax reconcile up to it).
			self.assertEqual(len(cart["shipping_methods"]), 1)
			self.assertEqual(cart["shipping_methods"][0]["shipping_option_id"], self.alt_rule)
			self.assertEqual(cart["shipping_methods"][0]["amount"], ALT_RATE_AMOUNT)
			self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])

	def test_unknown_option_is_invalid_data_without_mutation(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			response = self._dispatch(
				"POST", f"/ceto/store/carts/{cart_id}/shipping-methods", {"option_id": "Ceto Missing Rule"}
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

			cart = self._dispatch(
				"GET", f"/ceto/store/carts/{cart_id}?fields=shipping_methods,shipping_total"
			).get_json()["cart"]
			self.assertEqual(cart["shipping_methods"], [])
			self.assertEqual(cart["shipping_total"], 0)
			self.assertIsNone(self._quotation_of(cart_id).shipping_rule)

	def test_disabled_option_is_invalid_data_without_mutation(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods",
				{"option_id": self.masters.disabled_rate_rule},
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

			cart = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=shipping_methods").get_json()[
				"cart"
			]
			self.assertEqual(cart["shipping_methods"], [])
			self.assertIsNone(self._quotation_of(cart_id).shipping_rule)

	def test_country_mismatch_is_invalid_data_without_mutation(self) -> None:
		# The country-rate rule only accepts the bootstrap country; ERPNext
		# rejects it for a shipping address elsewhere on the controller save.
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			# The commit below persists the cart's India temporary Address; it
			# must not outlive this test as the shared guest Customer's default.
			self.addCleanup(self.masters.discard_committed_cart_temporaries)
			cart_id = self._cart_with_line(
				shipping_address={"country_code": "IN", "address_1": "1 Main Rd", "city": "Mumbai"}
			)
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods",
				{"option_id": self.masters.country_rate_rule},
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

			cart = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=shipping_methods").get_json()[
				"cart"
			]
			self.assertEqual(cart["shipping_methods"], [])
			self.assertIsNone(self._quotation_of(cart_id).shipping_rule)

	def test_mismatch_fixture_is_not_inherited_by_addressless_carts(self) -> None:
		# Regression: the mismatch subtest commits its cart so the failing
		# request's rollback cannot erase it, and the commit persists its India
		# temporary Address on the shared guest Customer. The next addressless
		# cart must stay addressless (ERPNext must not refill its empty slot
		# from that leftover as the guest party default) and must still be able
		# to apply the country rule.
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			self._cart_with_line(
				shipping_address={"country_code": "IN", "address_1": "1 Main Rd", "city": "Mumbai"}
			)
			frappe.db.commit()  # nosemgrep - recreate the committed mismatch fixture

			# The fixture cleanup under test must leave no guest-linked
			# temporary behind for ERPNext to refill the empty slot from.
			self.masters.discard_committed_cart_temporaries()
			self.addCleanup(self.masters.discard_committed_cart_temporaries)
			self.assertFalse(
				frappe.get_all(
					"Address",
					filters=[
						["Dynamic Link", "link_doctype", "=", "Customer"],
						["Dynamic Link", "link_name", "=", self.masters.customer],
						["address_title", "like", "Cart %"],
					],
				)
			)

			cart_id = self._cart_with_line()
			self.assertIsNone(self._quotation_of(cart_id).shipping_address_name)
			applied = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=shipping_methods",
				{"option_id": self.masters.country_rate_rule},
			)
			self.assertEqual(applied.status_code, 200)
			self.assertEqual(
				applied.get_json()["cart"]["shipping_methods"][0]["shipping_option_id"],
				self.masters.country_rate_rule,
			)

	def test_eligible_country_applies_the_country_rule(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line(
				shipping_address={"country_code": "US", "address_1": "1 Main St", "city": "New York"}
			)
			applied = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=shipping_methods",
				{"option_id": self.masters.country_rate_rule},
			)
			self.assertEqual(applied.status_code, 200)
			methods = applied.get_json()["cart"]["shipping_methods"]
			self.assertEqual(
				[method["shipping_option_id"] for method in methods], [self.masters.country_rate_rule]
			)

	def test_payload_data_is_accepted_but_never_persisted(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			applied = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=metadata,shipping_methods",
				{"option_id": self.masters.flat_rate_rule, "data": {"parcels": 2}},
			)
			self.assertEqual(applied.status_code, 200)
			cart = applied.get_json()["cart"]
			self.assertEqual(len(cart["shipping_methods"]), 1)

			# No compatibility field exists, so nothing about the request
			# payload is stored: not cart metadata, not Quotation state.
			self.assertIsNone(cart["metadata"])
			self.assertIsNone(frappe.db.get_value("Ceto Cart Reference", {"cart_id": cart_id}, "metadata"))

	def test_requires_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"POST",
				"/ceto/store/carts/shipping-methods-x/shipping-methods",
				{"option_id": self.masters.flat_rate_rule},
				publishable_key=None,
			)
			self.assertEqual(response.status_code, 401)

	def test_wrong_scoped_key_cannot_mutate_shipping_methods(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods",
				{"option_id": self.masters.flat_rate_rule},
				publishable_key="pk_other",
			)
			self.assertEqual(response.status_code, 403)
			self.assertIsNone(self._quotation_of(cart_id).shipping_rule)

	def test_invalid_payloads_are_rejected(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			for payload in (
				{},
				{"option_id": ""},
				{"option_id": self.masters.flat_rate_rule, "cart_id": "x"},
			):
				with self.subTest(payload=payload):
					response = self._dispatch(
						"POST", f"/ceto/store/carts/{cart_id}/shipping-methods", payload
					)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_unknown_cart_is_not_found(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"POST",
				"/ceto/store/carts/cart_missing/shipping-methods",
				{"option_id": self.masters.flat_rate_rule},
			)
			self.assertEqual(response.status_code, 404)
			self.assertEqual(response.get_json()["type"], "not_found")

	def test_fields_selection(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=id,shipping_methods",
				{"option_id": self.masters.flat_rate_rule},
			)
			self.assertEqual(response.status_code, 200)
			self.assertEqual(set(response.get_json()["cart"]), {"id", "shipping_methods"})

			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=id,not_a_field",
				{"option_id": self.masters.flat_rate_rule},
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

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
