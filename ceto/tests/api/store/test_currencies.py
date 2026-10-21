"""Store Currency endpoints: guest-dispatchable reads of the scoped currencies.

Pins the HTTP boundary on the test site: the pinned ``StoreCurrencyListResponse``
and ``StoreCurrencyResponse`` shapes, the publishable-key policy (required on
every read, validated at the boundary only) and the stable Medusa
validation/errors. The list is scoped, never the whole ERPNext currency
table: only the currencies valid configured commerce regions reference are
served, and a currency no valid region references — like an unknown one — is
the same masked ``404 not_found`` on detail.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.routing import ceto_router
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data
from ceto.types.http.store.currencies import StoreCurrency

EXTRA_CURRENCY = "XTS"
UNREFERENCED_CURRENCY = "XUR"


class TestCurrencyAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(settings)
		self.price_list = settings.selling_price_list
		self.currency = frappe.db.get_value("Price List", self.price_list, "currency")
		self._make_currency(EXTRA_CURRENCY)
		self._make_currency(UNREFERENCED_CURRENCY)
		self.extra_price_list = self._make_price_list("Ceto Curr API XTS Selling", EXTRA_CURRENCY)
		# The router rolls the open transaction back on every error response,
		# so the fixtures are committed first — mirroring the customer suites.
		frappe.db.commit()  # nosemgrep
		self.configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"publishable_keys": {"pk_test": {}},
			"regions": {
				"reg_base": {"company": self.company, "selling_price_list": self.price_list},
				"reg_xts": {"company": self.company, "selling_price_list": self.extra_price_list},
			},
		}

	def test_reads_are_guest_dispatchable(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			listed = self._dispatch("GET", "/ceto/store/currencies")
			self.assertEqual(listed.status_code, 200)
			self.assertTrue(listed.get_json()["currencies"])

			retrieved = self._dispatch("GET", f"/ceto/store/currencies/{EXTRA_CURRENCY.lower()}")
			self.assertEqual(retrieved.status_code, 200)
			self.assertEqual(retrieved.get_json()["currency"]["code"], EXTRA_CURRENCY.lower())

	def test_requires_a_configured_publishable_key(self):
		for publishable_key in (None, "pk_unknown"):
			with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
				for path in ("/ceto/store/currencies", f"/ceto/store/currencies/{EXTRA_CURRENCY.lower()}"):
					with self.subTest(publishable_key=publishable_key, path=path):
						response = self._dispatch("GET", path, publishable_key=publishable_key)
						self.assertEqual(response.status_code, 401)
						self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_list_scopes_to_the_configured_regions_currencies(self):
		with self.set_conf(ceto_cart=self.configuration):
			response = self._dispatch("GET", "/ceto/store/currencies")
		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"currencies", "count", "offset", "limit"})
		codes = [entry["code"] for entry in body["currencies"]]
		self.assertEqual(codes, sorted({(self.currency or "").lower(), EXTRA_CURRENCY.lower()}))
		self.assertEqual(body["count"], len(codes))
		# An existing currency no valid region references is never served.
		self.assertNotIn(UNREFERENCED_CURRENCY.lower(), codes)

	def test_list_pagination_is_validated_not_clamped(self):
		with self.set_conf(ceto_cart=self.configuration):
			page = self._dispatch("GET", "/ceto/store/currencies?offset=1&limit=1")
			self.assertEqual(page.status_code, 200)
			self.assertEqual(len(page.get_json()["currencies"]), 1)
			self.assertEqual(page.get_json()["offset"], 1)
			self.assertEqual(page.get_json()["limit"], 1)
			self.assertEqual(page.get_json()["count"], 2)

			for query in ("limit=101", "limit=-1", "offset=-1", "order=code"):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/currencies?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_detail_resolves_the_code_case_insensitively(self):
		with self.set_conf(ceto_cart=self.configuration):
			listed = self._dispatch("GET", "/ceto/store/currencies")
			response = self._dispatch("GET", f"/ceto/store/currencies/{EXTRA_CURRENCY.upper()}")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(response.get_json()), {"currency"})
		entry = response.get_json()["currency"]
		self.assertEqual(set(entry), set(StoreCurrency.model_fields))
		self.assertEqual(entry["code"], EXTRA_CURRENCY.lower())
		self.assertEqual(entry["name"], EXTRA_CURRENCY)
		# Detail answers the identical projection the list serves.
		self.assertEqual(
			entry,
			next(row for row in listed.get_json()["currencies"] if row["code"] == entry["code"]),
		)

	def test_unknown_and_unreferenced_codes_mask_as_not_found(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for code in ("zzz", UNREFERENCED_CURRENCY.lower()):
				with self.subTest(code=code):
					response = self._dispatch("GET", f"/ceto/store/currencies/{code}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")

	def test_detail_refuses_every_query_key(self):
		with self.set_conf(ceto_cart=self.configuration):
			response = self._dispatch("GET", f"/ceto/store/currencies/{EXTRA_CURRENCY.lower()}?fields=code")
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

	def _make_currency(self, code: str) -> str:
		if frappe.db.exists("Currency", code):
			return code
		frappe.get_doc(
			{
				"doctype": "Currency",
				"__newname": code,
				"currency_name": code,
				"enabled": 1,
				"symbol": "Ŧ",
				"number_format": "#,###.##",
			}
		).insert()
		return code

	def _make_price_list(self, name: str, currency: str) -> str:
		if frappe.db.exists("Price List", name):
			return name
		frappe.get_doc(
			{
				"doctype": "Price List",
				"__newname": name,
				"price_list_name": name,
				"currency": currency,
				"selling": 1,
				"buying": 0,
				"enabled": 1,
			}
		).insert()
		return name
