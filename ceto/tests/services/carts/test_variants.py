"""Cart variant resolution delegates to the publication authority.

The cart's only variant surface is ``resolve_item_code``: the exact stored
``Item`` code or the same ``invalid_data`` refusal for every unpublished
id. The tests pin the delegation — published variants and standalone items
resolve while templates, disabled items, non-sales items and items outside
the configured storefront roots are refused exactly like unknown ids — and
the exact ERPNext identity of the resolved code.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import frappe

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.variants import resolve_item_code
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite

ROOT = "Cart Publication Root"
T_SHIRTS = "Cart Publication T-Shirts"
OUTSIDE = "Cart Publication Outside"


class TestResolveItemCode(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.fixtures.item_group(ROOT, is_group=True)
		self.fixtures.item_group(T_SHIRTS, parent=ROOT)
		self.fixtures.item_group(OUTSIDE)

	@contextmanager
	def publish(self) -> Iterator[None]:
		"""Scope the storefront boundary the resolver is gated by."""
		with self.set_conf(ceto_catalog={"category_roots": [ROOT]}):
			yield

	def published_item(self, **overrides):
		return self.fixtures.item(item_group=T_SHIRTS, **overrides)

	def test_a_published_standalone_item_resolves_to_its_exact_code(self) -> None:
		standalone = self.published_item()

		with self.publish():
			self.assertEqual(resolve_item_code(standalone.name), standalone.name)

	def test_a_published_variant_resolves_and_its_template_does_not(self) -> None:
		template = self.fixtures.template_item(item_group=T_SHIRTS)
		variant = self.fixtures.variant_item(template)

		with self.publish():
			self.assertEqual(resolve_item_code(variant.name), variant.name)
			with self.assertRaises(InvalidDataError):
				resolve_item_code(template.name)

	def test_a_disabled_or_non_sales_item_is_refused(self) -> None:
		disabled = self.published_item(disabled=1)
		non_sales = self.published_item(is_sales_item=0)

		with self.publish():
			with self.assertRaises(InvalidDataError):
				resolve_item_code(disabled.name)
			with self.assertRaises(InvalidDataError):
				resolve_item_code(non_sales.name)

	def test_an_item_outside_the_roots_is_refused_like_an_unknown_id(self) -> None:
		outside = self.fixtures.item(item_group=OUTSIDE)

		with self.publish():
			with self.assertRaises(InvalidDataError):
				resolve_item_code(outside.name)
			with self.assertRaises(InvalidDataError):
				resolve_item_code("DEV-MISSING-001")
