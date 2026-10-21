"""The product reads at assortment scale: fixed query budgets, pinned latency.

Two enforcements the small-scale suites cannot make:

- **Query count is scale-invariant.** Every read surface costs the same
  fixed set of bulk queries over a five-item assortment as over the
  benchmark assortment of exactly 5,000 family variants (50 families x
  100 variants plus one standalone sellable unit). A per-item read — the
  N+1 regression the serializer's batching exists to prevent — multiplies
  its query count by the assortment size and fails the equality here at a
  size where the multiplier is unmistakable. The counts are taken on the
  second read of each surface: an uncounted warm-up pass first absorbs
  Frappe's one-time metadata queries (doctype caches, single defaults),
  which otherwise land on whichever assortment is read first in a cold
  process and would make the comparison order-dependent, not
  scale-dependent. The warm-up cannot hide an N+1: per-item queries are
  paid on every read, so the counted pass still multiplies with size.
- **The reads stay fast at that scale.** One read of the benchmark
  assortment must complete inside the pinned wall-clock budget below.
  The budget is recorded, not discovered per run: the baseline measured at
  ``f5a47b3`` on the CI-class runner was well under 0.5s per surface, and
  the budget pins roughly an order of magnitude of headroom — loose enough
  to stay deterministic across runners, tight enough that a per-item query
  or a quadratic serialization step (seconds at 5,000 units) cannot hide.

The fixture is synthetic by necessity: 5,051 ``Item`` rows through the ORM
controllers would spend minutes of insert overhead on rows the read path
only ever SELECTs. ``frappe.db.bulk_insert`` writes the same columns the
assembler reads (publication flags, family links, variant attributes) into
the same tables, deterministically named and stamped, inside the test
transaction — the per-test rollback discards every row again. The small
assortment, by contrast, travels through the regular fixture factories so
the equality compares a controller-built assortment against a bulk-built
one.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

import frappe

from ceto.services.catalog.products import (
	ProductCatalog,
	option_public_id,
	product_public_id,
)
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite

#: The benchmark assortment: 50 families x 100 variants — exactly 5,000
#: family variants — plus one standalone sellable unit (5,001 served).
BENCH_HEADS = 50
BENCH_VARIANTS_PER_HEAD = 100
BENCH_VARIANT_COUNT = BENCH_HEADS * BENCH_VARIANTS_PER_HEAD
BENCH_ROOT = "Scale Bench Root"

#: The small assortment the benchmark counts are compared against.
TINY_ROOT = "Scale Tiny Root"

BENCH_ATTRIBUTE = "Scale Colour"
BENCH_STAMP = "2026-03-01 00:00:00"

#: The pinned wall-clock budget, in seconds, for ONE read of the benchmark
#: assortment (any of the five surfaces, page-sized). Baseline at
#: ``f5a47b3``: every surface measured well under 0.5s — the budget is the
#: recorded target with headroom, not the observed time. Re-pin it only
#: with a deliberate, documented change to the read path's complexity.
READ_BUDGET_SECONDS = 2.0

#: The read surfaces, each exercised page-sized on both assortments.
SURFACES = ("list", "get", "variant_page", "option_page", "get_option")

#: The served-set sizes that prove each counted read really served the
#: assortment: the tiny fixture's three products (two families plus the
#: standalone), five sellable units and two options; the benchmark's 51
#: products (50 families plus the standalone), 5,001 sellable units and
#: 50 family options.
TINY_EXPECTED = {"list": 3, "get": 1, "variant_page": 5, "option_page": 2, "get_option": 1}
BENCH_EXPECTED = {
	"list": BENCH_HEADS + 1,
	"get": 1,
	"variant_page": BENCH_VARIANT_COUNT + 1,
	"option_page": BENCH_HEADS,
	"get_option": 1,
}

BENCH_ITEM_FIELDS = (
	"name",
	"item_code",
	"item_name",
	"item_group",
	"stock_uom",
	"has_variants",
	"variant_of",
	"disabled",
	"is_sales_item",
	"creation",
	"modified",
	"owner",
	"modified_by",
)


class ProductsScaleSuite(CetoTestSuite):
	"""Shared fixtures: the tiny controller-built and benchmark bulk-built sets."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()

	@contextmanager
	def counted_queries(self) -> Iterator[mock.Mock]:
		"""Spy on ``frappe.db.sql`` for the block: the query builder and
		``frappe.get_all`` both run through it."""
		with mock.patch.object(frappe.db, "sql", wraps=frappe.db.sql) as spy:
			yield spy

	def build_tiny_assortment(self) -> dict[str, str]:
		"""Mint the small assortment: two families, one standalone item."""
		self.fixtures.item_group(TINY_ROOT, is_group=True)
		attribute = self.fixtures.item_attribute("Black", "Red", name=BENCH_ATTRIBUTE)
		heads = [
			self.fixtures.template_item(
				item_code=f"SCALE-TINY-H{index}",
				item_name=f"Scale Tiny H{index}",
				item_group=TINY_ROOT,
				attributes=[{"attribute": attribute}],
			)
			for index in range(2)
		]
		for head in heads:
			self.fixtures.variant_item(head, item_code=f"{head.name}-BLACK")
			self.fixtures.variant_item(head, attribute_value="Red", item_code=f"{head.name}-RED")
		standalone = self.fixtures.item(
			item_code="SCALE-TINY-SOLO", item_name="Scale Tiny Solo", item_group=TINY_ROOT
		)
		return {
			"product_id": product_public_id(standalone.name),
			"option_id": option_public_id(heads[0].name, attribute),
		}

	def build_bench_assortment(self) -> dict[str, str]:
		"""Bulk-write the benchmark assortment: 50x100 family variants + one solo.

		Every identity is fixed — codes, titles, stamps, attribute rows — so
		the served set (and therefore the measured cost) is identical run to
		run. The rows carry exactly the columns the read path SELECTs.
		"""
		self.fixtures.item_group(BENCH_ROOT, is_group=True)
		item_rows: list[tuple[Any, ...]] = []
		attr_rows: list[tuple[Any, ...]] = []
		for index in range(BENCH_HEADS):
			head = f"SCALE-BENCH-H{index:03d}"
			item_rows.append(
				(head, head, f"Scale Bench H{index:03d}", BENCH_ROOT, "Unit", 1, None, 0, 1, *self._stamps())
			)
			attr_rows.append((f"{head}-attr", head, "Item", "attributes", 0, BENCH_ATTRIBUTE, ""))
			for member in range(BENCH_VARIANTS_PER_HEAD):
				code = f"{head}-V{member:03d}"
				item_rows.append(
					(
						code,
						code,
						f"Scale Bench H{index:03d} V{member:03d}",
						BENCH_ROOT,
						"Unit",
						0,
						head,
						0,
						1,
						*self._stamps(),
					)
				)
				attr_rows.append(
					(f"{code}-attr", code, "Item", "attributes", 0, BENCH_ATTRIBUTE, f"Shade {member:03d}")
				)
		solo = "SCALE-BENCH-SOLO"
		item_rows.append((solo, solo, "Scale Bench Solo", BENCH_ROOT, "Unit", 0, None, 0, 1, *self._stamps()))

		frappe.db.bulk_insert("Item", list(BENCH_ITEM_FIELDS), item_rows)
		frappe.db.bulk_insert(
			"Item Variant Attribute",
			["name", "parent", "parenttype", "parentfield", "idx", "attribute", "attribute_value"],
			attr_rows,
		)
		return {
			"product_id": product_public_id(solo),
			"option_id": option_public_id("SCALE-BENCH-H000", BENCH_ATTRIBUTE),
		}

	def counted_reads(self, ids: dict[str, str], expected: dict[str, int], root: str) -> dict[str, int]:
		"""Read every surface twice under ``root`` — once uncounted, once counted.

		The uncounted first pass pays Frappe's one-time metadata warm-up
		(doctype caches, single defaults): in a cold process those queries
		land on whichever assortment is read first, so counting them makes
		the budget order-dependent. The counted second pass measures the
		read's own cost and returns the ``frappe.db.sql`` call count per
		surface. Each counted read must serve its expected set — a count
		over an empty or partial read says nothing about the real one.
		"""
		counts: dict[str, int] = {}
		with self.set_conf(ceto_catalog={"category_roots": [root]}):
			catalog = ProductCatalog()
			for surface in SURFACES:
				self.read_surface(catalog, surface, ids)
			for surface in SURFACES:
				with self.counted_queries() as spy:
					result = self.read_surface(catalog, surface, ids)
				self.assertEqual(self.served_count(result), expected[surface], surface)
				counts[surface] = spy.call_count
		return counts

	def timed_reads(self, ids: dict[str, str], expected: dict[str, int], root: str) -> dict[str, float]:
		"""Time every surface once under ``root``, serving ``expected`` sizes."""
		timings: dict[str, float] = {}
		with self.set_conf(ceto_catalog={"category_roots": [root]}):
			catalog = ProductCatalog()
			for surface in SURFACES:
				start = time.perf_counter()
				result = self.read_surface(catalog, surface, ids)
				timings[surface] = time.perf_counter() - start
				self.assertEqual(self.served_count(result), expected[surface], surface)
		return timings

	@staticmethod
	def read_surface(catalog: ProductCatalog, surface: str, ids: dict[str, str]) -> Any:
		"""Run one page-sized read of ``surface`` over the scoped assortment."""
		if surface == "list":
			return catalog.list(limit=100)
		if surface == "get":
			return catalog.get(ids["product_id"])
		if surface == "variant_page":
			return catalog.variant_page(limit=100)
		if surface == "option_page":
			return catalog.option_page(limit=100)
		return catalog.get_option(ids["option_id"])

	@staticmethod
	def served_count(result: Any) -> int:
		"""The size of the served set a read answered from."""
		return result.count if hasattr(result, "count") else 1

	@staticmethod
	def _stamps() -> tuple[str, str, str, str]:
		return (BENCH_STAMP, BENCH_STAMP, "Administrator", "Administrator")


class TestScaleQueryBudget(ProductsScaleSuite):
	"""The fixed bulk-read set never grows with the assortment."""

	def test_a_page_costs_the_same_bulk_reads_at_5000_variants(self) -> None:
		tiny = self.counted_reads(self.build_tiny_assortment(), expected=TINY_EXPECTED, root=TINY_ROOT)
		bench = self.counted_reads(self.build_bench_assortment(), expected=BENCH_EXPECTED, root=BENCH_ROOT)

		for surface in SURFACES:
			with self.subTest(surface=surface, tiny=tiny[surface], bench=bench[surface]):
				self.assertGreater(tiny[surface], 0)
				self.assertEqual(bench[surface], tiny[surface])


class TestScaleLatencyBudget(ProductsScaleSuite):
	"""One read of the 5,000-variant assortment stays inside the pinned budget."""

	def test_every_surface_serves_5000_variants_within_the_budget(self) -> None:
		ids = self.build_bench_assortment()
		timings = self.timed_reads(ids, expected=BENCH_EXPECTED, root=BENCH_ROOT)

		for surface in SURFACES:
			with self.subTest(surface=surface, seconds=round(timings[surface], 3)):
				self.assertLess(timings[surface], READ_BUDGET_SECONDS)
