"""Pinned query contracts of the Store Order retrieve/list routes.

Phase 1 pins the request side only: ``StoreGetOrderParams`` (retrieve) and
``StoreOrderFilters`` (list) mirror ``@medusajs/types@2.21.1`` with the
upstream server pagination defaults, while the ``$and``/``$or`` combinators,
``order`` sort expressions and ``with_deleted`` stay rejected (Recorded
Decision 8 of ``docs/orders/field-mapping.md``). Pure Python — no Frappe.
"""

import unittest

from pydantic import ValidationError

# The carts package initializes before the orders package (pre-existing
# cross-package import order constraint, see ``test_orders_manifest``).
import ceto.types.http.store.carts
from ceto.types.http.store.orders import StoreGetOrderParams, StoreOrderFilters
from ceto.types.http.store.orders.manifest import (
	ORDER_LIST_DEFAULT_LIMIT,
	ORDER_LIST_DEFAULT_OFFSET,
	ORDER_LIST_FILTERS,
)


class TestStoreGetOrderParams(unittest.TestCase):
	def test_fields_is_the_only_key(self):
		# The pinned StoreGetOrderParams is a bare SelectParams: fields only.
		self.assertEqual(set(StoreGetOrderParams.model_fields), {"fields"})
		self.assertIsNone(StoreGetOrderParams().fields)
		self.assertEqual(StoreGetOrderParams(fields="id,total").fields, "id,total")

	def test_rejects_every_other_query_key(self):
		for key, value in (
			("limit", 10),
			("offset", 5),
			("id", "order_1"),
			("status", "pending"),
		):
			with self.subTest(key=key), self.assertRaises(ValidationError):
				StoreGetOrderParams(**{key: value})


class TestStoreOrderFilters(unittest.TestCase):
	def test_list_defaults_mirror_the_pinned_pagination(self):
		params = StoreOrderFilters()
		self.assertEqual(params.limit, 50)
		self.assertEqual(params.offset, 0)
		# One source of truth: the manifest pins the upstream server defaults.
		self.assertEqual(params.limit, ORDER_LIST_DEFAULT_LIMIT)
		self.assertEqual(params.offset, ORDER_LIST_DEFAULT_OFFSET)

	def test_fields_rides_the_find_params(self):
		params = StoreOrderFilters(fields="id,status", limit=10, offset=20)
		self.assertEqual(params.fields, "id,status")
		self.assertEqual(params.limit, 10)
		self.assertEqual(params.offset, 20)

	def test_pinned_filters_accept_single_or_list_values(self):
		self.assertEqual(StoreOrderFilters(id="order_1").id, "order_1")
		self.assertEqual(StoreOrderFilters(id=["order_1", "order_2"]).id, ["order_1", "order_2"])
		self.assertEqual(StoreOrderFilters(status="pending").status, "pending")
		self.assertEqual(
			StoreOrderFilters(status=["pending", "completed"]).status,
			["pending", "completed"],
		)

	def test_filters_are_exactly_the_pinned_domain(self):
		# Only the shared selector/pagination keys exist beside the two
		# domain filters pinned by the manifest.
		self.assertEqual(
			set(StoreOrderFilters.model_fields),
			{"fields", "limit", "offset", *ORDER_LIST_FILTERS},
		)

	def test_status_accepts_only_the_pinned_order_status_union(self):
		with self.assertRaises(ValidationError):
			StoreOrderFilters(status="shelved")
		with self.assertRaises(ValidationError):
			StoreOrderFilters(status=["pending", "nope"])

	def test_combinator_sort_and_soft_delete_params_are_rejected(self):
		# Recorded Decision 8: rejected as invalid data, never ignored —
		# a client must never receive a page it cannot reproduce.
		for key, value in (
			("$and", [{"status": "pending"}]),
			("$or", [{"status": "pending"}]),
			("order", "-created_at"),
			("with_deleted", True),
		):
			with self.subTest(key=key), self.assertRaises(ValidationError):
				StoreOrderFilters(**{key: value})

	def test_customer_id_is_never_client_supplied(self):
		# The list handler forces the authenticated caller's customer id.
		with self.assertRaises(ValidationError):
			StoreOrderFilters(customer_id="cust_1")


if __name__ == "__main__":
	unittest.main()
