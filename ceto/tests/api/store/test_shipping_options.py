"""Phase 4 shipping-options endpoints: the Medusa shipping-option surface.

Pins the HTTP boundary of ``GET /store/shipping-options`` and
``POST /store/shipping-options/{id}/calculate`` on the test site: the
pinned envelopes, the guest-dispatchable publishable-key policy with the
cart key's region / sales-channel scope, the strict query/body validation
and the masked ``404 not_found`` of the whole option space.

Note: a failed request rolls back the currently uncommitted transaction
(same as a real failed HTTP request), so every subtest that expects an
error commits its cart first (or asserts nothing after) instead of reusing
an earlier uncommitted cart.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.services.shipping.ids import encode_option_id
from ceto.services.shipping.providers.erpnext import PROVIDER_ID
from ceto.tests.data.cart_test_data import (
	SHIPPING_DISABLED_RATE_LABEL,
	SHIPPING_FLAT_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_LABEL,
	CartTestData,
)
from ceto.tests.utils import CetoTestSuite


def overridden_list(**_kwargs):
	return {"source": "override"}


def overridden_calculate(**_kwargs):
	return {"source": "override"}


class TestShippingOptionsAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# An earlier test's committed cart (kept to survive a request rollback)
		# leaves its guest-linked temporary Address behind; ERPNext would refill
		# this module's addressless carts from it as the guest party default.
		self.masters.discard_committed_cart_temporaries()
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

	def _cart_with_line(self, **create_kwargs) -> str:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
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

	def _flat_option_id(self) -> str:
		return encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule)

	def test_list_serves_the_cart_options(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch("GET", f"/ceto/store/shipping-options?cart_id={cart_id}")

			self.assertEqual(response.status_code, 200)
			body = response.get_json()
			self.assertEqual(set(body), {"shipping_options"})
			flat = next(
				option for option in body["shipping_options"] if option["name"] == SHIPPING_FLAT_RATE_LABEL
			)
			self.assertEqual(flat["id"], self._flat_option_id())
			self.assertEqual(flat["price_type"], "flat")
			self.assertEqual(flat["provider"], {"id": PROVIDER_ID, "is_enabled": True})
			self.assertEqual(flat["amount"], SHIPPING_FLAT_RATE_AMOUNT)
			self.assertFalse(flat["is_tax_inclusive"])
			self.assertEqual(flat["calculated_price"]["calculated_amount"], SHIPPING_FLAT_RATE_AMOUNT)
			self.assertEqual(flat["calculated_price"]["original_amount"], SHIPPING_FLAT_RATE_AMOUNT)
			self.assertFalse(flat["calculated_price"]["is_calculated_price_tax_inclusive"])
			self.assertIsNone(flat["data"])
			self.assertIsNone(flat["metadata"])
			# The disabled fixture never serves.
			self.assertNotIn(
				SHIPPING_DISABLED_RATE_LABEL, [option["name"] for option in body["shipping_options"]]
			)

	def test_is_return_serves_the_empty_list(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch("GET", f"/ceto/store/shipping-options?cart_id={cart_id}&is_return=true")

			self.assertEqual(response.status_code, 200)
			self.assertEqual(response.get_json(), {"shipping_options": []})

	def test_list_validates_the_query_strictly(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			for query in (
				"",
				"cart_id=",
				f"cart_id={cart_id}&limit=10",
				f"cart_id={cart_id}&offset=5",
				f"cart_id={cart_id}&fields=id,*service_zone",
				f"cart_id={cart_id}&order=name",
				f"cart_id={cart_id}&region_id=reg_test",
				f"cart_id={cart_id}&$or[0][cart_id]={cart_id}",
				f"cart_id={cart_id}&is_return=maybe",
				f"cart_id={cart_id}&unknown=1",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/shipping-options?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_list_requires_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"GET", "/ceto/store/shipping-options?cart_id=cart_1", publishable_key=None
			)
			self.assertEqual(response.status_code, 401)
			self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_list_refuses_a_wrong_scoped_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch(
				"GET", f"/ceto/store/shipping-options?cart_id={cart_id}", publishable_key="pk_other"
			)
			self.assertEqual(response.status_code, 403)
			self.assertEqual(response.get_json()["type"], "not_allowed")

	def test_an_unknown_cart_is_not_found(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", "/ceto/store/shipping-options?cart_id=cart_missing")
			self.assertEqual(response.status_code, 404)
			self.assertEqual(response.get_json()["type"], "not_found")

	def test_calculate_serves_the_option(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch(
				"POST",
				f"/ceto/store/shipping-options/{self._flat_option_id()}/calculate",
				{"cart_id": cart_id},
			)

			self.assertEqual(response.status_code, 200)
			body = response.get_json()
			self.assertEqual(set(body), {"shipping_option"})
			listed = self._dispatch("GET", f"/ceto/store/shipping-options?cart_id={cart_id}").get_json()
			flat = next(
				option for option in listed["shipping_options"] if option["name"] == SHIPPING_FLAT_RATE_LABEL
			)
			self.assertEqual(body["shipping_option"], flat)

	def test_calculate_provider_data_is_accepted_but_never_persisted(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch(
				"POST",
				f"/ceto/store/shipping-options/{self._flat_option_id()}/calculate",
				{"cart_id": cart_id, "data": {"parcels": 2}},
			)
			self.assertEqual(response.status_code, 200)

			# No compatibility field exists, so nothing about the request
			# payload is stored: not cart metadata, not Quotation state.
			self.assertIsNone(response.get_json()["shipping_option"]["data"])
			cart = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=metadata").get_json()
			self.assertIsNone(cart["cart"]["metadata"])

	def test_calculate_validates_the_body_and_query_strictly(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			option_id = self._flat_option_id()
			for payload in ({}, {"cart_id": ""}, {"cart_id": cart_id, "option_id": "x"}, {"id": "x"}):
				with self.subTest(payload=payload):
					response = self._dispatch(
						"POST", f"/ceto/store/shipping-options/{option_id}/calculate", payload
					)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

			# The calculate query accepts nothing: any query-only key rides
			# into the body contract through the merged arguments and is
			# refused there (a key the body also carries resolves to the
			# body's value, the shared merge semantics of every POST route).
			for query in ("fields=id", "is_return=true"):
				with self.subTest(query=query):
					response = self._dispatch(
						"POST",
						f"/ceto/store/shipping-options/{option_id}/calculate?{query}",
						{"cart_id": cart_id},
					)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_calculate_masks_unknown_and_malformed_options(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			for option_id in (
				encode_option_id("nobody", "key"),
				self.masters.flat_rate_rule,  # the legacy raw rule name
				"garbage",
			):
				with self.subTest(option_id=option_id):
					response = self._dispatch(
						"POST", f"/ceto/store/shipping-options/{option_id}/calculate", {"cart_id": cart_id}
					)
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")

	def test_calculate_masks_an_unknown_cart(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"POST",
				f"/ceto/store/shipping-options/{self._flat_option_id()}/calculate",
				{"cart_id": "cart_missing"},
			)
			self.assertEqual(response.status_code, 404)
			self.assertEqual(response.get_json()["type"], "not_found")

	def test_calculate_masks_an_ineligible_option(self) -> None:
		# The country-rate rule only accepts the bootstrap country; a cart
		# shipped elsewhere is never served it, on the list or by id.
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			# The commit below persists the cart's India temporary Address; it
			# must not outlive this test as the shared guest Customer's default.
			self.addCleanup(self.masters.discard_committed_cart_temporaries)
			cart_id = self._cart_with_line(
				shipping_address={"country_code": "IN", "address_1": "1 Main Rd", "city": "Mumbai"}
			)
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			country_id = encode_option_id(PROVIDER_ID, self.masters.country_rate_rule)

			response = self._dispatch(
				"POST", f"/ceto/store/shipping-options/{country_id}/calculate", {"cart_id": cart_id}
			)
			self.assertEqual(response.status_code, 404)
			self.assertEqual(response.get_json()["type"], "not_found")

			listed = self._dispatch("GET", f"/ceto/store/shipping-options?cart_id={cart_id}").get_json()
			self.assertNotIn(
				self.masters.country_rate_rule, [option["id"] for option in listed["shipping_options"]]
			)

	def test_endpoints_are_not_whitelisted(self) -> None:
		from ceto.api.store.shipping_options import (
			calculate_shipping_option_price,
			list_shipping_options,
		)

		for endpoint in (list_shipping_options, calculate_shipping_option_price):
			with self.subTest(endpoint=endpoint.__name__):
				self.assertNotIn(endpoint, frappe.whitelisted)
				self.assertFalse(hasattr(endpoint, "is_whitelisted"))

	def test_route_override_serves_the_registered_keys(self) -> None:
		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			self.patch_hooks(
				{
					"ceto_route_overrides": {
						"GET /ceto/store/shipping-options": [
							"ceto.tests.api.store.test_shipping_options.overridden_list"
						],
						"POST /ceto/store/shipping-options/{id}/calculate": [
							"ceto.tests.api.store.test_shipping_options.overridden_calculate"
						],
					}
				}
			),
		):
			response = self._dispatch("GET", "/ceto/store/shipping-options?cart_id=cart_1")
			self.assertEqual(response.status_code, 200)
			self.assertEqual(response.get_json(), {"source": "override"})

			response = self._dispatch(
				"POST", "/ceto/store/shipping-options/so_x/calculate", {"cart_id": "cart_1"}
			)
			self.assertEqual(response.status_code, 200)
			self.assertEqual(response.get_json(), {"source": "override"})

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
