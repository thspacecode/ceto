"""The published assortment assembled into Store product families.

One batched pass turns the published ``Item`` rows into the served
projection units. The family semantics are the field-mapping decisions,
resolved here and nowhere else: a product is either an **eligible
template** — a ``has_variants`` item that passes the publication
authority's base rules (enabled, sales, inside the configured storefront
roots) — or a **standalone published item**; every sellable unit is an
ERPNext ``Item`` code, the exact variant id the carts resolve (decision
2). A variant serves only inside its eligible family: a variant whose
template is not itself an eligible head is an orphan and is never exposed
— not as a variant, not as a product — even though the cart's resolver
still accepts its code. A family with zero published variants still
serves: the head projects an empty ``variants`` list, because eligibility
is the assortment boundary, not a sales record.

Options derive from the family head's ``Item Variant Attribute`` rows;
their values are only the attribute values observed on *published*
variants, so an unpublished variant's value never leaks through an option.
A standalone item serves as its own single sellable variant with no
options — the shape a Medusa option-less product carries.

Ordering is deterministic everywhere (Recorded Decision 6): products by
``item_name`` then item code (the served order), variants and the variants
surface by item code, option values value-ascending — the option list
itself sorts title-then-id at serialization.
"""

from dataclasses import dataclass
from typing import Any

import frappe

from ceto.services.catalog.publication import published_item_group_names

#: The ``Item`` columns one projection needs — fetched once for the whole
#: published assortment, never per item.
PRODUCT_ITEM_FIELDS = (
	"name",
	"item_name",
	"item_group",
	"description",
	"image",
	"stock_uom",
	"country_of_origin",
	"has_variants",
	"variant_of",
	"creation",
	"modified",
)


@dataclass(frozen=True, slots=True)
class ProductItem:
	"""One published ``Item`` row projected for serialization."""

	item_code: str
	title: str
	item_group: str
	description: str | None
	image: str | None
	stock_uom: str | None
	origin_country: str | None
	created_at: Any
	updated_at: Any

	@classmethod
	def of(cls, row: Any) -> "ProductItem":
		"""Project one fetched ``Item`` row."""
		return cls(
			item_code=row.name,
			title=row.item_name,
			item_group=row.item_group,
			description=row.description or None,
			image=row.image or None,
			stock_uom=row.stock_uom or None,
			origin_country=row.country_of_origin or None,
			created_at=row.creation,
			updated_at=row.modified,
		)


@dataclass(frozen=True, slots=True)
class ProductVariant:
	"""One sellable unit: an exact ``Item`` code inside its owning product."""

	item: ProductItem
	product: ProductItem
	attributes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ProductOption:
	"""One family option: the head's attribute and its observed values."""

	attribute: str
	values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ServedProduct:
	"""One served product: a family head or a standalone item."""

	item: ProductItem
	variants: tuple[ProductVariant, ...] = ()
	options: tuple[ProductOption, ...] = ()


@dataclass(frozen=True, slots=True)
class Assortment:
	"""The whole served assortment, ordered for the read models.

	``products`` is the served product order (title then item code);
	``variants`` is the canonical variants surface — every sellable unit,
	item-code ordered.
	"""

	products: tuple[ServedProduct, ...] = ()
	variants: tuple[ProductVariant, ...] = ()


def assemble() -> Assortment:
	"""Assemble the published assortment in one batched pass.

	Every read below is a single bulk query — the publication boundary, the
	items, the variant attributes — so the shape of the assortment never
	depends on per-item lookups. With no storefront roots configured the
	assortment is empty: nothing is published.
	"""
	groups = published_item_group_names()
	if not groups:
		return Assortment()
	rows = _published_item_rows(groups)
	items = {row.name: ProductItem.of(row) for row in rows}

	heads = {row.name for row in rows if int(row.has_variants)}
	family_of: dict[str, str] = {}
	standalone: set[str] = set()
	for row in rows:
		if row.name in heads:
			continue
		if row.variant_of and row.variant_of in heads:
			family_of[row.name] = row.variant_of
		elif not row.variant_of:
			standalone.add(row.name)
		# else: an orphan variant of an ineligible head — never exposed.

	head_attributes = _head_attributes(heads)
	variant_attributes = _variant_attributes(family_of, head_attributes)

	products: list[ServedProduct] = []
	surface: list[ProductVariant] = []
	for row in rows:  # the SQL order (title, item code) is the served order
		item = items[row.name]
		if row.name in heads:
			members = tuple(
				ProductVariant(items[code], item, variant_attributes.get(code, ()))
				for code in sorted(family_of)
				if family_of[code] == row.name
			)
			products.append(
				ServedProduct(item, members, _options(head_attributes.get(row.name, ()), members))
			)
			surface.extend(members)
		elif row.name in standalone:
			variant = ProductVariant(item, item)
			products.append(ServedProduct(item, (variant,)))
			surface.append(variant)
	return Assortment(tuple(products), tuple(sorted(surface, key=lambda variant: variant.item.item_code)))


def _published_item_rows(groups: set[str]) -> list[Any]:
	"""Fetch every base-rule-published ``Item`` row in served order."""
	return frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1, "item_group": ("in", sorted(groups))},
		fields=PRODUCT_ITEM_FIELDS,
		order_by="item_name asc, name asc",
	)


def _head_attributes(heads: set[str]) -> dict[str, tuple[str, ...]]:
	"""Batch-load the family heads' attribute titles, template order kept."""
	titles: dict[str, list[str]] = {code: [] for code in heads}
	for row in _variant_attribute_rows(heads):
		known = titles.get(row.parent)
		if row.attribute and known is not None and row.attribute not in known:
			known.append(row.attribute)
	return {code: tuple(known) for code, known in titles.items() if known}


def _variant_attributes(
	family_of: dict[str, str], head_attributes: dict[str, tuple[str, ...]]
) -> dict[str, tuple[tuple[str, str], ...]]:
	"""Batch-load the published variants' observed values per family option.

	A value survives only when its attribute is one of the family head's
	options, and the pairs keep the head's attribute order — the shape the
	variant's option-value projection serializes.
	"""
	observed: dict[str, list[tuple[str, str]]] = {code: [] for code in family_of}
	for row in _variant_attribute_rows(set(family_of)):
		pairs = observed.get(row.parent)
		head = family_of.get(row.parent, "")
		if pairs is None or not row.attribute or not row.attribute_value:
			continue
		if row.attribute in head_attributes.get(head, ()):
			pairs.append((row.attribute, row.attribute_value))
	attributes: dict[str, tuple[tuple[str, str], ...]] = {}
	for code, pairs in observed.items():
		head_order = head_attributes.get(family_of[code], ())
		values = dict(pairs)
		attributes[code] = tuple(
			(attribute, values[attribute]) for attribute in head_order if attribute in values
		)
	return attributes


def _options(
	head_attributes: tuple[str, ...], members: tuple[ProductVariant, ...]
) -> tuple[ProductOption, ...]:
	"""Project the family options: every head attribute, published values only."""
	observed: dict[str, set[str]] = {attribute: set() for attribute in head_attributes}
	for member in members:
		for attribute, value in member.attributes:
			if attribute in observed:
				observed[attribute].add(value)
	return tuple(ProductOption(attribute, tuple(sorted(values))) for attribute, values in observed.items())


def _variant_attribute_rows(parents: set[str]) -> list[Any]:
	"""Batch-load ``Item Variant Attribute`` rows for the given item codes."""
	if not parents:
		return []
	return frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": ("in", sorted(parents)), "parenttype": "Item"},
		fields=("parent", "attribute", "attribute_value"),
		order_by="parent asc, idx asc",
	)
