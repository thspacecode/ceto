"""Apply a validated profile update to an already-resolved customer chain.

One ``StoreCustomer`` spans three records (recorded decision 2 of
``docs/customers/field-mapping.md``) and the update touches them in the same
shape the serializer reads them back from: the profile columns live on the
``Contact``, the display name is recomputed on the ``Customer`` and the
``Ceto Customer Reference`` carries the metadata. Resolution and
authorization belong to the caller — this service receives an already
resolved :class:`CustomerIdentity` and reference and only performs the
trusted persistence, inside :func:`privileged_scope` and the caller's
transaction, so a failing step rolls the whole update back.
"""

from typing import TYPE_CHECKING

import frappe

from ceto.services.common import merged_metadata, privileged_scope
from ceto.services.customers.creation import compose_customer_name
from ceto.services.customers.identity import CustomerIdentity
from ceto.types.http.store.customers import StoreUpdateCustomer

if TYPE_CHECKING:
	from frappe.model.document import Document


def update_customer(
	identity: CustomerIdentity,
	reference: "Document",
	payload: StoreUpdateCustomer,
) -> None:
	"""Apply the validated ``payload`` to the resolved chain and reference.

	Only the fields present on the validated payload move
	(``payload.model_fields_set``): an omitted field leaves its column
	untouched, while a present ``null`` — or a stripped empty string, which
	the pinned payload model already normalized to ``""`` — clears it.
	``first_name`` / ``last_name`` / ``company_name`` are Contact columns;
	``phone`` owns the Contact's primary phone slot instead of writing the
	derived ``Contact.phone`` column, which the Contact controller recomputes
	from the ``phone_nos`` primary flag on every save. ``metadata`` merges
	like on every public reference record (:func:`merged_metadata`): values
	merge per key, a ``null`` value removes a key and an explicit
	``metadata: null`` clears all keys.

	Every effective profile or metadata mutation also saves the Customer, so
	its ``modified`` — the contract's ``updated_at``
	(``docs/customers/field-mapping.md``) — advances; an empty payload or a
	no-op ``metadata`` change writes nothing at all. No row is locked: the
	standard optimistic ``modified`` check surfaces a lost race as a
	``frappe.TimestampMismatchError`` to translate normally at the boundary.
	"""
	fields = payload.model_fields_set

	def cleared_value(field: str) -> str | None:
		"""The validated value with clear semantics: an empty string clears."""
		return getattr(payload, field) or None

	def set_primary_phone(contact: "Document", phone: str | None) -> bool:
		"""Move the Contact's primary phone slot to ``phone`` (``None`` clears).

		The contract's phone is the primary ``phone_nos`` row: the derived
		``Contact.phone`` column is never written directly, the Contact
		controller derives it from the primary flag on every save. Ceto only
		owns the primary slot — a clear releases it (any other row, e.g. a
		CRM-managed number, survives) and a new value promotes the row that
		already carries it or appends it as the only primary.
		"""
		if (contact.phone or None) == phone:
			return False
		rows = contact.get("phone_nos") or []
		if phone is None:
			for row in rows:
				if row.is_primary_phone:
					contact.remove(row)
			return True
		promoted = None
		for row in rows:
			row.is_primary_phone = 0
			if row.phone == phone:
				promoted = row
		if promoted is None:
			contact.append("phone_nos", {"phone": phone, "is_primary_phone": 1})
		else:
			promoted.is_primary_phone = 1
		return True

	with privileged_scope():
		contact = frappe.get_doc("Contact", identity.contact)
		contact_changed = False
		for field in ("first_name", "last_name", "company_name"):
			if field not in fields:
				continue
			value = cleared_value(field)
			if (contact.get(field) or None) != value:
				contact.set(field, value)
				contact_changed = True
		if "phone" in fields and set_primary_phone(contact, cleared_value("phone")):
			contact_changed = True

		reference_changed = False
		if "metadata" in fields:
			merged = merged_metadata(reference.metadata, payload.metadata)
			if merged != (reference.metadata or None):
				reference.metadata = merged
				reference_changed = True

		if contact_changed:
			contact.save(ignore_permissions=True)
		if contact_changed or reference_changed:
			customer = frappe.get_doc("Customer", identity.customer)
			# The names on the (already applied) Contact compose the display
			# name with the identity email as fallback (recorded decision 2).
			# The save also advances ``modified`` — the contract's updated_at
			# — for every effective profile or metadata mutation.
			customer.customer_name = compose_customer_name(
				contact.first_name, contact.last_name, identity.user
			)
			customer.save(ignore_permissions=True)
		if reference_changed:
			reference.save(ignore_permissions=True)
