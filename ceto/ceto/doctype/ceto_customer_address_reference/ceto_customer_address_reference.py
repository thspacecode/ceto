"""Metadata storage for exactly one customer-owned ERPNext Address.

The gap layer of the address-book contract (recorded decisions 4 and 5 of
``docs/customers/field-mapping.md``): the public address id is the ERPNext
``Address`` name itself, so the reference is named by it, and the pinned
optional ``metadata`` object of an address has no ERPNext equivalent — it
lives here, one-to-one onto the address. Validation blesses only a
customer-owned address, mirroring ``Ceto Customer Reference``: the
``Address`` must link exactly ``customer`` through its ``Customer`` Dynamic
Links, so another party's address can never gain a reference.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document


class CetoCustomerAddressReference(Document):
	"""Address-keyed metadata storage for one customer-linked Address."""

	def validate(self) -> None:
		self._validate_address_ownership()
		self._validate_metadata()

	def _validate_address_ownership(self) -> None:
		"""Require the Address's Customer Dynamic Links to name exactly ``customer``."""
		customers = set(
			frappe.get_all(
				"Dynamic Link",
				filters={
					"parenttype": "Address",
					"parent": self.address,
					"link_doctype": "Customer",
				},
				pluck="link_name",
			)
		)
		if customers != {self.customer}:
			frappe.throw(_("Customer address reference must match the Address's linked Customer"))

	def _validate_metadata(self) -> None:
		if not self.metadata:
			return
		try:
			value = json.loads(self.metadata)
		except (TypeError, ValueError):
			frappe.throw(_("Customer address metadata must be valid JSON"))
		if not isinstance(value, dict):
			frappe.throw(_("Customer address metadata must be a JSON object"))
