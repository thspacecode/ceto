"""Phase 1 Store Customer endpoints: create and retrieve.

Pins the HTTP boundary on the test site: the pinned ``StoreCustomerResponse``
shape and ``fields`` selector, the publishable-key policy (boundary validation
only), the registration-token contract (purpose-bound, provider-checked,
consumed only after a fully successful create) and the auth separation (only
``auth``-purpose tokens or a Frappe session retrieve ``/me``). Error subtests
rely on the router rolling the open transaction back, like the cart suites; an
identity a retry must find is committed first.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import frappe
import jwt
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.api.store.customers import create_customer, retrieve_customer
from ceto.routing import ceto_router
from ceto.services.auth.tokens import (
	authenticate_bearer_token,
	create_customer_password_reset_token,
	create_customer_registration_token,
	create_customer_token,
	get_bearer_registration_subject,
)
from ceto.services.customers.creation import create_customer_profile
from ceto.tests.data.customer_test_data import (
	THROTTLE_USER_LIMIT,
	link_customer,
	make_chain,
	make_customer,
	new_identity,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.customers import StoreCustomer

TEST_SECRET = "a-test-only-signing-secret-that-is-at-least-32-bytes"
PUBLISHABLE_KEYS = {"pk_test": {}}


class CustomerAPITestBase(CetoTestSuite):
	"""Shared boundary fixtures: the storefront key store and a lifted throttle."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self._previous_conf = frappe.conf.get("ceto_cart")
		frappe.conf["ceto_cart"] = {"publishable_keys": PUBLISHABLE_KEYS}
		# User-creating tests lift Frappe's per-minute throttle on the shared
		# test site; tearDown restores both values.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = THROTTLE_USER_LIMIT

	def tearDown(self) -> None:
		if self._previous_conf is None:
			frappe.conf.pop("ceto_cart", None)
		else:
			frappe.conf["ceto_cart"] = self._previous_conf
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _identity(self, label: str) -> str:
		# The router rolls the open transaction back on every error response,
		# so identities under test are committed first — mirroring the cart
		# suites, which commit their masters before error subtests.
		email = new_identity(label)
		frappe.db.commit()  # nosemgrep
		return email

	def _chain(self, label: str) -> tuple[str, str, str]:
		chain = make_chain(label)
		frappe.db.commit()  # nosemgrep
		return chain

	def _dispatch(
		self,
		method: str,
		path: str,
		payload: dict | None = None,
		*,
		token: str | None = None,
		publishable_key: str | None = "pk_test",
	):
		request = self._request(method, path, payload, token=token, publishable_key=publishable_key)
		with self.set_request(request):
			return ceto_router.dispatch(request)

	def _dispatch_with_hook(self, method: str, path: str, *, token: str):
		"""Dispatch like production: the auth hook runs before the router.

		``auth_hooks`` authenticates ``auth``-purpose bearer requests by
		setting the session user; non-auth-purpose tokens leave the request as
		Guest, which the router refuses.
		"""
		request = self._request(method, path, None, token=token)
		with self.set_request(request), self.set_user("Guest"):
			authenticate_bearer_token()
			return ceto_router.dispatch(request)

	@staticmethod
	def _request(
		method: str,
		path: str,
		payload: dict | None = None,
		*,
		token: str | None = None,
		publishable_key: str | None = "pk_test",
	) -> Request:
		headers = {}
		if publishable_key:
			headers["x-publishable-api-key"] = publishable_key
		if token:
			headers["Authorization"] = f"Bearer {token}"
		return Request(
			EnvironBuilder(
				path=path,
				method=method,
				data=json.dumps(payload) if payload is not None else None,
				content_type="application/json" if payload is not None else None,
				headers=headers or None,
				environ_base={"REMOTE_ADDR": "127.0.0.1"},
			).get_environ()
		)

	@staticmethod
	def _create_payload() -> dict:
		return {
			"first_name": "Aria",
			"last_name": "Stone",
			"company_name": "Harbor Co.",
			"phone": "+1 555 0100",
			"metadata": {"loyalty_tier": "gold"},
		}

	def _assert_no_profile(self, email: str) -> None:
		"""No reference and no Customer link may exist for the identity."""
		contact = frappe.db.get_value("Contact", {"user": email})
		linked = (
			frappe.get_all(
				"Dynamic Link",
				filters={"parenttype": "Contact", "parent": contact, "link_doctype": "Customer"},
				pluck="link_name",
			)
			if contact
			else []
		)
		self.assertEqual(frappe.db.count("Ceto Customer Reference", {"user": email}), 0)
		self.assertEqual(linked, [])


class TestCustomerCreateAPI(CustomerAPITestBase):
	def test_endpoints_are_not_whitelisted(self):
		for endpoint in (create_customer, retrieve_customer):
			self.assertNotIn(endpoint, frappe.whitelisted)
			self.assertFalse(hasattr(endpoint, "is_whitelisted"))

	def test_create_returns_the_pinned_customer(self):
		email = self._identity("create")
		token = create_customer_registration_token(email, "emailpass")

		response = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(response.get_json()), {"customer"})
		customer = response.get_json()["customer"]
		self.assertEqual(set(customer), set(StoreCustomer.model_fields))
		self.assertRegex(customer["id"], r"^cus_[0-9a-f]{32}$")
		self.assertEqual(customer["email"], email)
		self.assertEqual(customer["first_name"], "Aria")
		self.assertEqual(customer["last_name"], "Stone")
		self.assertEqual(customer["company_name"], "Harbor Co.")
		self.assertEqual(customer["phone"], "+1 555 0100")
		self.assertEqual(customer["metadata"], {"loyalty_tier": "gold"})
		self.assertEqual(customer["addresses"], [])

	def test_create_defaults_the_email_to_the_token_subject(self):
		email = self._identity("fallback")
		token = create_customer_registration_token(email, "emailpass")

		response = self._dispatch("POST", "/ceto/store/customers", {"first_name": "Aria"}, token=token)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_json()["customer"]["email"], email)

	def test_create_honours_the_fields_selector(self):
		email = self._identity("fields")
		token = create_customer_registration_token(email, "emailpass")

		response = self._dispatch(
			"POST", "/ceto/store/customers?fields=id,email", self._create_payload(), token=token
		)

		self.assertEqual(response.status_code, 200)
		body = response.get_json()["customer"]
		self.assertEqual(set(body), {"id", "email"})
		self.assertEqual(body["email"], email)

	def test_unknown_field_failure_rolls_back_and_keeps_the_token(self):
		# The selector is applied before the token is consumed: the 400 rolls
		# the profile back and the same token completes the registration.
		email = self._identity("badfields")
		token = create_customer_registration_token(email, "emailpass")

		response = self._dispatch(
			"POST", "/ceto/store/customers?fields=not_a_field", self._create_payload(), token=token
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")
		self.assertFalse(frappe.db.count("Ceto Customer Reference", {"user": email}))

		retried = self._dispatch(
			"POST", "/ceto/store/customers?fields=id", self._create_payload(), token=token
		)
		self.assertEqual(retried.status_code, 200)
		self.assertEqual(set(retried.get_json()["customer"]), {"id"})

	def test_create_rejects_a_disagreeing_email_without_consuming(self):
		email = self._identity("mismatch")
		token = create_customer_registration_token(email, "emailpass")

		response = self._dispatch(
			"POST",
			"/ceto/store/customers",
			{**self._create_payload(), "email": "other@example.com"},
			token=token,
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")
		self._assert_no_profile(email)

		retried = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)
		self.assertEqual(retried.status_code, 200)

	def test_create_requires_a_configured_publishable_key(self):
		email = self._identity("nokey")
		token = create_customer_registration_token(email, "emailpass")
		for publishable_key in (None, "pk_unknown"):
			with self.subTest(publishable_key=publishable_key):
				response = self._dispatch(
					"POST",
					"/ceto/store/customers",
					self._create_payload(),
					token=token,
					publishable_key=publishable_key,
				)
				self.assertEqual(response.status_code, 401)
				self.assertEqual(response.get_json()["type"], "unauthorized")
				self._assert_no_profile(email)

	def test_registration_bearer_is_required_and_purpose_bound(self):
		email = self._identity("purpose")
		for label, token in (
			("missing", None),
			("opaque", "opaque-value"),
			("auth purpose", create_customer_token(email)),
			("password reset", create_customer_password_reset_token(email, "emailpass")),
		):
			with self.subTest(bearer=label):
				response = self._dispatch(
					"POST", "/ceto/store/customers", self._create_payload(), token=token
				)
				self.assertEqual(response.status_code, 401)
				self.assertEqual(response.get_json()["type"], "unauthorized")
				self._assert_no_profile(email)

	def test_expired_registration_token_is_refused(self):
		email = self._identity("expired")
		issued_at = datetime.now(UTC) - timedelta(hours=2)
		expired = jwt.encode(
			{
				"sub": email,
				"actor_type": "customer",
				"purpose": "registration",
				"provider": "emailpass",
				"iss": "ceto",
				"iat": issued_at,
				"exp": issued_at + timedelta(hours=1),
				"jti": "expired-registration-api-jti",
			},
			TEST_SECRET,
			algorithm="HS256",
		)
		with self.set_conf(ceto_jwt_secret=TEST_SECRET):
			response = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=expired)

		self.assertEqual(response.status_code, 401)
		self._assert_no_profile(email)

	def test_wrong_provider_registration_token_is_refused(self):
		email = self._identity("provider")
		# The test site ships Google disabled, and an unknown provider string
		# is never available: both tokens carry a valid registration purpose
		# but name no enabled customer auth provider.
		for provider in ("google", "ghost-provider"):
			with self.subTest(provider=provider):
				token = create_customer_registration_token(email, provider)
				response = self._dispatch(
					"POST", "/ceto/store/customers", self._create_payload(), token=token
				)
				self.assertEqual(response.status_code, 401)
				self._assert_no_profile(email)

	def test_replayed_token_is_refused_and_binds_nothing(self):
		email = self._identity("replay")
		token = create_customer_registration_token(email, "emailpass")
		first = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)
		self.assertEqual(first.status_code, 200)
		# The replay arrives as its own request in production: commit the
		# successful create so the replay's rollback cannot wipe it.
		frappe.db.commit()  # nosemgrep

		replay = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)

		self.assertEqual(replay.status_code, 401)
		self.assertEqual(replay.get_json()["type"], "unauthorized")
		self.assertEqual(frappe.db.count("Ceto Customer Reference", {"user": email}), 1)

	def test_preowned_identity_is_refused_and_keeps_the_token(self):
		# A pre-existing ERPNext chain (no Ceto reference) can never be minted
		# a parallel profile, and the check writes nothing.
		email, _customer, _contact = self._chain("preowned")
		token = create_customer_registration_token(email, "emailpass")

		response = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)

		self.assertEqual(response.status_code, 401)
		self.assertFalse(frappe.db.count("Ceto Customer Reference", {"user": email}))

	def test_disabled_identity_is_refused_and_retryable(self):
		email = self._identity("disabled")
		token = create_customer_registration_token(email, "emailpass")
		frappe.db.set_value("User", email, "enabled", 0)
		frappe.db.commit()  # nosemgrep

		response = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)

		self.assertEqual(response.status_code, 401)
		self._assert_no_profile(email)

		frappe.db.set_value("User", email, "enabled", 1)
		retried = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)
		self.assertEqual(retried.status_code, 200)

	def test_ambiguous_identity_is_refused_and_retryable(self):
		email = self._identity("ambiguous")
		second_contact = frappe.get_doc({"doctype": "Contact", "first_name": "Second", "user": email})
		second_contact.insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep
		token = create_customer_registration_token(email, "emailpass")

		response = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)

		self.assertEqual(response.status_code, 401)
		self._assert_no_profile(email)

		frappe.delete_doc("Contact", second_contact.name, force=True)
		retried = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)
		self.assertEqual(retried.status_code, 200)

	def test_internal_failure_rolls_back_and_keeps_the_token(self):
		# The router rolls the request back when converting the error; the
		# committed identity (_identity commits) survives and the token
		# (cache state) is untouched.
		email = self._identity("rollback")
		token = create_customer_registration_token(email, "emailpass")

		with patch(
			"ceto.services.customers.creation.mint_customer_id",
			side_effect=RuntimeError("boom"),
		):
			response = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)

		self.assertEqual(response.status_code, 500)
		self.assertEqual(response.get_json()["type"], "internal_error")
		self.assertTrue(frappe.db.exists("User", email))
		self._assert_no_profile(email)

		retried = self._dispatch("POST", "/ceto/store/customers", self._create_payload(), token=token)
		self.assertEqual(retried.status_code, 200)
		self.assertEqual(retried.get_json()["customer"]["email"], email)

	def test_checked_token_stays_unconsumed_after_a_refusal(self):
		# The service-level check is exactly what the boundary ran: still
		# resolvable after every refusal above burned nothing.
		email = self._identity("unconsumed")
		token = create_customer_registration_token(email, "emailpass")
		refused = self._dispatch(
			"POST",
			"/ceto/store/customers",
			{**self._create_payload(), "email": "other@example.com"},
			token=token,
		)
		self.assertEqual(refused.status_code, 400)

		request = self._request("POST", "/ceto/store/customers", token=token)
		with self.set_request(request):
			self.assertEqual(get_bearer_registration_subject(), email)


class TestCustomerRetrieveAPI(CustomerAPITestBase):
	def test_retrieve_by_session_returns_the_pinned_customer(self):
		email, reference = self._profile("session")

		with self.set_user(email):
			response = self._dispatch("GET", "/ceto/store/customers/me")

		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(response.get_json()), {"customer"})
		customer = response.get_json()["customer"]
		self.assertEqual(set(customer), set(StoreCustomer.model_fields))
		self.assertEqual(customer["id"], reference)
		self.assertEqual(customer["email"], email)
		self.assertEqual(customer["first_name"], "Aria")
		self.assertEqual(customer["addresses"], [])

	def test_retrieve_by_session_honours_the_fields_selector(self):
		email, reference = self._profile("fields")

		with self.set_user(email):
			fields = self._dispatch("GET", "/ceto/store/customers/me?fields=id,email")
			unknown = self._dispatch("GET", "/ceto/store/customers/me?fields=not_a_field")
			rejected = self._dispatch("GET", "/ceto/store/customers/me?limit=5")

		self.assertEqual(fields.status_code, 200)
		self.assertEqual(fields.get_json()["customer"], {"id": reference, "email": email})
		self.assertEqual(unknown.status_code, 400)
		self.assertEqual(unknown.get_json()["type"], "invalid_data")
		self.assertEqual(rejected.status_code, 400)
		self.assertEqual(rejected.get_json()["type"], "invalid_data")

	def test_retrieve_by_bearer_token(self):
		email, reference = self._profile("bearer")
		token = create_customer_token(email)

		response = self._dispatch_with_hook("GET", "/ceto/store/customers/me", token=token)

		self.assertEqual(response.status_code, 200)
		customer = response.get_json()["customer"]
		self.assertEqual(customer["id"], reference)
		self.assertEqual(customer["email"], email)

	def test_retrieve_requires_authentication(self):
		self._profile("guest")

		with self.set_user("Guest"):
			response = self._dispatch("GET", "/ceto/store/customers/me")

		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_retrieve_requires_a_configured_publishable_key(self):
		email, _reference = self._profile("nokey")

		with self.set_user(email):
			response = self._dispatch("GET", "/ceto/store/customers/me", publishable_key=None)

		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_retrieve_masks_unresolvable_identities(self):
		registered = self._identity("mask-registered")
		chain, _chain_customer, _chain_contact = self._chain("mask-chain")
		ambiguous, _ambiguous_customer, _ambiguous_contact = self._chain("mask-ambiguous")
		link_customer(ambiguous, make_customer("mask-second"))
		disabled, _disabled_customer, _disabled_contact = self._chain("mask-disabled")
		frappe.db.set_value("User", disabled, "enabled", 0)
		# Every 401 response rolls the open transaction back; commit the four
		# states so each subtest refuses against persistent data.
		frappe.db.commit()  # nosemgrep
		for session_user in (registered, chain, ambiguous, disabled, "nobody@example.com"):
			with self.subTest(session_user=session_user):
				with self.set_user(session_user):
					response = self._dispatch("GET", "/ceto/store/customers/me")
				self.assertEqual(response.status_code, 401)
				self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_non_auth_purpose_tokens_never_authenticate_retrieval(self):
		email, _reference = self._profile("separation")
		for label, token in (
			("registration", create_customer_registration_token(email, "emailpass")),
			("password reset", create_customer_password_reset_token(email, "emailpass")),
		):
			with self.subTest(purpose=label):
				response = self._dispatch_with_hook("GET", "/ceto/store/customers/me", token=token)
				self.assertEqual(response.status_code, 401)
				self.assertEqual(response.get_json()["type"], "unauthorized")

	def _profile(self, label: str) -> tuple[str, str]:
		email = self._identity(label)
		_identity, reference = create_customer_profile(email, first_name="Aria", last_name="Stone")
		return email, reference.name
