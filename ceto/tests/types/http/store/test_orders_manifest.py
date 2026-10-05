"""Contract tests for the pinned Store Order routes manifest.

Phase 0 pinned the contract only; Phase 2 wired the retrieve route and
Phase 3 the list route. The tests fail loudly on manifest drift against the
verified upstream contracts, on drift against the routes the README
advertises, on README status drift against the registered surface, and on
any route registration beyond the implemented retrieval+listing surface.
They are pure Python (no Frappe imports), like the manifest itself.
"""

import re
import unittest
from pathlib import Path

# Import the carts package before the orders manifest: ``carts.responses``
# reaches back into the orders package at module level
# (``StoreCompleteCartSuccess.order``), while ``orders.entities`` subclasses
# ``carts.entities`` — so initializing the orders package before carts cannot
# resolve (pre-existing cross-package import order constraint, the same
# pattern ``test_orders_entities`` follows).
import ceto.types.http.store.carts
from ceto.types.http.store.orders.manifest import (
	ORDER_API_SOURCE_URL,
	ORDER_LIST_DEFAULT_LIMIT,
	ORDER_LIST_DEFAULT_OFFSET,
	ORDER_LIST_FILTERS,
	ORDER_LIST_MAX_LIMIT,
	ORDER_ROUTES,
	ORDER_SDK_METHODS,
	ORDER_SDK_PACKAGE,
	ORDER_SDK_VERSION,
	ORDER_SERVER_PACKAGE,
	ORDER_SERVER_VERSION,
	ORDER_TRANSFER_LIFETIME_DAYS,
	ORDER_TYPES_PACKAGE,
	ORDER_TYPES_VERSION,
)

#: Repo root (this file: ceto/tests/types/http/store/…, five levels down).
REPO_ROOT = Path(__file__).resolve().parents[5]
PACKAGE_ROOT = REPO_ROOT / "ceto"

EXPECTED_METHOD_PATHS = {
	("GET", "/store/orders/{id}"),
	("GET", "/store/orders"),
	("POST", "/store/orders/{id}/transfer/request"),
	("POST", "/store/orders/{id}/transfer/accept"),
	("POST", "/store/orders/{id}/transfer/cancel"),
	("POST", "/store/orders/{id}/transfer/decline"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1`` and the SDK
#: method signatures of ``@medusajs/js-sdk@2.21.1`` (auth against the lockstep
#: server implementation, see the manifest docstring).
EXPECTED_CONTRACTS = {
	("GET", "/store/orders/{id}"): (None, "StoreOrderResponse", "retrieve"),
	("GET", "/store/orders"): (None, "StoreOrderListResponse", "list"),
	("POST", "/store/orders/{id}/transfer/request"): (
		"StoreRequestOrderTransfer",
		"StoreOrderResponse",
		"requestTransfer",
	),
	("POST", "/store/orders/{id}/transfer/accept"): (
		"StoreAcceptOrderTransfer",
		"StoreOrderResponse",
		"acceptTransfer",
	),
	("POST", "/store/orders/{id}/transfer/cancel"): (None, "StoreOrderResponse", "cancelTransfer"),
	("POST", "/store/orders/{id}/transfer/decline"): (
		"StoreDeclineOrderTransfer",
		"StoreOrderResponse",
		"declineTransfer",
	),
}


def readme_orders_rows() -> list[tuple[str, str, str]]:
	"""Parse the Method/Route/Status rows of the README's Orders table."""
	section = (REPO_ROOT / "README.md").read_text().split("### Orders", 1)[1]
	section = section.split("\n### ", 1)[0]
	rows = []
	for line in section.splitlines():
		if not line.startswith("|"):
			continue
		columns = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
		if columns[0] == "Method" or set(columns[0]) <= {"-"}:
			continue
		rows.append((columns[0], columns[1], columns[2]))
	return rows


def registered_orders_routes() -> set[tuple[str, str]]:
	"""Parse the surface ``ceto/api/store/orders.py`` actually registers."""
	orders_api = (PACKAGE_ROOT / "api" / "store" / "orders.py").read_text()
	return {
		(method.upper(), path) for method, path in re.findall(r'@ceto_router\.(\w+)\("([^"]+)"', orders_api)
	}


class TestOrderRouteManifest(unittest.TestCase):
	def test_manifest_covers_exactly_the_6_pinned_routes(self):
		method_paths = {(route.method, route.path) for route in ORDER_ROUTES}
		self.assertEqual(len(ORDER_ROUTES), 6)
		self.assertEqual(method_paths, EXPECTED_METHOD_PATHS)

	def test_routes_are_unique(self):
		method_paths = [(route.method, route.path) for route in ORDER_ROUTES]
		self.assertEqual(len(method_paths), len(set(method_paths)))

	def test_contract_fields_are_populated(self):
		for route in ORDER_ROUTES:
			with self.subTest(route=route):
				self.assertTrue(route.path.startswith("/store/orders"))
				self.assertTrue(route.response_type.startswith("Store"))
				self.assertIn(
					route.auth,
					(
						"publishable-key",
						"publishable-key+customer-session",
						"publishable-key+transfer-token",
					),
				)

	def test_official_httptypes_contracts_are_pinned(self):
		for (method, path), contract in EXPECTED_CONTRACTS.items():
			route = next(r for r in ORDER_ROUTES if (r.method, r.path) == (method, path))
			with self.subTest(route=route):
				self.assertEqual((route.request_type, route.response_type, route.sdk_method), contract)

	def test_sdk_covers_every_pinned_route(self):
		"""Unlike the cart surface, every order route has a direct SDK method."""
		self.assertEqual(
			{route.sdk_method for route in ORDER_ROUTES},
			set(ORDER_SDK_METHODS),
		)

	def test_list_uses_the_paginated_list_response(self):
		route = next(r for r in ORDER_ROUTES if r.sdk_method == "list")
		self.assertEqual(route.response_type, "StoreOrderListResponse")
		self.assertEqual(route.request_type, None)

	def test_retrieve_and_transfer_routes_use_the_order_response(self):
		"""The SDK inlines retrieve's {order: StoreOrder} — the pinned response name."""
		responses = {
			route.sdk_method: route.response_type for route in ORDER_ROUTES if route.sdk_method != "list"
		}
		self.assertEqual(set(responses.values()), {"StoreOrderResponse"})

	def test_cancel_transfer_carries_no_request_body(self):
		"""The SDK sends no body and the pinned server middleware validates none."""
		route = next(r for r in ORDER_ROUTES if r.sdk_method == "cancelTransfer")
		self.assertEqual(route.request_type, None)

	def test_customer_session_is_required_for_list_request_and_cancel(self):
		authors = {route.sdk_method: route.auth for route in ORDER_ROUTES}
		self.assertEqual(
			{method: authors[method] for method in ("list", "requestTransfer", "cancelTransfer")},
			{
				"list": "publishable-key+customer-session",
				"requestTransfer": "publishable-key+customer-session",
				"cancelTransfer": "publishable-key+customer-session",
			},
		)

	def test_accept_and_decline_authorize_with_the_transfer_token(self):
		"""No customer authentication middleware upstream — the token authorizes."""
		authors = {route.sdk_method: route.auth for route in ORDER_ROUTES}
		self.assertEqual(
			{method: authors[method] for method in ("acceptTransfer", "declineTransfer")},
			{
				"acceptTransfer": "publishable-key+transfer-token",
				"declineTransfer": "publishable-key+transfer-token",
			},
		)

	def test_retrieve_stays_guest_accessible(self):
		route = next(r for r in ORDER_ROUTES if r.sdk_method == "retrieve")
		self.assertEqual(route.auth, "publishable-key")

	def test_list_filters_are_pinned(self):
		self.assertEqual(ORDER_LIST_FILTERS, ("id", "status"))

	def test_list_pagination_defaults_are_pinned(self):
		self.assertEqual(ORDER_LIST_DEFAULT_LIMIT, 50)
		self.assertEqual(ORDER_LIST_DEFAULT_OFFSET, 0)

	def test_list_page_bound_is_a_ceto_decision(self):
		"""Upstream 2.21.1 bounds no page size — the read-model cap is Ceto's."""
		self.assertEqual(ORDER_LIST_MAX_LIMIT, 100)

	def test_transfer_lifetime_is_a_ceto_decision(self):
		"""Upstream 2.21.1 defines no expiry — 7 days is Ceto's pinned decision."""
		self.assertEqual(ORDER_TRANSFER_LIFETIME_DAYS, 7)

	def test_sdk_source_and_version_are_pinned(self):
		self.assertEqual(ORDER_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(ORDER_SDK_VERSION, "2.21.1")
		self.assertEqual(ORDER_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(ORDER_TYPES_VERSION, "2.21.1")
		self.assertEqual(ORDER_SERVER_PACKAGE, "@medusajs/medusa")
		self.assertEqual(ORDER_SERVER_VERSION, "2.21.1")
		self.assertEqual(ORDER_API_SOURCE_URL, "https://docs.medusajs.com/api/store/orders")

	def test_readme_orders_table_matches_the_manifest(self):
		"""The advertised surface is the pinned surface — README drift fails."""
		advertised = {(method, path) for method, path, _ in readme_orders_rows()}
		self.assertEqual(len(advertised), 6)
		self.assertEqual(advertised, {(route.method, route.path) for route in ORDER_ROUTES})

	def test_readme_marks_exactly_the_registered_surface_implemented(self):
		"""The advertised status is the implemented surface, mechanically: the
		✅ rows are exactly the routes ``orders.py`` registers — the Phase 2
		retrieval slice and the Phase 3 listing slice — and every other
		pinned row stays ⚪️ To implement."""
		statuses = {(method, path): status for method, path, status in readme_orders_rows()}
		implemented = {route for route, status in statuses.items() if "✅" in status}
		self.assertEqual(implemented, registered_orders_routes())
		self.assertEqual(implemented, {("GET", "/store/orders/{id}"), ("GET", "/store/orders")})
		unimplemented = {route for route, status in statuses.items() if "⚪" in status}
		self.assertEqual(unimplemented, set(statuses) - implemented)
		self.assertEqual(len(unimplemented), 4)

	def test_phase_3_registers_exactly_retrieval_and_listing(self):
		"""Phase 3 boundary: ``orders.py`` wires retrieval and listing exactly.

		Read from source, not imported (the file-read convention of
		``tests/docs/test_orders_field_mapping.py``): the registered surface
		is exactly the two implemented routes — retrieval guest-dispatchable,
		per the pinned ``publishable-key`` auth, and listing
		customer-authenticated, so its decorator carries no ``allow_guest`` —
		and ``routes.py`` wires the module. The four transfer routes stay
		contract-only until their phase registers them; the runtime registry
		equality lives in ``ceto.tests.routing.test_router``.
		"""
		orders_api = (PACKAGE_ROOT / "api" / "store" / "orders.py").read_text()
		self.assertEqual(
			registered_orders_routes(),
			{("GET", "/store/orders/{id}"), ("GET", "/store/orders")},
		)
		self.assertIn('@ceto_router.get("/store/orders/{id}", allow_guest=True)', orders_api)
		self.assertIn('@ceto_router.get("/store/orders")', orders_api)
		self.assertNotIn('@ceto_router.get("/store/orders", allow_guest=True)', orders_api)
		self.assertIn("import ceto.api.store.orders", (PACKAGE_ROOT / "api" / "routes.py").read_text())


if __name__ == "__main__":
	unittest.main()
