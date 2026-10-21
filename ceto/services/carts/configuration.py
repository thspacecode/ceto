from dataclasses import dataclass

import frappe

from ceto.config.cart import cart_settings, mapped_settings
from ceto.routing.exceptions import InvalidDataError


@dataclass(frozen=True)
class CartConfiguration:
	guest_customer: str
	company: str
	selling_price_list: str
	currency: str
	taxes_and_charges: str | None
	territory: str | None
	region_id: str | None
	sales_channel_id: str | None
	valid_for_days: int

	@classmethod
	def resolve(
		cls,
		*,
		region_id: str | None = None,
		sales_channel_id: str | None = None,
	) -> "CartConfiguration":
		settings = cart_settings()
		region_id = region_id or settings.get("default_region_id")
		sales_channel_id = sales_channel_id or settings.get("default_sales_channel_id")

		resolved = dict(settings)
		resolved.update(mapped_settings(settings, "regions", region_id, "region"))
		resolved.update(mapped_settings(settings, "sales_channels", sales_channel_id, "sales channel"))

		guest_customer = _required(resolved, "guest_customer")
		company = _required(resolved, "company")
		price_list = _required(resolved, "selling_price_list")
		currency = resolved.get("currency") or frappe.db.get_value("Price List", price_list, "currency")
		if not currency:
			raise InvalidDataError("Cart price list must have a currency")

		return cls(
			guest_customer=guest_customer,
			company=company,
			selling_price_list=price_list,
			currency=currency,
			taxes_and_charges=resolved.get("taxes_and_charges"),
			territory=resolved.get("territory"),
			region_id=region_id,
			sales_channel_id=sales_channel_id,
			valid_for_days=int(resolved.get("valid_for_days") or 30),
		)


def _required(settings: dict, key: str) -> str:
	value = settings.get(key)
	if not value:
		raise InvalidDataError(f"Missing ceto_cart.{key} configuration")
	return str(value)
