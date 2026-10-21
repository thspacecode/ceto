"""Phase 4 cart round-trip slice: the opaque option id across the surfaces.

Pins the guest journey on the test site: the option the list and
calculate surfaces serve under their opaque ``so_`` id is the one the
cart shipping-methods apply accepts, the applied method echoes that id
back with the option's amount and name, an idempotent re-apply keeps
one charge row, and a malformed or foreign-provider token is the
existing ``400 invalid_data`` unknown-option rejection with the cart
untouched. The legacy raw rule name stays accepted and echoed.

Note: a failed request rolls back the currently uncommitted transaction
(same as a real failed HTTP request), so the error subtest commits its
cart first instead of reusing earlier uncommitted carts.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.services.carts.shipping import UNKNOWN_OPTION
from ceto.services.shipping.ids import encode_option_id
from ceto.services.shipping.providers.erpnext import PROVIDER_ID
from ceto.tests.data.cart_test_data import (
	SHIPPING_COUNTRY_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_LABEL,
	CartTestData,
)
from ceto.tests.utils import CetoTestSuite


class TestShippingOptionsCartRoundtripAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# An earlier test's committed cart (kept to survive a request rollback)
		# leaves its guest-linked temporary Address behind; ERPNext would refill
		# this module's addressless carts from it as the guest party default.
		self.masters.discard_committed_cart_temporaries()
		# The router rolls back the open transaction when converting an error
		# to a response (mirroring Frappe's commit-on-success). The error
		# subtest below therefore needs its cart committed to survive that.
		frappe.db.commit()
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {
				"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"},
			},
		}

	def _flat_option_id(self) -> str:
		return encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule)

	def _cart_with_line(self) -> str:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			created = self._dispatch("POST", "/ceto/store/carts?fields=id", {})
			self.assertEqual(created.status_code, 200)
			cart_id = created.get_json()["cart"]["id"]
			added = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items?fields=id",
				{"variant_id": self.masters.item, "quantity": 1},
			)
			self.assertEqual(added.status_code, 200)
			return cart_id

	def _list_options(self, cart_id: str) -> list:
		response = self._dispatch("GET", f"/ceto/store/shipping-options?cart_id={cart_id}")
		self.assertEqual(response.status_code, 200)
		return response.get_json()["shipping_options"]

	def _calculate(self, cart_id: str, option_id: str) -> dict:
		response = self._dispatch(
			"POST", f"/ceto/store/shipping-options/{option_id}/calculate", {"cart_id": cart_id}
		)
		self.assertEqual(response.status_code, 200)
		return response.get_json()["shipping_option"]

	def _apply(self, cart_id: str, option_id: str, fields: str = "shipping_methods,shipping_total"):
		return self._dispatch(
			"POST",
			f"/ceto/store/carts/{cart_id}/shipping-methods?fields={fields}",
			{"option_id": option_id},
		)

	def _quotation_of(self, cart_id: str):
		quotation = frappe.db.get_value("Ceto Cart Reference", {"cart_id": cart_id}, "quotation")
		return frappe.get_doc("Quotation", quotation)

	def test_list_calculate_add_to_cart_roundtrip(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()

			listed = next(
				option for option in self._list_options(cart_id) if option["name"] == SHIPPING_FLAT_RATE_LABEL
			)
			option_id = listed["id"]
			self.assertEqual(option_id, self._flat_option_id())

			# The calculated price matches the listing.
			calculated = self._calculate(cart_id, option_id)
			self.assertEqual(calculated["id"], option_id)
			self.assertEqual(calculated["amount"], SHIPPING_FLAT_RATE_AMOUNT)

			# The listed id applies, and the cart echoes it with the
			# option's amount and name — no re-derivation anywhere.
			applied = self._apply(cart_id, option_id)
			self.assertEqual(applied.status_code, 200)
			cart = applied.get_json()["cart"]
			self.assertEqual(len(cart["shipping_methods"]), 1)
			method = cart["shipping_methods"][0]
			self.assertEqual(method["shipping_option_id"], option_id)
			self.assertEqual(method["name"], listed["name"])
			self.assertEqual(method["amount"], listed["amount"])
			self.assertEqual(method["amount"], calculated["amount"])
			self.assertEqual(cart["shipping_total"], SHIPPING_FLAT_RATE_AMOUNT)

			# The echo persists with the cart.
			fetched = self._dispatch(
				"GET", f"/ceto/store/carts/{cart_id}?fields=shipping_methods,shipping_total"
			)
			self.assertEqual(fetched.get_json()["cart"]["shipping_methods"], cart["shipping_methods"])
			self.assertEqual(fetched.get_json()["cart"]["shipping_total"], SHIPPING_FLAT_RATE_AMOUNT)

	def test_roundtrip_reapply_is_idempotent(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			first = self._apply(cart_id, self._flat_option_id())
			self.assertEqual(first.status_code, 200)

			second = self._apply(cart_id, self._flat_option_id(), "shipping_methods,subtotal,tax_total,total")
			self.assertEqual(second.status_code, 200)
			cart = second.get_json()["cart"]
			self.assertEqual(len(cart["shipping_methods"]), 1)
			self.assertEqual(cart["shipping_methods"][0]["shipping_option_id"], self._flat_option_id())
			self.assertEqual(cart["shipping_methods"][0]["amount"], SHIPPING_FLAT_RATE_AMOUNT)
			# The grand total still carries the charge exactly once.
			self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])
			rows = self._quotation_of(cart_id).get("taxes", filters={"charge_type": "Actual"})
			self.assertEqual(len(rows), 1)

	def test_switching_the_supplied_id_form_switches_the_echo(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			applied = self._apply(cart_id, self._flat_option_id())
			self.assertEqual(
				applied.get_json()["cart"]["shipping_methods"][0]["shipping_option_id"],
				self._flat_option_id(),
			)

			# The legacy raw name replaces the opaque id and the echo
			# follows the last supplied id form.
			replaced = self._apply(cart_id, self.masters.country_rate_rule)
			self.assertEqual(replaced.status_code, 200)
			cart = replaced.get_json()["cart"]
			self.assertEqual(len(cart["shipping_methods"]), 1)
			self.assertEqual(
				cart["shipping_methods"][0]["shipping_option_id"], self.masters.country_rate_rule
			)
			self.assertEqual(cart["shipping_methods"][0]["amount"], SHIPPING_COUNTRY_RATE_AMOUNT)

	def test_malformed_foreign_and_unknown_tokens_are_invalid_data(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			for option_id in (
				"so_",
				"so_###",
				encode_option_id("ups", self.masters.flat_rate_rule),
				encode_option_id(PROVIDER_ID, "Ceto Missing Rule"),
			):
				with self.subTest(option_id=option_id):
					response = self._apply(cart_id, option_id)
					self.assertEqual(response.status_code, 400)
					body = response.get_json()
					self.assertEqual(body["type"], "invalid_data")
					self.assertEqual(body["message"], UNKNOWN_OPTION)

			# Every rejection left the cart untouched.
			cart = self._dispatch(
				"GET", f"/ceto/store/carts/{cart_id}?fields=shipping_methods,shipping_total"
			).get_json()["cart"]
			self.assertEqual(cart["shipping_methods"], [])
			self.assertEqual(cart["shipping_total"], 0)
			self.assertIsNone(self._quotation_of(cart_id).shipping_rule)

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
