"""Store product projections over the published assortment.

The read-only projection the five pinned product routes will serve. The
public identities are derived, never stored (products field-mapping
decision 7): the product id is ``prod_`` plus a SHA-256 truncation of the
exact ``Item`` code, the option/value ids hash the family code with the
attribute (and value), and the image id hashes the item — all opaque,
stable and addressable with no core schema change, the same derivation
pattern the ``pcat_``/``ptag_`` ids use. The ``handle`` is the slug of the
item title with the item code as fallback; a title slug two served
products share is disambiguated on every member with a digest suffix, so
handles stay unique and the mapping stays deterministic for a given
assortment.

Serialization is batched — the merchandising links, the embedded
collection/type/category/tag projections, the variant barcodes and the
region-aware prices each load in one query for the whole served set
before any entity is built, so a page's read cost never grows with its
size. Visibility stays delegated: the assortment comes from the family
assembly over the publication authority, embedded categories/tags only
ever re-serve the projections their own directories serve, and pricing
resolves through the cart price-list authority
(:mod:`ceto.services.catalog.pricing`) only when the caller presents an
explicit ``region_id``. An unknown product id masks as ``404`` like
everywhere else on the Store surface.
"""

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import frappe

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.catalog.collections import CollectionDirectory
from ceto.services.catalog.families import (
	Assortment,
	ProductItem,
	ProductVariant,
	ServedProduct,
	assemble,
)
from ceto.services.catalog.pricing import PricingAuthority, calculate_prices, resolve_pricing_authority
from ceto.services.catalog.product_categories import ProductCategoryDirectory
from ceto.services.catalog.product_tags import ProductTagDirectory
from ceto.services.catalog.product_types import ProductTypeDirectory
from ceto.types.http.store.collections import StoreCollection
from ceto.types.http.store.product_categories import StoreProductCategory
from ceto.types.http.store.product_tags import StoreProductTag
from ceto.types.http.store.product_types import StoreProductType
from ceto.types.http.store.products import (
	PRODUCT_LIST_DEFAULT_LIMIT,
	PRODUCT_LIST_DEFAULT_OFFSET,
	PRODUCT_LIST_MAX_LIMIT,
	PRODUCT_VARIANT_LIST_DEFAULT_LIMIT,
	PRODUCT_VARIANT_LIST_DEFAULT_OFFSET,
	PRODUCT_VARIANT_LIST_MAX_LIMIT,
	StoreCalculatedPrice,
	StoreProduct,
	StoreProductImage,
	StoreProductListResponse,
	StoreProductOption,
	StoreProductOptionValue,
	StoreProductResponse,
	StoreProductVariant,
	StoreProductVariantListResponse,
)

#: The ``Item Barcode`` types that serve the variant's ``ean`` / ``upc``
#: columns; the first barcode row serves ``barcode`` regardless of type.
EAN_BARCODE_TYPES = frozenset({"EAN", "EAN-8", "EAN-13"})

UPC_BARCODE_TYPES = frozenset({"UPC", "UPC-A"})

_SLUG_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")

#: The digest input separator — a character item codes, attributes and
#: values cannot carry, so ``(a, bc)`` and ``(ab, c)`` hash differently.
_DIGEST_SEPARATOR = "\x1f"

_ID_DIGEST_LENGTH = 32

_HANDLE_SUFFIX_LENGTH = 8


def _digest(*parts: str) -> str:
	"""Hash the parts into one hex digest, order-sensitive."""
	return hashlib.sha256(_DIGEST_SEPARATOR.join(parts).encode("utf-8")).hexdigest()


def product_public_id(item_code: str) -> str:
	"""Return the item's stable public id: ``prod_`` + 128 bits of its code's SHA-256."""
	return "prod_" + _digest(item_code)[:_ID_DIGEST_LENGTH]


def option_public_id(product_code: str, attribute: str) -> str:
	"""Return a family option's stable public id, hashed with its family code."""
	return "opt_" + _digest(product_code, attribute)[:_ID_DIGEST_LENGTH]


def option_value_public_id(product_code: str, attribute: str, value: str) -> str:
	"""Return an option value's stable public id, hashed with its family and option."""
	return "optval_" + _digest(product_code, attribute, value)[:_ID_DIGEST_LENGTH]


def image_public_id(item_code: str) -> str:
	"""Return the served image's stable public id, hashed with its item."""
	return "img_" + _digest(item_code, "image")[:_ID_DIGEST_LENGTH]


def product_handle(item_name: str, item_code: str) -> str:
	"""Slug the item title into the product's stable public URL segment.

	A title that slugs to nothing (symbols only, or no title at all) falls
	back to the item code, so the derived handle is never empty.
	"""
	for value in (item_name, item_code):
		slug = _SLUG_SEPARATOR_RE.sub("-", (value or "").strip().lower()).strip("-")
		if slug:
			return slug
	return (item_code or "").strip()


def _unique_handles(items: Iterable[ProductItem]) -> dict[str, str]:
	"""Resolve the served set's handles to unique, deterministic segments.

	A title slug only one product claims is the handle. A shared slug
	disambiguates every colliding member — not an arbitrary survivor — by
	appending the member's own product-id digest, so the same assortment
	always resolves to the same handles.
	"""
	shared: dict[str, list[str]] = {}
	for item in items:
		shared.setdefault(product_handle(item.title, item.item_code), []).append(item.item_code)
	handles: dict[str, str] = {}
	for slug, codes in shared.items():
		if len(codes) == 1:
			handles[codes[0]] = slug
			continue
		for code in sorted(codes):
			suffix = product_public_id(code).removeprefix("prod_")[:_HANDLE_SUFFIX_LENGTH]
			handles[code] = f"{slug}-{suffix}"
	return handles


@dataclass(slots=True)
class _Barcodes:
	"""The served barcode columns of one variant."""

	barcode: str | None = None
	ean: str | None = None
	upc: str | None = None


@dataclass(frozen=True, slots=True)
class _Enrichment:
	"""Every batched lookup the product/variant serializers need."""

	handles: dict[str, str] = field(default_factory=dict)
	merchandising: dict[str, Any] = field(default_factory=dict)
	collections: dict[str, StoreCollection] = field(default_factory=dict)
	types: dict[str, StoreProductType] = field(default_factory=dict)
	categories: dict[str, StoreProductCategory] = field(default_factory=dict)
	tags: dict[str, list[StoreProductTag]] = field(default_factory=dict)
	barcodes: dict[str, _Barcodes] = field(default_factory=dict)
	prices: dict[str, StoreCalculatedPrice] = field(default_factory=dict)


class ProductCatalog:
	"""Project the published assortment onto the pinned product contracts."""

	def list(
		self,
		*,
		limit: int = PRODUCT_LIST_DEFAULT_LIMIT,
		offset: int = PRODUCT_LIST_DEFAULT_OFFSET,
		region_id: str | None = None,
	) -> StoreProductListResponse:
		"""Return the pinned ``{products, count, offset, limit}`` envelope.

		The count runs over the whole served assortment before pagination,
		and the envelope echoes the effective page.
		"""
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), PRODUCT_LIST_MAX_LIMIT)
		products = self._product_projections(region_id)
		return StoreProductListResponse(
			products=products[offset : offset + limit],
			count=len(products),
			offset=offset,
			limit=limit,
		)

	def get(self, product_id: str, *, region_id: str | None = None) -> StoreProductResponse:
		"""Return one served product by its public id; unknown ids mask as 404."""
		by_id = {product.id: product for product in self._product_projections(region_id)}
		product = by_id.get(product_id)
		if product is None:
			raise RouteNotFoundError(f"Product {product_id or '(not set)'} not found")
		return StoreProductResponse(product=product)

	def variant_page(
		self,
		*,
		limit: int = PRODUCT_VARIANT_LIST_DEFAULT_LIMIT,
		offset: int = PRODUCT_VARIANT_LIST_DEFAULT_OFFSET,
		region_id: str | None = None,
	) -> StoreProductVariantListResponse:
		"""Return the canonical variants surface in item-code order.

		Every sellable unit of the served assortment appears — a family's
		published variants and the standalone items' own variants — while
		ineligible-family orphans never do.
		"""
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), PRODUCT_VARIANT_LIST_MAX_LIMIT)
		variants = self._variant_projections(region_id)
		return StoreProductVariantListResponse(
			variants=variants[offset : offset + limit],
			count=len(variants),
			offset=offset,
			limit=limit,
		)

	def _product_projections(self, region_id: str | None) -> list[StoreProduct]:
		"""Serialize the served assortment, enriched and priced in one pass."""
		assortment = assemble()
		if not assortment.products:
			return []
		enrichment = self._enrich(assortment, resolve_pricing_authority(region_id))
		return [self._product_projection(served, enrichment) for served in assortment.products]

	def _variant_projections(self, region_id: str | None) -> list[StoreProductVariant]:
		"""Serialize the variants surface, enriched and priced in one pass."""
		assortment = assemble()
		if not assortment.variants:
			return []
		enrichment = self._enrich(assortment, resolve_pricing_authority(region_id))
		return [self._variant_projection(variant, enrichment) for variant in assortment.variants]

	@staticmethod
	def _enrich(assortment: Assortment, authority: PricingAuthority | None) -> _Enrichment:
		"""Batch-load every lookup the serializers need — one query per source."""
		product_codes = [served.item.item_code for served in assortment.products]
		variant_codes = [variant.item.item_code for variant in assortment.variants]
		merchandising = _load_merchandising(product_codes)
		return _Enrichment(
			handles=_unique_handles(served.item for served in assortment.products),
			merchandising=merchandising,
			collections=CollectionDirectory().projections(
				[row.collection for row in merchandising.values() if row.collection]
			),
			types=ProductTypeDirectory().projections(
				[row.product_type for row in merchandising.values() if row.product_type]
			),
			categories=ProductCategoryDirectory().projections(
				[served.item.item_group for served in assortment.products]
			),
			tags=ProductTagDirectory().item_tag_projections(product_codes),
			barcodes=_load_barcodes(variant_codes),
			prices=(
				calculate_prices(
					{variant.item.item_code: variant.item.stock_uom for variant in assortment.variants},
					authority,
				)
				if authority
				else {}
			),
		)

	def _product_projection(self, served: ServedProduct, enrichment: _Enrichment) -> StoreProduct:
		"""Project one served product onto the pinned entity."""
		item = served.item
		code = item.item_code
		link = enrichment.merchandising.get(code)
		return StoreProduct(
			id=product_public_id(code),
			title=item.title,
			handle=enrichment.handles[code],
			description=item.description,
			thumbnail=item.image,
			images=_image_projections(item),
			collection_id=link.collection if link else None,
			collection=enrichment.collections.get(link.collection) if link else None,
			type_id=link.product_type if link else None,
			type=enrichment.types.get(link.product_type) if link else None,
			categories=(
				[enrichment.categories[item.item_group]] if item.item_group in enrichment.categories else []
			),
			tags=enrichment.tags.get(code, []),
			variants=[self._variant_projection(variant, enrichment) for variant in served.variants],
			options=self._option_projections(served),
			origin_country=item.origin_country,
			created_at=item.created_at,
			updated_at=item.updated_at,
		)

	def _option_projections(self, served: ServedProduct) -> list[StoreProductOption]:
		"""Project the family options, title-then-id ordered, values embedded."""
		code = served.item.item_code
		options = [
			StoreProductOption(
				id=option_public_id(code, option.attribute),
				title=option.attribute,
				values=[
					StoreProductOptionValue(
						id=option_value_public_id(code, option.attribute, value),
						value=value,
						option_id=option_public_id(code, option.attribute),
					)
					for value in option.values
				],
				created_at=served.item.created_at,
				updated_at=served.item.updated_at,
			)
			for option in served.options
		]
		options.sort(key=lambda option: (option.title, option.id))
		return options

	def _variant_projection(self, variant: ProductVariant, enrichment: _Enrichment) -> StoreProductVariant:
		"""Project one sellable unit onto the pinned entity."""
		item = variant.item
		code = item.item_code
		product_code = variant.product.item_code
		barcodes = enrichment.barcodes.get(code)
		return StoreProductVariant(
			id=code,
			title=item.title,
			sku=code,
			barcode=barcodes.barcode if barcodes else None,
			ean=barcodes.ean if barcodes else None,
			upc=barcodes.upc if barcodes else None,
			thumbnail=item.image,
			images=_image_projections(item),
			product_id=product_public_id(product_code),
			options=[
				StoreProductOptionValue(
					id=option_value_public_id(product_code, attribute, value),
					value=value,
					option_id=option_public_id(product_code, attribute),
				)
				for attribute, value in variant.attributes
			],
			calculated_price=enrichment.prices.get(code),
			created_at=item.created_at,
			updated_at=item.updated_at,
		)


def _image_projections(item: ProductItem) -> list[StoreProductImage]:
	"""Project the item's image set — ``Item.image`` is the only source."""
	if not item.image:
		return []
	return [StoreProductImage(id=image_public_id(item.item_code), url=item.image)]


def _load_merchandising(item_codes: Sequence[str]) -> dict[str, Any]:
	"""Batch-load the ``Ceto Product Merchandising`` link per exact item code."""
	codes = sorted({code for code in item_codes if code})
	if not codes:
		return {}
	rows = frappe.get_all(
		"Ceto Product Merchandising",
		filters={"item": ("in", codes)},
		fields=("item", "collection", "product_type"),
	)
	return {row.item: row for row in rows}


def _load_barcodes(item_codes: Sequence[str]) -> dict[str, _Barcodes]:
	"""Batch-load the barcode rows per exact item code, first row serving."""
	codes = sorted({code for code in item_codes if code})
	if not codes:
		return {}
	barcodes: dict[str, _Barcodes] = {}
	rows = frappe.get_all(
		"Item Barcode",
		filters={"parent": ("in", codes), "parenttype": "Item"},
		fields=("parent", "barcode", "barcode_type"),
		order_by="parent asc, idx asc",
	)
	for row in rows:
		entry = barcodes.setdefault(row.parent, _Barcodes(barcode=row.barcode))
		if row.barcode_type in EAN_BARCODE_TYPES and entry.ean is None:
			entry.ean = row.barcode
		if row.barcode_type in UPC_BARCODE_TYPES and entry.upc is None:
			entry.upc = row.barcode
	return barcodes
