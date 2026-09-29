import json
import uuid

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite


class TestCartAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"}},
		}

	def test_guest_create_retrieve_and_update(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			created = self._dispatch(
				"POST",
				"/ceto/store/carts?fields=id,email,currency_code",
				{"email": "guest@example.com"},
			)
			self.assertEqual(created.status_code, 200)
			created_cart = created.get_json()["cart"]
			self.assertEqual(set(created_cart), {"id", "email", "currency_code"})
			cart_id = created_cart["id"]

			retrieved = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,email")
			self.assertEqual(retrieved.status_code, 200)
			self.assertEqual(retrieved.get_json()["cart"]["email"], "guest@example.com")

			updated = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}?fields=id,email,metadata",
				{"email": "new@example.com", "metadata": {"campaign": "fall"}},
			)
			self.assertEqual(updated.status_code, 200)
			self.assertEqual(
				updated.get_json()["cart"],
				{
					"id": cart_id,
					"email": "new@example.com",
					"metadata": {"campaign": "fall"},
				},
			)

	def test_invalid_payload_uses_medusa_error_shape(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("POST", "/ceto/store/carts", {"unknown": True})
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_requires_a_configured_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("POST", "/ceto/store/carts", {}, publishable_key=None)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

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


class TestCartLineItemAPI(CetoTestSuite):
	"""Phase 2 line-item endpoints: add, update and delete line items.

	Note: a failed request rolls back the currently uncommitted transaction
	(same as a real failed HTTP request), so every subtest that expects an
	error provisions a fresh cart instead of reusing earlier state.
	"""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
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

	def _create_cart(self) -> str:
		created = self._dispatch("POST", "/ceto/store/carts?fields=id", {})
		self.assertEqual(created.status_code, 200)
		return created.get_json()["cart"]["id"]

	def _add_line(self, cart_id: str, quantity: int = 2) -> str:
		response = self._dispatch(
			"POST",
			f"/ceto/store/carts/{cart_id}/line-items?fields=id,items",
			{"variant_id": self.masters.item, "quantity": quantity},
		)
		self.assertEqual(response.status_code, 200)
		return response.get_json()["cart"]["items"][-1]["id"]

	def test_guest_add_update_and_delete_lifecycle(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._create_cart()
			line_id = self._add_line(cart_id, quantity=1)

			updated = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items/{line_id}?fields=id,items",
				{"quantity": 3},
			)
			self.assertEqual(updated.status_code, 200)
			cart = updated.get_json()["cart"]
			self.assertEqual([item["id"] for item in cart["items"]], [line_id])
			self.assertEqual(cart["items"][0]["quantity"], 3)

			deleted = self._dispatch("DELETE", f"/ceto/store/carts/{cart_id}/line-items/{line_id}")
			self.assertEqual(deleted.status_code, 200)
			self.assertEqual(
				deleted.get_json(),
				{"id": line_id, "object": "line-item", "deleted": True, "parent": cart_id},
			)

	def test_add_response_wraps_exactly_cart_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._create_cart()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items",
				{"variant_id": self.masters.item, "quantity": 1, "metadata": {"gift": True}},
			)
			self.assertEqual(response.status_code, 200)
			body = response.get_json()
			self.assertEqual(set(body), {"cart"})
			item = body["cart"]["items"][-1]
			self.assertEqual(item["variant_id"], self.masters.item)
			self.assertEqual(item["quantity"], 1)
			self.assertEqual(item["metadata"], {"gift": True})
			self.assertRegex(item["id"], r"^li_[0-9a-f]{32}$")

	def test_fields_query_is_honoured_on_line_mutations(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._create_cart()
			line_id = self._add_line(cart_id)

			added = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items?fields=id",
				{"variant_id": self.masters.other_item, "quantity": 2},
			)
			self.assertEqual(added.status_code, 200)
			self.assertEqual(added.get_json()["cart"], {"id": cart_id})

			updated = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items/{line_id}?fields=id",
				{"quantity": 2},
			)
			self.assertEqual(updated.status_code, 200)
			self.assertEqual(updated.get_json()["cart"], {"id": cart_id})

	def test_add_rejects_invalid_payloads(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for payload in (
				{"variant_id": self.masters.item, "quantity": 0},
				{"variant_id": self.masters.item, "quantity": -1},
				{"variant_id": "no-such-item", "quantity": 1},
				{"quantity": 1},
				{"variant_id": self.masters.item, "quantity": 1, "title": "x"},
			):
				with self.subTest(payload=payload):
					cart_id = self._create_cart()
					response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/line-items", payload)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_update_rejects_invalid_payloads(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for payload in ({"quantity": 0}, {"quantity": 2, "variant_id": "x"}):
				with self.subTest(payload=payload):
					cart_id = self._create_cart()
					line_id = self._add_line(cart_id)
					response = self._dispatch(
						"POST", f"/ceto/store/carts/{cart_id}/line-items/{line_id}", payload
					)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_disabled_variant_is_rejected(self) -> None:
		frappe.db.set_value("Item", self.masters.other_item, "disabled", 1)
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._create_cart()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items",
				{"variant_id": self.masters.other_item, "quantity": 1},
			)
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_unknown_and_foreign_lines_are_masked(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for case in ("unknown", "foreign"):
				for method, payload in (("POST", {"quantity": 1}), ("DELETE", None)):
					with self.subTest(case=case, method=method):
						cart_id = self._create_cart()
						line_id = (
							self._add_line(self._create_cart()) if case == "foreign" else "li_" + "0" * 32
						)
						response = self._dispatch(
							method, f"/ceto/store/carts/{cart_id}/line-items/{line_id}", payload
						)
						self.assertEqual(response.status_code, 404)
						self.assertEqual(response.get_json()["type"], "not_found")
						self.assertNotIn("cart", response.get_json())

	def test_wrong_scoped_publishable_key_causes_no_mutation(self) -> None:
		# The not_allowed response proves the guard rejected the request; the
		# service test with persistence patched out proves no save (mutation)
		# is ever attempted for a rejecting guard.
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for method, path, payload in (
				(
					"POST",
					"/ceto/store/carts/{cart_id}/line-items",
					{"variant_id": self.masters.item, "quantity": 5},
				),
				("POST", "/ceto/store/carts/{cart_id}/line-items/{line_id}", {"quantity": 9}),
				("DELETE", "/ceto/store/carts/{cart_id}/line-items/{line_id}", None),
				("POST", "/ceto/store/carts/{cart_id}", {"email": "attacker@example.com"}),
			):
				with self.subTest(method=method, path=path):
					cart_id = self._create_cart()
					line_id = self._add_line(cart_id, quantity=1)
					response = self._dispatch(
						method,
						path.format(cart_id=cart_id, line_id=line_id),
						payload,
						publishable_key="pk_other",
					)
					self.assertEqual(response.status_code, 403)
					self.assertEqual(response.get_json()["type"], "not_allowed")

	def test_delete_returns_exact_body_and_repeat_is_404(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = self._create_cart()
			line_id = self._add_line(cart_id)

			deleted = self._dispatch("DELETE", f"/ceto/store/carts/{cart_id}/line-items/{line_id}")
			self.assertEqual(deleted.status_code, 200)
			self.assertEqual(
				deleted.get_json(),
				{"id": line_id, "object": "line-item", "deleted": True, "parent": cart_id},
			)
			repeat = self._dispatch("DELETE", f"/ceto/store/carts/{cart_id}/line-items/{line_id}")
			self.assertEqual(repeat.status_code, 404)
			self.assertEqual(repeat.get_json()["type"], "not_found")

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


class TestCartCustomerClaimAPI(CetoTestSuite):
	"""Phase 3 claim endpoint: ``POST /store/carts/{id}/customer``.

	Error subtests rely on the router's rollback of the open transaction, so
	carts and masters are committed before the failing requests.
	"""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData.shared()
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"}},
		}
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _claiming_user(self, label: str) -> tuple[str, str]:
		# Unique per test: claimed carts commit, so parties created in earlier
		# tests survive and must not collide.
		email = f"ceto.api.claim.{label}.{uuid.uuid4().hex[:8]}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"Api {label}",
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Api Claimed {label} {uuid.uuid4().hex[:8]}",
				"customer_type": "Individual",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": "All Territories",
			}
		)
		customer.flags.ignore_permissions = True
		customer.insert()
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": f"Api {label}",
				"email_id": email,
				"user": email,
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		)
		contact.flags.ignore_permissions = True
		contact.insert()
		return email, customer.name

	def _create_cart_with_line(self, *, with_address: bool = False) -> str:
		payload = (
			{
				"shipping_address": {
					"first_name": "Aria",
					"last_name": "Stone",
					"phone": "+1 555 0100",
					"address_1": "1 Harbor Way",
					"city": "Portland",
					"province": "Oregon",
					"postal_code": "97201",
					"country_code": "us",
				}
			}
			if with_address
			else {}
		)
		created = self._dispatch("POST", "/ceto/store/carts?fields=id", payload)
		self.assertEqual(created.status_code, 200)
		cart_id = created.get_json()["cart"]["id"]
		added = self._dispatch(
			"POST",
			f"/ceto/store/carts/{cart_id}/line-items?fields=id",
			{"variant_id": self.masters.item, "quantity": 1},
		)
		self.assertEqual(added.status_code, 200)
		return cart_id

	def test_claim_transfers_guest_cart_to_customer(self) -> None:
		email, customer = self._claiming_user("buyer")
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user("Guest"):
				cart_id = self._create_cart_with_line(with_address=True)

			with self.set_user(email):
				response = self._dispatch(
					"POST",
					f"/ceto/store/carts/{cart_id}/customer?fields=id,customer_id,email,shipping_address",
					None,
				)
			self.assertEqual(response.status_code, 200)
			body = response.get_json()
			self.assertEqual(set(body), {"cart"})
			self.assertEqual(body["cart"]["customer_id"], customer)
			self.assertEqual(body["cart"]["email"], email)
			# The guest temporary became a customer-owned copy (Recorded
			# Decision 4): relinked, owned by the claiming customer, and no
			# longer reachable from the shared Guest Customer.
			shipping = body["cart"]["shipping_address"]
			self.assertEqual(shipping["customer_id"], customer)
			self.assertEqual(shipping["address_1"], "1 Harbor Way")

			with self.set_user("Guest"):
				# The guest session (possession of the id) no longer sees it.
				masked = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id")
				self.assertEqual(masked.status_code, 404)

	def test_repeat_claim_is_idempotent(self) -> None:
		email, customer = self._claiming_user("buyer")
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user("Guest"):
				cart_id = self._create_cart_with_line()
			with self.set_user(email):
				first = self._dispatch(
					"POST", f"/ceto/store/carts/{cart_id}/customer?fields=id,customer_id", None
				)
				second = self._dispatch(
					"POST", f"/ceto/store/carts/{cart_id}/customer?fields=id,customer_id", None
				)
			self.assertEqual(first.status_code, 200)
			self.assertEqual(second.status_code, 200)
			self.assertEqual(second.get_json()["cart"]["customer_id"], customer)

	def test_unauthenticated_claim_is_unauthorized(self) -> None:
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user("Guest"):
				cart_id = self._create_cart_with_line()
				response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/customer?fields=id", None)
			self.assertEqual(response.status_code, 401)
			self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_competing_owner_is_masked_as_not_found(self) -> None:
		owner_email, _ = self._claiming_user("owner")
		other_email, _ = self._claiming_user("other")
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user("Guest"):
				cart_id = self._create_cart_with_line()
			with self.set_user(owner_email):
				response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/customer", None)
				self.assertEqual(response.status_code, 200)
			with self.set_user(other_email):
				response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/customer", None)
				self.assertEqual(response.status_code, 404)
				self.assertEqual(response.get_json()["type"], "not_found")

	def test_wrong_scoped_key_is_not_allowed(self) -> None:
		email, _ = self._claiming_user("buyer")
		configuration = {
			**self.configuration,
			"publishable_keys": {
				"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"},
				"pk_other": {"region_id": "reg_other", "sales_channel_id": "sc_other"},
			},
		}
		with self.set_conf(ceto_cart=configuration):
			with self.set_user("Guest"):
				cart_id = self._create_cart_with_line()
			with self.set_user(email):
				response = self._dispatch(
					"POST", f"/ceto/store/carts/{cart_id}/customer", None, publishable_key="pk_other"
				)
			self.assertEqual(response.status_code, 403)
			self.assertEqual(response.get_json()["type"], "not_allowed")

	def test_no_partial_mutation_when_claim_fails_midway(self) -> None:
		from unittest.mock import patch

		email, _ = self._claiming_user("buyer")
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user("Guest"):
				cart_id = self._create_cart_with_line()
				frappe.db.commit()

			with (
				self.set_user(email),
				patch(
					"ceto.services.carts.claim.CartLineItems.save",
					side_effect=RuntimeError("boom"),
				),
			):
				response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/customer?fields=id", None)
			self.assertEqual(response.status_code, 500)
			self.assertEqual(response.get_json()["type"], "internal_error")

			with self.set_user("Guest"):
				# Rolled back: still an unclaimed guest cart with its line.
				after = self._dispatch(
					"GET", f"/ceto/store/carts/{cart_id}?fields=id,customer_id,email,items"
				)
			self.assertEqual(after.status_code, 200)
			cart = after.get_json()["cart"]
			self.assertIsNone(cart["customer_id"])
			self.assertEqual(cart["email"], None)
			self.assertEqual(len(cart["items"]), 1)

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
