"""Seed selling rates for the development catalog."""

import frappe
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Cast_

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.dataset import ITEM_PRICES, ItemPriceSeed
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.exceptions import AmbiguousIdentityError, BootstrapError


class SetupItemPrices(BaseImporter):
	"""Seed deterministic, party-neutral selling rates on the Dev price list.

	The identity mirrors ERPNext's duplicate check. In particular, optional
	text fields may be stored as either NULL or an empty string, and an unset
	packing unit may be NULL or zero.
	"""

	def __init__(self, settings: BootstrapSettings, company: str) -> None:
		super().__init__()
		self.settings = settings
		self.company = company

	def make(self) -> Report:
		for seed in ITEM_PRICES:
			self.make_item_price(seed)
		return self.report

	def make_item_price(self, seed: ItemPriceSeed) -> None:
		price_list = self.settings.selling_price_list
		stock_uom = frappe.db.get_value("Item", seed.item_code, "stock_uom")
		if not stock_uom:
			msg = f"Item {seed.item_code} not found; run the item seeder first."
			frappe.throw(msg, BootstrapError)

		owned = {"price_list_rate": seed.price_list_rate}
		label = f"Dev selling rate for {seed.item_code} on {price_list}"
		name = self.resolve_item_price(price_list, seed.item_code, stock_uom, label)

		if name:
			doc = frappe.get_doc("Item Price", name)
			self.update_and_record(doc, owned, "Item Price", label)
		else:
			doc = frappe.new_doc("Item Price")
			doc.price_list = price_list
			doc.item_code = seed.item_code
			doc.uom = stock_uom
			# Pin every ERPNext duplicate-key dimension. valid_from otherwise
			# defaults to Today during insert and changes the identity every day.
			doc.valid_from = self.settings.item_price_valid_from
			doc.valid_upto = None
			doc.customer = None
			doc.supplier = None
			doc.batch_no = None
			doc.packing_unit = 0
			self.create_and_record(doc, owned, "Item Price", label)

	def resolve_item_price(self, price_list: str, item_code: str, stock_uom: str, label: str) -> str | None:
		"""Resolve the exact bootstrap rate without adopting user-owned prices."""
		item_price = frappe.qb.DocType("Item Price")
		condition = (
			(item_price.price_list == price_list)
			& (item_price.item_code == item_code)
			& (item_price.uom == stock_uom)
			& (item_price.valid_from == self.settings.item_price_valid_from)
			& self.unset_text(item_price.valid_upto)
			& self.unset_text(item_price.customer)
			& self.unset_text(item_price.supplier)
			& self.unset_text(item_price.batch_no)
			& Criterion.any([item_price.packing_unit.isnull(), item_price.packing_unit == 0])
		)
		names = frappe.qb.from_(item_price).select(item_price.name).where(condition).run(pluck=True)
		if len(names) > 1:
			msg = f"{label} matched {len(names)} Item Price records: {', '.join(sorted(names))}"
			raise AmbiguousIdentityError(msg)
		return names[0] if names else None

	@staticmethod
	def unset_text(field):
		"""Match ERPNext's representation of an unset optional text field."""
		return Criterion.any([field.isnull(), Cast_(field, "varchar") == ""])


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the item price seeder."""
	resolved = settings or BootstrapSettings()
	return SetupItemPrices(resolved, resolve_company(resolved)).make()
