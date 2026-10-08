"""Serialize an identity chain into the pinned ``StoreCustomer`` (Phase 0).

The public id comes from the ``Ceto Customer Reference``, the profile columns
from the ``Contact``, the identity email from the ``User`` and the timestamps
from the ``Customer`` (``docs/customers/field-mapping.md``). The ``addresses``
relation is always serialized — Ceto policy: the address book loads with the
customer — through the address book service, and the default ids are derived
from the flagged book entries (recorded decision 6).
"""

import json
from typing import TYPE_CHECKING, Any

import frappe

from ceto.routing.exceptions import InvalidDataError
from ceto.services.customers.addresses import default_address_id, serialize_book
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
			default_billing_address_id=default_address_id(identity.customer, "is_primary_address"),
			default_shipping_address_id=default_address_id(identity.customer, "is_shipping_address"),
			company_name=profile.company_name or None,
			first_name=profile.first_name or None,
			last_name=profile.last_name or None,
			phone=profile.phone or None,
			metadata=json.loads(reference.metadata) if reference.metadata else None,
			addresses=serialize_book(identity.customer, reference.name),
			created_at=created,
			updated_at=modified,
		)

	@staticmethod
	def select_fields(customer: dict[str, Any], fields: str | None) -> dict[str, Any]:
		"""Apply the pinned ``SelectParams`` selector to one serialized customer.

		The baseline is the fully serialized customer with its always-present
		``addresses`` relation (Ceto policy: the address book loads with the
		customer); plain and ``+``/``-``/``*`` tokens project on top of it,
		and an unknown field is rejected like every Ceto contract.
		"""
		if not fields:
			return customer

		tokens = [token.strip() for token in fields.split(",") if token.strip()]
		plain_fields = {CustomerSerializer._field_name(token) for token in tokens if token[0] not in "+-*"}
		selected = plain_fields or set(customer)
		for token in tokens:
			field = CustomerSerializer._field_name(token)
			if field not in customer:
				raise InvalidDataError(f"Unknown customer field: {field}")
			if token.startswith("-"):
				selected.discard(field)
			else:
				selected.add(field)
		return {key: value for key, value in customer.items() if key in selected}

	@staticmethod
	def _field_name(token: str) -> str:
		field = token.lstrip("+-*").split(".", 1)[0]
		if not field:
			raise InvalidDataError("Customer fields must not be empty")
		return field
