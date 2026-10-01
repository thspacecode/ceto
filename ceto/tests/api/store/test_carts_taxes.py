"""Phase 4 cart-taxes endpoint: ``POST /store/carts/{id}/taxes``.

Note: a failed request rolls back the currently uncommitted transaction
(same as a real failed HTTP request), so every subtest that expects an error
and asserts state afterwards provisions a fresh cart and commits the
preceding state instead of reusing earlier uncommitted carts.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.cart_test_data import ITEM_PRICE, SHIPPING_FLAT_RATE_AMOUNT, TAX_RATE, CartTestData
from ceto.tests.utils import CetoTestSuite


class TestCartTaxesAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# The router rolls back the open transaction when converting an error
		# to a response (mirroring Frappe's commit-on-success). Error subtests
		# below therefore need the master data committed to survive that.
		frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {
				"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"},
				"pk_other": {"region_id": "reg_other", "sales_channel_id": "sc_other"},
			},
		}

	def _cart_with_line(self, *, publishable_key: str = "pk_test") -> str:
		created = self._dispatch("POST", "/ceto/store/carts?fields=id", {}, publishable_key=publishable_key)
		self.assertEqual(created.status_code, 200)
		cart_id = created.get_json()["cart"]["id"]
		added = self._dispatch(
			"POST",
			f"/ceto/store/carts/{cart_id}/line-items?fields=id",
			{"variant_id": self.masters.item, "quantity": 1},
			publishable_key=publishable_key,
		)
		self.assertEqual(added.status_code, 200)
		return cart_id

	def _quotation_of(self, cart_id: str):
		quotation = frappe.db.get_value("Ceto Cart Reference", {"cart_id": cart_id}, "quotation")
		return frappe.get_doc("Quotation", quotation)

	def test_calculate_with_empty_payload(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/taxes", {})
			self.assertEqual(response.status_code, 200)
			body = response.get_json()
			self.assertEqual(set(body), {"cart"})
			cart = body["cart"]
			self.assertEqual(cart["id"], cart_id)
			self.assertAlmostEqual(cart["tax_total"], TAX_RATE / 100 * ITEM_PRICE)
			self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])

	def test_extra_payload_fields_are_rejected(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"POST", "/ceto/store/carts/cart_missing/taxes", {"region_id": "reg_other"}
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_recalculate_is_idempotent(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			applied = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods",
				{"option_id": self.masters.flat_rate_rule},
			)
			self.assertEqual(applied.status_code, 200)

			carts = [
				self._dispatch("POST", f"/ceto/store/carts/{cart_id}/taxes", {}).get_json()["cart"]
				for _ in range(2)
			]

		for cart in carts:
			self.assertAlmostEqual(cart["tax_total"], TAX_RATE / 100 * ITEM_PRICE)
			self.assertAlmostEqual(cart["shipping_total"], SHIPPING_FLAT_RATE_AMOUNT)
			self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])
		self.assertEqual(carts[0]["total"], carts[1]["total"])
		self.assertEqual(carts[0]["subtotal"], carts[1]["subtotal"])
		# The repeated request never duplicates the shipping charge row.
		self.assertEqual(len(self._quotation_of(cart_id).get("taxes", filters={"charge_type": "Actual"})), 1)

	def test_requires_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"POST", "/ceto/store/carts/cart_missing/taxes", {}, publishable_key=None
			)
			self.assertEqual(response.status_code, 401)
			self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_wrong_scoped_key_is_not_allowed(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			response = self._dispatch(
				"POST", f"/ceto/store/carts/{cart_id}/taxes", {}, publishable_key="pk_other"
			)
			self.assertEqual(response.status_code, 403)
			self.assertEqual(response.get_json()["type"], "not_allowed")

			cart = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=tax_total,total").get_json()[
				"cart"
			]
			self.assertAlmostEqual(cart["tax_total"], TAX_RATE / 100 * ITEM_PRICE)
			self.assertAlmostEqual(cart["total"], ITEM_PRICE * (1 + TAX_RATE / 100))

	def test_unknown_cart_is_not_found(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("POST", "/ceto/store/carts/cart_missing/taxes", {})
			self.assertEqual(response.status_code, 404)
			self.assertEqual(response.get_json()["type"], "not_found")

	def test_fields_selection(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch(
				"POST", f"/ceto/store/carts/{cart_id}/taxes?fields=id,tax_total,total", {}
			)
			self.assertEqual(response.status_code, 200)
			self.assertEqual(set(response.get_json()["cart"]), {"id", "tax_total", "total"})

			response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/taxes?fields=id,not_a_field", {})
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_missing_template_region_is_invalid_data_and_rolls_back(self) -> None:
		configuration = {
			**self.masters.configuration,
			"regions": {"reg_test": {}, "reg_bad": {"taxes_and_charges": "Ceto Missing Template"}},
			"publishable_keys": {"pk_open": {}},
		}
		with self.set_conf(ceto_cart=configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line(publishable_key="pk_open")
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}",
				{"region_id": "reg_bad"},
				publishable_key="pk_open",
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

			# The failed configuration change rolled back: the cart keeps its
			# region, template and totals.
			cart = self._dispatch(
				"GET",
				f"/ceto/store/carts/{cart_id}?fields=region_id,tax_total,total",
				publishable_key="pk_open",
			).get_json()["cart"]
			self.assertEqual(cart["region_id"], "reg_test")
			self.assertAlmostEqual(cart["tax_total"], TAX_RATE / 100 * ITEM_PRICE)
			self.assertAlmostEqual(cart["total"], ITEM_PRICE * (1 + TAX_RATE / 100))

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
