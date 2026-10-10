"""The Ceto development catalog: deliberately fake, non-production records.

Record names carry a ``Dev``/``DEV`` prefix so the dataset can never be
mistaken for production master data. Rows are plain data declarations; all
behavior lives in the seeders under ``ceto.data.bootstrap_dev.seeders``.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ItemGroupSeed:
	"""One storefront category; ``parent`` of ``None`` uses the site root."""

	item_group_name: str
	parent: str | None = None
	is_group: bool = False


@dataclass(frozen=True)
class UomSeed:
	"""A UOM the catalog requires; shared UOMs are never mutated."""

	uom_name: str
	must_be_whole_number: bool


@dataclass(frozen=True)
class WarehouseSeed:
	"""One warehouse; ``parent`` of ``None`` uses the company root warehouse."""

	warehouse_name: str
	parent: str | None = None
	is_group: bool = False


@dataclass(frozen=True)
class ItemSeed:
	"""One sellable item; ``default_warehouse`` names a dataset warehouse."""

	item_code: str
	item_name: str
	item_group: str
	stock_uom: str
	description: str
	default_warehouse: str | None = None
	is_stock_item: bool = True
	is_sales_item: bool = True
	is_purchase_item: bool = False


@dataclass(frozen=True)
class ItemPriceSeed:
	"""One open-ended selling rate on the bootstrap price list."""

	item_code: str
	price_list_rate: Decimal


@dataclass(frozen=True)
class ItemTagSeed:
	"""The demo tags pinned on one demo item; ``tags`` are Tag master names."""

	item_code: str
	tags: tuple[str, ...]


@dataclass(frozen=True)
class CollectionSeed:
	"""One demo collection; ``handle`` is the stable business key."""

	title: str
	handle: str
	external_id: str | None = None
	metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class ProductTypeSeed:
	"""One demo product type; ``value`` is the stable business key."""

	value: str
	external_id: str | None = None
	metadata: dict[str, object] | None = None


ITEM_GROUPS: tuple[ItemGroupSeed, ...] = (
	ItemGroupSeed(item_group_name="Dev Apparel", parent=None, is_group=True),
	ItemGroupSeed(item_group_name="Dev T-Shirts", parent="Dev Apparel"),
	ItemGroupSeed(item_group_name="Dev Graphic Tees", parent="Dev T-Shirts"),
	ItemGroupSeed(item_group_name="Dev Hoodies", parent="Dev Apparel"),
	ItemGroupSeed(item_group_name="Dev Footwear"),
	ItemGroupSeed(item_group_name="Dev Accessories"),
	ItemGroupSeed(item_group_name="Dev Clearance"),
)

UOMS: tuple[UomSeed, ...] = (
	UomSeed(uom_name="Unit", must_be_whole_number=True),
	UomSeed(uom_name="Pair", must_be_whole_number=True),
	UomSeed(uom_name="Meter", must_be_whole_number=False),
)

WAREHOUSES: tuple[WarehouseSeed, ...] = (
	WarehouseSeed(warehouse_name="Dev Warehouses", parent=None, is_group=True),
	WarehouseSeed(warehouse_name="Dev Sellable Stock", parent="Dev Warehouses"),
	WarehouseSeed(warehouse_name="Dev Returns", parent="Dev Warehouses"),
)

ITEMS: tuple[ItemSeed, ...] = (
	ItemSeed(
		item_code="DEV-TSHIRT-001",
		item_name="Dev Classic T-Shirt",
		item_group="Dev T-Shirts",
		stock_uom="Unit",
		description="Development sample T-shirt for storefront testing.",
		default_warehouse="Dev Sellable Stock",
	),
	ItemSeed(
		item_code="DEV-HOODIE-001",
		item_name="Dev Zip Hoodie",
		item_group="Dev Hoodies",
		stock_uom="Unit",
		description="Development sample hoodie for storefront testing.",
		default_warehouse="Dev Sellable Stock",
	),
	ItemSeed(
		item_code="DEV-SNEAKER-001",
		item_name="Dev Canvas Sneaker",
		item_group="Dev Footwear",
		stock_uom="Pair",
		description="Development sample sneaker exercising a non-default UOM.",
		default_warehouse="Dev Sellable Stock",
	),
	ItemSeed(
		item_code="DEV-MUG-001",
		item_name="Dev Coffee Mug",
		item_group="Dev Accessories",
		stock_uom="Unit",
		description="Development sample mug for storefront testing.",
		default_warehouse="Dev Sellable Stock",
	),
	ItemSeed(
		item_code="DEV-TOTE-001",
		item_name="Dev Clearance Tote",
		item_group="Dev Clearance",
		stock_uom="Unit",
		description="Development sample clearance item.",
		default_warehouse="Dev Sellable Stock",
	),
)

ITEM_PRICES: tuple[ItemPriceSeed, ...] = (
	ItemPriceSeed(item_code="DEV-TSHIRT-001", price_list_rate=Decimal("25.00")),
	ItemPriceSeed(item_code="DEV-HOODIE-001", price_list_rate=Decimal("59.00")),
	ItemPriceSeed(item_code="DEV-SNEAKER-001", price_list_rate=Decimal("79.00")),
	ItemPriceSeed(item_code="DEV-MUG-001", price_list_rate=Decimal("12.50")),
	ItemPriceSeed(item_code="DEV-TOTE-001", price_list_rate=Decimal("5.00")),
)

#: Tags are item-level links, so values repeat across items on purpose: the
#: served tag set is the deduplicated projection, and ``DEV-MUG-001`` stays
#: untagged to prove the set is link-driven.
ITEM_TAGS: tuple[ItemTagSeed, ...] = (
	ItemTagSeed(item_code="DEV-TSHIRT-001", tags=("Dev New Arrival", "Dev Summer")),
	ItemTagSeed(item_code="DEV-HOODIE-001", tags=("Dev Summer",)),
	ItemTagSeed(item_code="DEV-SNEAKER-001", tags=("Dev Footwear", "Dev New Arrival")),
)

COLLECTIONS: tuple[CollectionSeed, ...] = (
	CollectionSeed(
		title="Dev Summer Drop",
		handle="dev-summer-drop",
		metadata={"featured": True, "season": "summer"},
	),
	CollectionSeed(
		title="Dev Essentials",
		handle="dev-essentials",
		external_id="dev-collection-essentials",
	),
)

PRODUCT_TYPES: tuple[ProductTypeSeed, ...] = (
	ProductTypeSeed(value="Dev Apparel", external_id="dev-type-apparel"),
	ProductTypeSeed(value="Dev Accessory", metadata={"merchandising": "core"}),
)
