"""The deterministic assortment the product golden bodies are served from.

Every fact the served contracts carry is pinned here: the storefront roots,
the family head and its variants, the standalone item, the attribute master
name, the merchandising link ids, the tag value and every served record's
``creation`` / ``modified`` timestamps. Nothing mints a random identity, so
the same fixture always serves the same bodies
(``ceto.tests.golden.product_responses``).

Timestamps are pinned by writing the two columns directly after the ORM
insert: ``Document.insert`` stamps ``creation`` / ``modified`` with the
current time and offers no override, and ``update_modified=False`` keeps
the write from restamping ``modified``. The rows still travel through the
controllers on insert, so nothing about served behaviour is bypassed —
only the two audit stamps are fixed.

Prices resolve through the baseline bootstrap price list, whose currency
the golden bodies pin as ``usd``; the storefront helper refuses a site
whose baseline currency differs, so a drifted site fails with a message
instead of a misleading body diff.
"""

from dataclasses import dataclass
from typing import Any

import frappe

from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.services.catalog.products import option_public_id, product_public_id
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import boot_strap_test_master_data

GOLDEN_ROOT = "Golden Catalog"
GOLDEN_GROUP = "Golden Apparel"
GOLDEN_ATTRIBUTE = "Golden Colour"

GOLDEN_TEE = "GOLDEN-TEE"
GOLDEN_TEE_BLACK = "GOLDEN-TEE-BLACK"
GOLDEN_TEE_RED = "GOLDEN-TEE-RED"
GOLDEN_SOCK = "GOLDEN-SOCK"

GOLDEN_TAG = "golden-tee"
GOLDEN_COLLECTION_ID = "pcol_" + "1" * 32
GOLDEN_TYPE_ID = "ptyp_" + "2" * 32

#: The pinned audit stamps: each product/variant serves its own row's pair,
#: and the family head's pair serves its option projection.
CREATED_AT = "2026-01-15 08:30:00"
UPDATED_AT = "2026-02-20 17:45:12"

#: The pricing context the priced golden reads present. The cart
#: configuration is scoped without a ``regions`` overlay, so the value
#: passes through to the baseline selling price list untouched.
GOLDEN_REGION_ID = "reg_test"

PUBLISHABLE_KEY = "pk_test"


@dataclass(frozen=True, slots=True)
class GoldenAssortment:
	"""The fixture facts the golden routes address."""

	product_id: str
	option_id: str


def golden_storefront() -> dict[str, Any]:
	"""Return the ``ceto_catalog`` / ``ceto_cart`` conf the golden reads serve.

	``ceto_catalog`` scopes the storefront to the fixture's own root — the
	committed baseline assortment stays outside the served set — and the
	cart anchors resolve pricing exactly like the priced API suites do.
	"""
	settings = boot_strap_test_master_data.resolve_baseline_settings()
	currency = frappe.db.get_value("Price List", settings.selling_price_list, "currency")
	if currency != "USD":
		raise AssertionError(
			f"Golden bodies pin the baseline price list currency as USD; site serves {currency!r}"
		)
	return {
		"ceto_catalog": {"category_roots": [GOLDEN_ROOT]},
		"ceto_cart": {
			"publishable_keys": {PUBLISHABLE_KEY: {}},
			"guest_customer": frappe.db.get_value(
				"Customer", {"customer_name": settings.guest_customer_name}
			),
			"company": resolve_company(settings),
			"selling_price_list": settings.selling_price_list,
		},
	}


def build_golden_assortment(fixtures: CatalogTestData) -> GoldenAssortment:
	"""Mint the published assortment the golden bodies serve, deterministically.

	One published family — two variants, merchandised, tagged, one barcode
	set, priced — and one unlinked standalone item, all inside one fixture
	Item Group. Every identity is fixed; see the module docstring for the
	timestamp pinning.
	"""
	fixtures.item_group(GOLDEN_ROOT, is_group=True)
	group = fixtures.item_group(GOLDEN_GROUP, parent=GOLDEN_ROOT)
	_pin_timestamps("Item Group", group.name)

	attribute = fixtures.item_attribute("Black", "Red", name=GOLDEN_ATTRIBUTE)
	head = fixtures.template_item(
		item_code=GOLDEN_TEE,
		item_name="Golden Anvil Tee",
		item_group=GOLDEN_GROUP,
		description="Golden anvil tee description.",
		image="/files/golden-tee.png",
		country_of_origin="Portugal",
		attributes=[{"attribute": attribute}],
	)
	black = fixtures.variant_item(
		head,
		item_code=GOLDEN_TEE_BLACK,
		item_name="Golden Anvil Tee Black",
		image="/files/golden-tee-black.png",
	)
	red = fixtures.variant_item(
		head,
		attribute_value="Red",
		item_code=GOLDEN_TEE_RED,
		item_name="Golden Anvil Tee Red",
	)
	sock = fixtures.item(
		item_code=GOLDEN_SOCK,
		item_name="Golden Zephyr Sock",
		item_group=GOLDEN_GROUP,
		description="Golden zephyr sock description.",
		image="/files/golden-sock.png",
		country_of_origin="Thailand",
	)
	# Barcode rows re-save their Item, so they land before the stamp pinning.
	fixtures.barcode(black, "GT-BARCODE-FIRST")
	fixtures.barcode(black, "4006381333931", barcode_type="EAN-13")
	for item in (head, black, red, sock):
		_pin_timestamps("Item", item.name)

	collection = fixtures.collection(
		collection_id=GOLDEN_COLLECTION_ID,
		title="Golden Anvil Collection",
		handle="golden-anvil-collection",
	)
	product_type = fixtures.product_type(type_id=GOLDEN_TYPE_ID, value="Golden Apparel Type")
	_pin_timestamps("Ceto Collection", collection.name)
	_pin_timestamps("Ceto Product Type", product_type.name)

	fixtures.merchandising(head, collection=collection, product_type=product_type)
	fixtures.item_tag(head, GOLDEN_TAG)

	price_list = boot_strap_test_master_data.resolve_baseline_settings().selling_price_list
	for item, rate in ((black, 24.5), (red, 26.0), (sock, 12.0)):
		fixtures.item_price(item, rate, price_list=price_list)

	return GoldenAssortment(
		product_id=product_public_id(GOLDEN_TEE),
		option_id=option_public_id(GOLDEN_TEE, GOLDEN_ATTRIBUTE),
	)


def _pin_timestamps(doctype: str, name: str) -> None:
	"""Freeze one record's served audit stamps (see the module docstring)."""
	frappe.db.set_value(
		doctype,
		name,
		{"creation": CREATED_AT, "modified": UPDATED_AT},
		update_modified=False,
	)
