"""Store Locale endpoint: the guest-dispatchable enabled-language list.

Pins the HTTP boundary on the test site: the pinned ``{locales}`` envelope
plus the labeled ``default_locale`` Ceto extension, the publishable-key
policy (required although the route is guest-dispatchable — upstream serves
it behind its ``translation`` feature flag, Ceto always serves it on its own
provisioning) and the unpaged query refusal: upstream pins no query contract,
so every key fails as ``400 invalid_data`` before the languages resolve.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.locales import StoreLocale

TEMP_LANGUAGE = "zz_apilocale"
FALLBACK_LOCALE = "en"


class TestLocaleAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self._insert_language(TEMP_LANGUAGE)
		# The router rolls the open transaction back on every error response,
		# so the fixture is committed first — mirroring the customer suites.
		frappe.db.commit()  # nosemgrep
		self.configuration = {"publishable_keys": {"pk_test": {}}}

	def test_list_is_guest_dispatchable(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", "/ceto/store/locales")
		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"locales", "default_locale"})
		codes = [locale["code"] for locale in body["locales"]]
		self.assertEqual(codes, sorted(codes))
		self.assertIn(FALLBACK_LOCALE, codes)
		for locale in body["locales"]:
			with self.subTest(locale=locale["code"]):
				self.assertEqual(set(locale), set(StoreLocale.model_fields))

	def test_requires_a_configured_publishable_key(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for publishable_key in (None, "pk_unknown"):
				with self.subTest(publishable_key=publishable_key):
					response = self._dispatch("GET", "/ceto/store/locales", publishable_key=publishable_key)
					self.assertEqual(response.status_code, 401)
					self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_lists_only_enabled_languages(self):
		with self.set_conf(ceto_cart=self.configuration):
			codes = self._served_codes()
			self.assertIn(TEMP_LANGUAGE, codes)
			frappe.db.set_value("Language", TEMP_LANGUAGE, "enabled", 0, update_modified=False)
			codes = self._served_codes()
		self.assertNotIn(TEMP_LANGUAGE, codes)

	def test_default_locale_is_deterministic(self):
		with self.set_conf(ceto_cart={**self.configuration, "default_locale": TEMP_LANGUAGE}):
			response = self._dispatch("GET", "/ceto/store/locales")
		self.assertEqual(response.get_json()["default_locale"], TEMP_LANGUAGE)

		site_language = frappe.db.get_single_value("System Settings", "language") or FALLBACK_LOCALE
		with self.set_conf(ceto_cart=self.configuration):
			response = self._dispatch("GET", "/ceto/store/locales")
		self.assertEqual(response.get_json()["default_locale"], site_language)

	def test_the_unpaged_route_refuses_every_query_key(self):
		with self.set_conf(ceto_cart=self.configuration):
			for query in ("fields=code", "limit=10", "offset=0"):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/locales?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def _served_codes(self) -> list[str]:
		response = self._dispatch("GET", "/ceto/store/locales")
		self.assertEqual(response.status_code, 200)
		return [locale["code"] for locale in response.get_json()["locales"]]

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

	def _insert_language(self, code: str) -> None:
		if not frappe.db.exists("Language", code):
			frappe.get_doc(
				{
					"doctype": "Language",
					"__newname": code,
					"language_code": code,
					"language_name": f"Ceto Test {code}",
					"enabled": 1,
				}
			).insert()
