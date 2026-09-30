"""Seed a zero-rated sales taxes template when the site can support one safely."""

import frappe
from frappe.model.document import Document

from ceto.data.base_importer import BaseImporter, Report, apply_values, values_differ
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.data.bootstrap_dev.settings import BootstrapSettings


class SetupTaxes(BaseImporter):
	"""Seed the Dev sales taxes template; a template is master data, not a posting.

	With a 0% rate nothing reaches the ledger even if the template is applied
	to a transaction. The template is only written when the company exposes
	exactly one leaf Tax account; otherwise a note explains why it was skipped
	and no guess is made.
	"""

	def __init__(self, settings: BootstrapSettings, company: str) -> None:
		super().__init__()
		self.settings = settings
		self.company = company

	def make(self) -> Report:
		account = self.resolve_tax_account()
		if not account:
			return self.report

		expected_rows = [
			{
				"charge_type": "On Net Total",
				"account_head": account,
				"rate": self.settings.tax_rate,
				"description": self.settings.sales_taxes_template_title,
			}
		]
		filters = {"title": self.settings.sales_taxes_template_title, "company": self.company}
		label = f"sales taxes template '{self.settings.sales_taxes_template_title}'"
		name = self.resolve_unique_name("Sales Taxes and Charges Template", filters, label)

		if name:
			doc = frappe.get_doc("Sales Taxes and Charges Template", name)
			changed = apply_values(doc, {"is_default": 0, "disabled": 0})
			changed = self.apply_taxes_rows(doc, expected_rows) or changed
			if changed:
				doc.save()
				self.record_change("updated", "Sales Taxes and Charges Template", label)
			else:
				self.record_change("skipped", "Sales Taxes and Charges Template", label)
		else:
			doc = frappe.new_doc("Sales Taxes and Charges Template")
			doc.title = self.settings.sales_taxes_template_title
			doc.company = self.company
			doc.is_default = 0
			doc.disabled = 0
			for row in expected_rows:
				doc.append("taxes", row)
			doc.insert()
			self.record_change("created", "Sales Taxes and Charges Template", label)
		return self.report

	def resolve_tax_account(self) -> str:
		"""Return the company's single leaf Tax account, or explain why there is none."""
		filters = {"company": self.company, "account_type": "Tax", "is_group": 0}
		names = frappe.get_all("Account", filters=filters, pluck="name")
		if not names:
			self.record_note(
				f"Company {self.company} has no leaf Tax account; sales taxes template not seeded."
			)
			return ""
		if len(names) > 1:
			self.record_note(
				f"Company {self.company} has {len(names)} leaf Tax accounts; "
				"sales taxes template not seeded because the target account is ambiguous."
			)
			return ""
		return names[0]

	def apply_taxes_rows(self, doc: Document, expected_rows: list[dict]) -> bool:
		"""Converge the template's tax rows onto the expected single row."""
		if len(doc.taxes) == len(expected_rows) and all(
			not any(values_differ(row.get(fieldname), value) for fieldname, value in expected.items())
			for row, expected in zip(doc.taxes, expected_rows, strict=True)
		):
			return False

		doc.taxes = []
		for expected in expected_rows:
			doc.append("taxes", expected)
		return True


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the sales taxes template seeder."""
	resolved = settings or BootstrapSettings()
	return SetupTaxes(resolved, resolve_company(resolved)).make()
