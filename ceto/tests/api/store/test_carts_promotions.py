"""Phase 4 promotions endpoints: apply and remove coupon codes.

Note: a failed request rolls back the currently uncommitted transaction
(same as a real failed HTTP request), so every subtest that expects an error
provisions a fresh cart instead of reusing earlier state.
"""

import json

import frappe
from frappe.utils import today
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.cart_test_data import ITEM_PRICE, CartTestData
from ceto.tests.utils import CetoTestSuite


class TestCartPromotionsAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.masters.disable_stale_promotion_rules()
		self.discount_code = self._make_coupon("APISAVE", 10.0)
		# Rejection/removal cases only require a distinct public code. Avoid a
		# second matching Pricing Rule before the cart's initial line is priced.
		self.other_code = f"APIOTHER{self.masters.suffix}"
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

	def _make_coupon(self, label: str, percentage: float) -> str:
		rule = frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": f"Ceto {label} {self.masters.suffix}",
				"apply_on": "Item Code",
				"items": [{"item_code": self.masters.item}],
				"coupon_code_based": 1,
				"selling": 1,
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": percentage,
				"company": self.masters.company,
				"for_price_list": self.masters.price_list,
				"currency": "USD",
				"priority": {"SAVE10": 1, "SAVE20": 2, "OLDE": 3, "MAXED": 4, "APISAVE": 1, "APIOTHER": 2}[
					label
				],
				"valid_from": today(),
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Coupon Code",
				"coupon_name": f"Ceto {label} {self.masters.suffix}",
				"coupon_code": f"{label}{self.masters.suffix}",
				"coupon_type": "Promotional",
				"pricing_rule": rule.name,
				"valid_from": today(),
			}
		).insert(ignore_permissions=True)
		return f"{label}{self.masters.suffix}"

	def _cart_with_line(self) -> str:
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

	def test_apply_and_remove_promotion(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()

			applied = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/promotions?fields=id,promotions,item_subtotal",
				{"promo_codes": [self.discount_code]},
			)
			self.assertEqual(applied.status_code, 200)
			cart = applied.get_json()["cart"]
			self.assertEqual([promotion["code"] for promotion in cart["promotions"]], [self.discount_code])
			self.assertAlmostEqual(cart["item_subtotal"], ITEM_PRICE * 0.9)

			removed = self._dispatch(
				"DELETE",
				f"/ceto/store/carts/{cart_id}/promotions?fields=id,promotions,item_subtotal",
				{"promo_codes": [self.discount_code]},
			)
			self.assertEqual(removed.status_code, 200)
			cart = removed.get_json()["cart"]
			self.assertEqual(cart["promotions"], [])
			self.assertAlmostEqual(cart["item_subtotal"], ITEM_PRICE)

	def test_unknown_code_is_invalid_data(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch(
				"POST", f"/ceto/store/carts/{cart_id}/promotions", {"promo_codes": ["NOPE"]}
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_multiple_distinct_codes_are_rejected_without_mutation(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/promotions",
				{"promo_codes": [self.discount_code, self.other_code]},
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

			cart = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=promotions").get_json()["cart"]
			self.assertEqual(cart["promotions"], [])

	def test_remove_from_cart_without_promotions_is_a_no_op(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			response = self._dispatch(
				"DELETE", f"/ceto/store/carts/{cart_id}/promotions", {"promo_codes": [self.other_code]}
			)
			self.assertEqual(response.status_code, 200)
			self.assertEqual(response.get_json()["cart"]["promotions"], [])

	def test_requires_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"POST",
				"/ceto/store/carts/promotions-x/promotions",
				{"promo_codes": ["X"]},
				publishable_key=None,
			)
			self.assertEqual(response.status_code, 401)

	def test_wrong_scoped_key_cannot_mutate_promotions(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests
			for method, payload in (
				("POST", {"promo_codes": [self.discount_code]}),
				("DELETE", {"promo_codes": [self.discount_code]}),
			):
				response = self._dispatch(
					method, f"/ceto/store/carts/{cart_id}/promotions", payload, publishable_key="pk_other"
				)
				self.assertEqual(response.status_code, 403)
			cart = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=promotions").get_json()["cart"]
			self.assertEqual(cart["promotions"], [])

	def test_promo_codes_on_create_and_update(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			created = self._dispatch(
				"POST",
				"/ceto/store/carts?fields=id,promotions",
				{"promo_codes": [self.discount_code]},
			)
			self.assertEqual(created.status_code, 200)
			self.assertEqual(
				[promotion["code"] for promotion in created.get_json()["cart"]["promotions"]],
				[self.discount_code],
			)
			cart_id = created.get_json()["cart"]["id"]

			updated = self._dispatch(
				"POST", f"/ceto/store/carts/{cart_id}?fields=id,promotions", {"promo_codes": []}
			)
			self.assertEqual(updated.status_code, 200)
			self.assertEqual(updated.get_json()["cart"]["promotions"], [])

	def test_invalid_payloads_are_rejected(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._cart_with_line()
			for payload in ({}, {"promo_codes": []}, {"promo_codes": [""]}, {"promo_codes": "SAVE10"}):
				with self.subTest(payload=payload):
					response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/promotions", payload)
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
