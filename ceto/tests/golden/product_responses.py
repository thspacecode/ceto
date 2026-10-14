"""The pinned golden bodies of the five product/variant/option reads.

Every literal below was served by ``GET /store/products?region_id=…`` and
its four sibling routes over :data:`ceto.tests.golden.catalog.build_golden_assortment`
and verified value-by-value before being frozen — the derived ids are the
frozen digests of the fixture's exact codes (products field-mapping
decision 7), the timestamps the fixture's pinned audit stamps, the prices
the baseline price list's rates in its pinned ``usd`` currency.

The three priced surfaces serve their fullest shape (a resolved
``calculated_price``); the region-less default — every ``calculated_price``
``null`` — is pinned by the boundary suite's unpriced-read tests. The two
option surfaces accept no pricing context, so their bodies are pricing-free
by contract. A diff against any body is a deliberate contract change: re-
serve the fixture, verify every changed value, and re-pin it here.
"""

GOLDEN_TEE_PRODUCT_ID = "prod_e3241bbee30f1063c604a173261f8577"
GOLDEN_TEE_OPTION_ID = "opt_1b3fb615cbdff1c2a43dcfa4869a9a20"

_BLACK_OPTION_VALUE = {
	"id": "optval_923bfec27efa7c1f4ec47aed06e7a8fe",
	"value": "Black",
	"rank": None,
	"option_id": GOLDEN_TEE_OPTION_ID,
	"option": None,
	"metadata": None,
	"created_at": None,
	"updated_at": None,
	"deleted_at": None,
}

_RED_OPTION_VALUE = {
	"id": "optval_984e6b01fb68504b85b497e2e60da223",
	"value": "Red",
	"rank": None,
	"option_id": GOLDEN_TEE_OPTION_ID,
	"option": None,
	"metadata": None,
	"created_at": None,
	"updated_at": None,
	"deleted_at": None,
}

_GOLDEN_COLOUR_OPTION = {
	"id": GOLDEN_TEE_OPTION_ID,
	"title": "Golden Colour",
	"is_exclusive": None,
	"product": None,
	"values": [_BLACK_OPTION_VALUE, _RED_OPTION_VALUE],
	"metadata": None,
	"created_at": "2026-01-15T08:30:00",
	"updated_at": "2026-02-20T17:45:12",
	"deleted_at": None,
}

_GOLDEN_TEE_PRICE = {
	"is_calculated_price_price_list": True,
	"is_calculated_price_tax_inclusive": False,
	"calculated_amount": 24.5,
	"is_original_price_price_list": True,
	"is_original_price_tax_inclusive": False,
	"original_amount": 24.5,
	"currency_code": "usd",
	"is_calculated_price_promotion": False,
}

_GOLDEN_BLACK_VARIANT = {
	"id": "GOLDEN-TEE-BLACK",
	"title": "Golden Anvil Tee Black",
	"sku": "GOLDEN-TEE-BLACK",
	"barcode": "GT-BARCODE-FIRST",
	"ean": "4006381333931",
	"upc": None,
	"thumbnail": "/files/golden-tee-black.png",
	"images": [
		{
			"id": "img_217f981f20f023f0ff308e05d946d74c",
			"url": "/files/golden-tee-black.png",
			"rank": None,
			"metadata": None,
			"created_at": None,
			"updated_at": None,
			"deleted_at": None,
		}
	],
	"allow_backorder": None,
	"manage_inventory": None,
	"variant_rank": None,
	"product_id": GOLDEN_TEE_PRODUCT_ID,
	"product": None,
	"options": [_BLACK_OPTION_VALUE],
	"calculated_price": _GOLDEN_TEE_PRICE,
	"hs_code": None,
	"origin_country": None,
	"mid_code": None,
	"material": None,
	"weight": None,
	"length": None,
	"height": None,
	"width": None,
	"metadata": None,
	"created_at": "2026-01-15T08:30:00",
	"updated_at": "2026-02-20T17:45:12",
	"deleted_at": None,
}

_GOLDEN_RED_VARIANT = {
	"id": "GOLDEN-TEE-RED",
	"title": "Golden Anvil Tee Red",
	"sku": "GOLDEN-TEE-RED",
	"barcode": None,
	"ean": None,
	"upc": None,
	"thumbnail": None,
	"images": [],
	"allow_backorder": None,
	"manage_inventory": None,
	"variant_rank": None,
	"product_id": GOLDEN_TEE_PRODUCT_ID,
	"product": None,
	"options": [_RED_OPTION_VALUE],
	"calculated_price": {
		"is_calculated_price_price_list": True,
		"is_calculated_price_tax_inclusive": False,
		"calculated_amount": 26.0,
		"is_original_price_price_list": True,
		"is_original_price_tax_inclusive": False,
		"original_amount": 26.0,
		"currency_code": "usd",
		"is_calculated_price_promotion": False,
	},
	"hs_code": None,
	"origin_country": None,
	"mid_code": None,
	"material": None,
	"weight": None,
	"length": None,
	"height": None,
	"width": None,
	"metadata": None,
	"created_at": "2026-01-15T08:30:00",
	"updated_at": "2026-02-20T17:45:12",
	"deleted_at": None,
}

_GOLDEN_SOCK_VARIANT = {
	"id": "GOLDEN-SOCK",
	"title": "Golden Zephyr Sock",
	"sku": "GOLDEN-SOCK",
	"barcode": None,
	"ean": None,
	"upc": None,
	"thumbnail": "/files/golden-sock.png",
	"images": [
		{
			"id": "img_2f602a7af20e54fc6948e827663d58a0",
			"url": "/files/golden-sock.png",
			"rank": None,
			"metadata": None,
			"created_at": None,
			"updated_at": None,
			"deleted_at": None,
		}
	],
	"allow_backorder": None,
	"manage_inventory": None,
	"variant_rank": None,
	"product_id": "prod_34240d77e32a783267d8ba6116d73a15",
	"product": None,
	"options": [],
	"calculated_price": {
		"is_calculated_price_price_list": True,
		"is_calculated_price_tax_inclusive": False,
		"calculated_amount": 12.0,
		"is_original_price_price_list": True,
		"is_original_price_tax_inclusive": False,
		"original_amount": 12.0,
		"currency_code": "usd",
		"is_calculated_price_promotion": False,
	},
	"hs_code": None,
	"origin_country": None,
	"mid_code": None,
	"material": None,
	"weight": None,
	"length": None,
	"height": None,
	"width": None,
	"metadata": None,
	"created_at": "2026-01-15T08:30:00",
	"updated_at": "2026-02-20T17:45:12",
	"deleted_at": None,
}

_GOLDEN_APPAREL_CATEGORY = {
	"id": "pcat_beaca7aa8f50055b2be3679ae2ef669c",
	"name": "Golden Apparel",
	"handle": "golden-apparel",
	"description": None,
	"rank": None,
	"parent_category_id": "pcat_dd3ec3e0883c4ef22f0b715f5d6837a0",
	"parent_category": None,
	"category_children": [],
	"external_id": None,
	"metadata": None,
	"created_at": "2026-01-15T08:30:00",
	"updated_at": "2026-02-20T17:45:12",
	"deleted_at": None,
}

_GOLDEN_ANVIL_TEE = {
	"id": GOLDEN_TEE_PRODUCT_ID,
	"title": "Golden Anvil Tee",
	"handle": "golden-anvil-tee",
	"subtitle": None,
	"description": "Golden anvil tee description.",
	"is_giftcard": None,
	"discountable": None,
	"status": None,
	"thumbnail": "/files/golden-tee.png",
	"origin_country": "Portugal",
	"collection_id": "pcol_11111111111111111111111111111111",
	"collection": {
		"id": "pcol_11111111111111111111111111111111",
		"title": "Golden Anvil Collection",
		"handle": "golden-anvil-collection",
		"metadata": None,
		"external_id": None,
		"created_at": "2026-01-15T08:30:00",
		"updated_at": "2026-02-20T17:45:12",
		"deleted_at": None,
	},
	"type_id": "ptyp_22222222222222222222222222222222",
	"type": {
		"id": "ptyp_22222222222222222222222222222222",
		"value": "Golden Apparel Type",
		"external_id": None,
		"metadata": None,
		"created_at": "2026-01-15T08:30:00",
		"updated_at": "2026-02-20T17:45:12",
		"deleted_at": None,
	},
	"categories": [_GOLDEN_APPAREL_CATEGORY],
	"tags": [
		{
			"id": "ptag_f3ea6777336496633274ec493c3b4f06",
			"value": "golden-tee",
			"external_id": None,
			"metadata": None,
			"created_at": None,
			"updated_at": None,
			"deleted_at": None,
		}
	],
	"variants": [_GOLDEN_BLACK_VARIANT, _GOLDEN_RED_VARIANT],
	"options": [_GOLDEN_COLOUR_OPTION],
	"images": [
		{
			"id": "img_8dfe0e39e18249b3b3a9cdb2904722f0",
			"url": "/files/golden-tee.png",
			"rank": None,
			"metadata": None,
			"created_at": None,
			"updated_at": None,
			"deleted_at": None,
		}
	],
	"external_id": None,
	"metadata": None,
	"created_at": "2026-01-15T08:30:00",
	"updated_at": "2026-02-20T17:45:12",
	"deleted_at": None,
}

_GOLDEN_ZEPHYR_SOCK = {
	"id": "prod_34240d77e32a783267d8ba6116d73a15",
	"title": "Golden Zephyr Sock",
	"handle": "golden-zephyr-sock",
	"subtitle": None,
	"description": "Golden zephyr sock description.",
	"is_giftcard": None,
	"discountable": None,
	"status": None,
	"thumbnail": "/files/golden-sock.png",
	"origin_country": "Thailand",
	"collection_id": None,
	"collection": None,
	"type_id": None,
	"type": None,
	"categories": [_GOLDEN_APPAREL_CATEGORY],
	"tags": [],
	"variants": [_GOLDEN_SOCK_VARIANT],
	"options": [],
	"images": [
		{
			"id": "img_2f602a7af20e54fc6948e827663d58a0",
			"url": "/files/golden-sock.png",
			"rank": None,
			"metadata": None,
			"created_at": None,
			"updated_at": None,
			"deleted_at": None,
		}
	],
	"external_id": None,
	"metadata": None,
	"created_at": "2026-01-15T08:30:00",
	"updated_at": "2026-02-20T17:45:12",
	"deleted_at": None,
}

#: ``GET /store/products?region_id=reg_test`` — the served assortment,
#: family first (item title order), with the pinned page echo.
GOLDEN_PRODUCT_LIST_BODY = {
	"products": [_GOLDEN_ANVIL_TEE, _GOLDEN_ZEPHYR_SOCK],
	"count": 2,
	"offset": 0,
	"limit": 50,
}

#: ``GET /store/products/{id}?region_id=reg_test`` — the identical projection
#: the list serves, under the pinned ``{"product": …}`` envelope.
GOLDEN_PRODUCT_DETAIL_BODY = {"product": _GOLDEN_ANVIL_TEE}

#: ``GET /store/product-variants?region_id=reg_test`` — the canonical
#: variants surface in item-code order (the standalone sock serves first),
#: with the pinned ``limit: 20`` echo.
GOLDEN_VARIANT_LIST_BODY = {
	"variants": [_GOLDEN_SOCK_VARIANT, _GOLDEN_BLACK_VARIANT, _GOLDEN_RED_VARIANT],
	"count": 3,
	"offset": 0,
	"limit": 20,
}

#: ``GET /store/product-options`` — the family's option with its published
#: values embedded, price-free by contract.
GOLDEN_OPTION_LIST_BODY = {
	"product_options": [_GOLDEN_COLOUR_OPTION],
	"count": 1,
	"offset": 0,
	"limit": 50,
}

#: ``GET /store/product-options/{id}`` — the identical projection the option
#: list serves, under the pinned ``{"product_option": …}`` envelope.
GOLDEN_OPTION_DETAIL_BODY = {"product_option": _GOLDEN_COLOUR_OPTION}
