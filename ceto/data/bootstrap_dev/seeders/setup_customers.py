"""Seed the guest customer used for anonymous storefront checkouts."""

import frappe

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.settings import BootstrapSettings


class SetupCustomers(BaseImporter):
	"""Seed the Dev guest customer; identity is the ``customer_name`` field.

	Customer docnames depend on naming settings, so the bootstrap never relies
	on them: the guest is located by ``customer_name`` and any duplicate is
	reported as ambiguous instead of guessed at.
	"""

	def __init__(self, settings: BootstrapSettings) -> None:
		super().__init__()
		self.settings = settings

	def make(self) -> Report:
		settings = self.settings
		filters = {"customer_name": settings.guest_customer_name}
		label = f"guest customer '{settings.guest_customer_name}'"
		name = self.resolve_unique_name("Customer", filters, label)

		owned = {
			"customer_type": "Individual",
			"customer_group": settings.guest_customer_group,
			"territory": settings.guest_territory,
		}
		if name:
			doc = frappe.get_doc("Customer", name)
			self.update_and_record(doc, owned, "Customer", name)
		else:
			doc = frappe.new_doc("Customer")
			doc.customer_name = settings.guest_customer_name
			self.create_and_record(doc, owned, "Customer", settings.guest_customer_name)
		return self.report


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the guest customer seeder."""
	return SetupCustomers(settings or BootstrapSettings()).make()
