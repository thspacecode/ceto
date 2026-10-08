"""Mechanical drift checks on the pinned customer route manifest.

Phase 0 registers no endpoint behavior, so the manifest is drifted against the
documented route inventory and the pinned ``@medusajs/js-sdk@2.21.1`` /
``@medusajs/types@2.21.1`` contracts only (the docs inventory itself is
cross-checked in ``ceto.tests.docs.test_customers_endpoints``). When the
customer routes are implemented, the registered router surface must equal this
manifest, exactly like ``ceto.tests.routing.test_router`` does for carts.
"""

import unittest

from ceto.types.http.store.customers.manifest import (
	CUSTOMER_API_SOURCE_URL,
	CUSTOMER_ROUTES,
	CUSTOMER_SDK_METHODS,
	CUSTOMER_SDK_PACKAGE,
	CUSTOMER_SDK_VERSION,
	CUSTOMER_TYPES_PACKAGE,
	CUSTOMER_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {
	("GET", "/store/customers/me"),
	("GET", "/store/customers/me/addresses"),
	("GET", "/store/customers/me/addresses/{address_id}"),
	("POST", "/store/customers"),
	("POST", "/store/customers/me"),
	("POST", "/store/customers/me/addresses"),
	("POST", "/store/customers/me/addresses/{address_id}"),
	("DELETE", "/store/customers/me/addresses/{address_id}"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1`` (the package
#: ``@medusajs/js-sdk@2.21.1`` depends on) and the SDK method signatures.
EXPECTED_CONTRACTS = {
	("POST", "/store/customers"): (
		"StoreCreateCustomer",
		"StoreCustomerResponse",
		"create",
		"SelectParams",
		"publishable-key+registration-token",
	),
	("GET", "/store/customers/me"): (
		None,
		"StoreCustomerResponse",
		"retrieve",
		"StoreGetCustomerParams",
		"publishable-key+customer-session",
	),
	("POST", "/store/customers/me"): (
		"StoreUpdateCustomer",
		"StoreCustomerResponse",
		"update",
		"SelectParams",
		"publishable-key+customer-session",
	),
	("GET", "/store/customers/me/addresses"): (
		None,
		"StoreCustomerAddressListResponse",
		"listAddress",
		"StoreCustomerAddressFilters",
		"publishable-key+customer-session",
	),
	("POST", "/store/customers/me/addresses"): (
		"StoreCreateCustomerAddress",
		"StoreCustomerResponse",
		"createAddress",
		"SelectParams",
		"publishable-key+customer-session",
	),
	("GET", "/store/customers/me/addresses/{address_id}"): (
		None,
		"StoreCustomerAddressResponse",
		"retrieveAddress",
		"StoreGetCustomerAddressParams",
		"publishable-key+customer-session",
	),
	("POST", "/store/customers/me/addresses/{address_id}"): (
		"StoreUpdateCustomerAddress",
		"StoreCustomerResponse",
		"updateAddress",
		"SelectParams",
		"publishable-key+customer-session",
	),
	("DELETE", "/store/customers/me/addresses/{address_id}"): (
		None,
		"StoreCustomerAddressDeleteResponse",
		"deleteAddress",
		None,
		"publishable-key+customer-session",
	),
}


class TestCustomerRouteManifest(unittest.TestCase):
	def test_manifest_covers_exactly_the_8_pinned_routes(self):
		method_paths = {(route.method, route.path) for route in CUSTOMER_ROUTES}
		self.assertEqual(len(CUSTOMER_ROUTES), 8)
		self.assertEqual(method_paths, EXPECTED_METHOD_PATHS)

	def test_routes_are_unique(self):
		method_paths = [(route.method, route.path) for route in CUSTOMER_ROUTES]
		self.assertEqual(len(method_paths), len(set(method_paths)))

	def test_contract_fields_are_populated(self):
		for route in CUSTOMER_ROUTES:
			with self.subTest(route=route):
				self.assertTrue(route.path.startswith("/store/customers"))
				self.assertTrue(route.response_type.startswith("Store"))
				self.assertIn(
					route.auth,
					("publishable-key+registration-token", "publishable-key+customer-session"),
				)

	def test_official_httptypes_contracts_are_pinned(self):
		for (method, path), contract in EXPECTED_CONTRACTS.items():
			route = next(r for r in CUSTOMER_ROUTES if (r.method, r.path) == (method, path))
			with self.subTest(route=route):
				self.assertEqual(
					(route.request_type, route.response_type, route.sdk_method, route.query_type),
					contract[:4],
				)
				self.assertEqual(route.auth, contract[4])

	def test_create_requires_the_registration_token(self):
		route = next(r for r in CUSTOMER_ROUTES if (r.method, r.path) == ("POST", "/store/customers"))
		self.assertEqual(route.auth, "publishable-key+registration-token")

	def test_me_routes_require_the_customer_session(self):
		me_routes = {(r.method, r.path): r.auth for r in CUSTOMER_ROUTES if "/me" in r.path}
		self.assertEqual(len(me_routes), 7)
		self.assertEqual(set(me_routes.values()), {"publishable-key+customer-session"})

	def test_sdk_source_and_version_are_pinned(self):
		self.assertEqual(CUSTOMER_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(CUSTOMER_SDK_VERSION, "2.21.1")
		self.assertEqual(CUSTOMER_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(CUSTOMER_TYPES_VERSION, "2.21.1")
		self.assertEqual(CUSTOMER_API_SOURCE_URL, "https://docs.medusajs.com/api/store/customers")

	def test_sdk_coverage_of_pinned_methods(self):
		self.assertEqual(
			set(CUSTOMER_SDK_METHODS),
			{
				"create",
				"retrieve",
				"update",
				"listAddress",
				"createAddress",
				"retrieveAddress",
				"updateAddress",
				"deleteAddress",
			},
		)

	def test_every_route_has_an_sdk_method(self):
		# Unlike carts, the pinned SDK covers the whole customer surface; a
		# route without a method would need the raw-client escape hatch and a
		# manifest comment explaining why.
		for route in CUSTOMER_ROUTES:
			with self.subTest(route=route):
				self.assertIn(route.sdk_method, CUSTOMER_SDK_METHODS)

	def test_only_the_delete_route_has_no_query_contract(self):
		queryless = {(r.method, r.path) for r in CUSTOMER_ROUTES if r.query_type is None}
		self.assertEqual(queryless, {("DELETE", "/store/customers/me/addresses/{address_id}")})

	def test_only_the_list_route_is_paginated(self):
		paginated = {
			(r.method, r.path) for r in CUSTOMER_ROUTES if r.query_type == "StoreCustomerAddressFilters"
		}
		self.assertEqual(paginated, {("GET", "/store/customers/me/addresses")})


if __name__ == "__main__":
	unittest.main()
