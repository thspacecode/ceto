"""Public ``cus_…`` identity and metadata for exactly one ERPNext Customer.

The gap layer of the customers contract (recorded decision 1 of
``docs/customers/field-mapping.md``): the public customer id is ``cus_`` plus
128 bits of cryptographic random, and it never exposes the ERPNext Customer
name. One-to-one by schema — the public id, the ``Customer`` and the owning
registration ``User`` are each unique across the table — and tied to the
pinned identity chain: the user's ``Contact`` (``Contact.user``) must link
exactly this Customer through a Dynamic Link, so a reference can only bless a
chain the identity resolver would accept.
"""

import json
import re
import secrets

import frappe
from frappe import _
from frappe.model.document import Document

CUSTOMER_ID_PATTERN = re.compile(r"^cus_[0-9a-f]{32}$")


def mint_customer_id() -> str:
	"""Mint a public customer id: ``cus_`` + 128 bits of cryptographic random."""
	return f"cus_{secrets.token_hex(16)}"


class CetoCustomerReference(Document):
	"""Stable public identity, owning registration user and metadata storage."""

	def validate(self) -> None:
		self._validate_customer_id()
		self._validate_identity_chain()
		self._validate_metadata()

	def _validate_customer_id(self) -> None:
		if not CUSTOMER_ID_PATTERN.match(self.customer_id or ""):
			frappe.throw(_("Customer ID must be 'cus_' followed by 32 hexadecimal characters"))

	def _validate_identity_chain(self) -> None:
		"""Require the User's Contact chain to link exactly this Customer."""
		contacts = frappe.get_all("Contact", filters={"user": self.user}, pluck="name")
		customers = set()
		if contacts:
			customers = set(
				frappe.get_all(
					"Dynamic Link",
					filters={
						"parenttype": "Contact",
						"parent": ["in", contacts],
						"link_doctype": "Customer",
					},
					pluck="link_name",
				)
			)
		if customers != {self.customer}:
			frappe.throw(_("Customer reference must match the User's linked Customer"))

	def _validate_metadata(self) -> None:
		if not self.metadata:
			return
		try:
			value = json.loads(self.metadata)
		except (TypeError, ValueError):
			frappe.throw(_("Customer metadata must be valid JSON"))
		if not isinstance(value, dict):
			frappe.throw(_("Customer metadata must be a JSON object"))
