"""Serialize an identity chain into the pinned ``StoreCustomer`` (Phase 0).

The public id comes from the ``Ceto Customer Reference``, the profile columns
from the ``Contact``, the identity email from the ``User`` and the timestamps
from the ``Customer`` (``docs/customers/field-mapping.md``). The ``addresses``
relation is always serialized — Ceto policy: the address book loads with the
customer — and stays empty until the address-book phase delivers
customer-linked Addresses.
"""

import json
from typing import TYPE_CHECKING

import frappe

from ceto.services.customers.identity import CustomerIdentity
from ceto.types.http.store.customers import StoreCustomer

if TYPE_CHECKING:
	from frappe.model.document import Document


class CustomerSerializer:
	"""Build the pinned ``StoreCustomer`` from an identity chain and its reference."""

	@staticmethod
	def serialize(identity: CustomerIdentity, reference: "Document") -> StoreCustomer:
		"""Return the pinned customer entity for ``identity``.

		``reference`` is the ``Ceto Customer Reference`` that names the
		public ``cus_…`` id and carries the metadata; without it no
		contract-safe public id exists, so callers must always resolve the
		reference first.
		"""
		profile = frappe.db.get_value(
			"Contact",
			identity.contact,
			["first_name", "last_name", "company_name", "phone"],
			as_dict=True,
		)
		created, modified = frappe.db.get_value("Customer", identity.customer, ["creation", "modified"])
		return StoreCustomer(
			id=reference.name,
			email=frappe.db.get_value("User", identity.user, "email"),
			company_name=profile.company_name or None,
			first_name=profile.first_name or None,
			last_name=profile.last_name or None,
			phone=profile.phone or None,
			metadata=json.loads(reference.metadata) if reference.metadata else None,
			created_at=created,
			updated_at=modified,
		)
