"""Transport-independent CRUD/list service for the customer address book.

The address-book half of the customers contract (routes 4-8 of
``docs/customers/endpoints.md``). Every entry is a customer-linked ERPNext
``Address``: the public id **is** the ``Address`` name — API-created entries
mint Ceto's stable ``addr_…`` naming while pre-existing customer Addresses
surface under their existing names (recorded decision 5 of
``docs/customers/field-mapping.md``) — and the pinned optional ``metadata``
object lives in the ``Ceto Customer Address Reference`` gap layer (recorded
decision 4). The default flags stay the ERPNext checkboxes, exclusive per
customer (recorded decision 6), and deletion mirrors the soft-delete
semantics of recorded decision 9 through the normal ERPNext integrity.

Every operation first resolves the caller's identity chain through the
shared resolver
(:func:`ceto.services.customers.identity.resolve_customer_reference`) — a
chain that cannot resolve is refused with ``401 unauthorized`` before any
privileged write — and only then performs trusted persistence inside
:func:`ceto.services.common.privileged_scope` and the caller's transaction.
Ownership is read exclusively from the ``Address`` ↔ ``Customer`` Dynamic
Link; a missing, foreign or disabled entry is masked as the same
``404 not_found`` (:class:`ceto.routing.exceptions.RouteNotFoundError`) so a
response never confirms which addresses exist.

The address-owned response shapes (retrieve/list) come back as projected
response bodies; the create/update/delete responses are the parent customer,
which the route serializes from the returned ``(identity, reference)`` pair
through the ``CustomerSerializer`` — the same boundary split the profile
routes use.
"""

from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING

import frappe

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError
from ceto.services.addresses import is_customer_address, resolve_country
from ceto.services.common import dump_metadata, merged_metadata, privileged_scope
from ceto.services.customers.identity import CustomerIdentity, resolve_customer_reference
from ceto.types.http.store.customers import StoreCustomerAddress

if TYPE_CHECKING:
	from ceto.types.http.store.customers import (
		StoreCreateCustomerAddress,
		StoreCustomerAddressFilters,
		StoreUpdateCustomerAddress,
	)

#: Ceto policy: the pinned address payloads carry no ERPNext address type.
ADDRESS_TYPE = "Billing"

_MASKED_404 = "No customer address exists at this id"
_DEFAULT_LIMIT = 20
_DEFAULT_ORDER = "creation asc, name asc"

#: The ``q`` search sweeps the label and the street/city columns.
_SEARCH_FIELDS = ("address_title", "address_line1", "address_line2", "city")

_LABEL_FIELDS = frozenset({"address_name", "first_name", "last_name", "company"})
_REQUIRED_TEXT_FIELDS = frozenset({"address_1", "city"})

#: (payload field, Address column) for the direct text columns.
_TEXT_COLUMNS = {
	"address_1": "address_line1",
	"address_2": "address_line2",
	"city": "city",
	"province": "state",
	"postal_code": "pincode",
	"phone": "phone",
}

#: (payload field, Address column) for the exclusive per-customer defaults.
_DEFAULT_FLAG_SLOTS = (
	("is_default_billing", "is_primary_address"),
	("is_default_shipping", "is_shipping_address"),
)

#: The pinned ``order`` tokens and the Address columns they may sort by.
_ORDER_COLUMNS = {
	"id": "name",
	"created_at": "creation",
	"updated_at": "modified",
	"address_name": "address_title",
	"city": "city",
	"postal_code": "pincode",
}


def mint_address_id() -> str:
	"""Mint a public address id: ``addr_`` + 128 bits of cryptographic random.

	The same shape as the ``cus_…``/``cart_…`` ids; it names the ERPNext
	``Address`` itself so the public id stays stable across reads without
	leaking ERPNext's configurable naming (recorded decision 5).
	"""
	return f"addr_{secrets.token_hex(16)}"


class AddressBookSerializer:
	"""Build the pinned ``StoreCustomerAddress`` from one address book entry."""

	#: The label trio collapses into ``address_title`` and never serializes a
	#: value back, so the pinned selector refuses it like an unknown field.
	_COLLAPSED_FIELDS = frozenset({"first_name", "last_name", "company"})

	@staticmethod
	def serialize(address, customer_id: str, metadata: dict | None = None) -> StoreCustomerAddress:
		"""Return the pinned address entity for the loaded ``Address`` doc.

		``customer_id`` is the owning customer's public ``cus_…`` id (recorded
		decision 5) and ``metadata`` the decoded reference metadata.
		``first_name`` / ``last_name`` / ``company`` have no dedicated ERPNext
		columns — they collapse into ``address_title`` — so only
		``address_name`` serializes back, exactly like the cart serializer.
		"""
		country_code = frappe.db.get_value("Country", address.country, "code") if address.country else None
		return StoreCustomerAddress(
			id=address.name,
			customer_id=customer_id,
			is_default_shipping=bool(address.is_shipping_address),
			is_default_billing=bool(address.is_primary_address),
			address_name=address.address_title or None,
			phone=address.phone or None,
			address_1=address.address_line1 or None,
			address_2=address.address_line2 or None,
			city=address.city or None,
			province=address.state or None,
			postal_code=address.pincode or None,
			country_code=country_code.lower() if country_code else None,
			metadata=metadata,
			created_at=address.creation,
			updated_at=address.modified,
		)

	@staticmethod
	def select_fields(address: dict, fields: str | None) -> dict:
		"""Apply the pinned ``SelectParams`` selector to one serialized address.

		Plain and ``+``/``-``/``*`` tokens project on top of the fully
		serialized entry; the collapsed label trio and an unknown field are
		refused like every Ceto contract.
		"""
		if not fields:
			return address

		tokens = [token.strip() for token in fields.split(",") if token.strip()]
		plain_fields = {AddressBookSerializer._field_name(token) for token in tokens if token[0] not in "+-*"}
		selected = plain_fields or set(address)
		for token in tokens:
			field = AddressBookSerializer._field_name(token)
			if field in AddressBookSerializer._COLLAPSED_FIELDS:
				raise InvalidDataError(f"Address field collapses into address_name: {field}")
			if field not in address:
				raise InvalidDataError(f"Unknown address field: {field}")
			if token.startswith("-"):
				selected.discard(field)
			else:
				selected.add(field)
		return {key: value for key, value in address.items() if key in selected}

	@staticmethod
	def _field_name(token: str) -> str:
		field = token.lstrip("+-*").split(".", 1)[0]
		if not field:
			raise InvalidDataError("Address fields must not be empty")
		return field


def book_names(customer: str) -> list[str]:
	"""The customer's enabled entry names in the deterministic book order."""
	return frappe.get_all(
		"Address",
		filters=_book_filters(customer),
		pluck="name",
		order_by=_DEFAULT_ORDER,
	)


def serialize_book(customer: str, customer_id: str) -> list[StoreCustomerAddress]:
	"""Serialize the enabled book of ``customer`` in the deterministic order.

	The read behind the always-serialized ``addresses`` relation of the
	customer serializer (Ceto policy: the address book loads with the
	customer): the bounded per-user list resolves once — names, then the
	metadata map — and every entry goes through the address serializer.
	"""
	names = book_names(customer)
	metadata = _metadata_map(names)
	return [
		AddressBookSerializer.serialize(frappe.get_doc("Address", name), customer_id, metadata.get(name))
		for name in names
	]


def default_address_id(customer: str, flag_column: str) -> str | None:
	"""The public id of the enabled entry holding ``flag_column``; else ``None``.

	The derived ``default_billing_address_id`` / ``default_shipping_address_id``
	of the customer serializer (recorded decision 6): the flagged row of the
	enabled book — the first in the deterministic order should legacy data
	ever carry two flags of one kind.
	"""
	names = frappe.get_all(
		"Address",
		filters=[*_book_filters(customer), [flag_column, "=", 1]],
		pluck="name",
		order_by=_DEFAULT_ORDER,
	)
	return names[0] if names else None


def _book_filters(customer: str) -> list[list[str]]:
	"""The enabled ``Address`` ↔ ``Customer`` Dynamic Link book membership."""
	return [
		["disabled", "=", 0],
		["Dynamic Link", "parenttype", "=", "Address"],
		["Dynamic Link", "link_doctype", "=", "Customer"],
		["Dynamic Link", "link_name", "=", customer],
	]


def create_address(user: str, payload: StoreCreateCustomerAddress) -> tuple[CustomerIdentity, object]:
	"""Append one validated payload as an entry of ``user``'s address book.

	The identity resolves first (``401 unauthorized`` before any privileged
	write); then the pinned core columns are required, the ISO ``country_code``
	resolves through the shared helper and the entry is created inside the
	caller's transaction with Ceto's stable ``addr_…`` public name, exactly
	one Dynamic Link — the owning ``Customer``, never a Quotation or Contact
	(recorded decision 5) — and its ``Ceto Customer Address Reference`` for
	the metadata. Setting a default flag here clears the previous per-customer
	holder through the normal Address controller. Returns the resolved
	``(identity, reference)`` pair for the parent-customer serialization.
	"""
	identity, reference = resolve_customer_reference(user)
	_require(payload.address_1, "address_1")
	_require(payload.city, "city")
	country = _resolved_country(payload.country_code)
	label = _label(payload.address_name, payload.first_name, payload.last_name, payload.company)
	with privileged_scope():
		address = frappe.new_doc("Address")
		address.address_type = ADDRESS_TYPE
		address.address_title = label
		address.address_line1 = payload.address_1
		address.address_line2 = payload.address_2
		address.city = payload.city
		address.state = payload.province
		address.pincode = payload.postal_code
		address.country = country
		address.phone = payload.phone
		address.is_primary_address = int(bool(payload.is_default_billing))
		address.is_shipping_address = int(bool(payload.is_default_shipping))
		address.append("links", {"link_doctype": "Customer", "link_name": identity.customer})
		address.insert(ignore_permissions=True, set_name=mint_address_id())
		_store_metadata(address, identity, dump_metadata(payload.metadata))
	return identity, reference


def retrieve_address(user: str, address_id: str, fields: str | None = None) -> dict:
	"""Return one owned entry serialized to the pinned entity, then projected.

	The identity resolves first; a missing, foreign or disabled entry is
	masked as the same ``404 not_found``.
	"""
	identity, reference = resolve_customer_reference(user)
	address = _owned_address(address_id, identity.customer)
	entry = AddressBookSerializer.serialize(address, reference.name, _metadata_of(address.name))
	return AddressBookSerializer.select_fields(entry.model_dump(mode="json"), fields)


def update_address(
	user: str, address_id: str, payload: StoreUpdateCustomerAddress
) -> tuple[CustomerIdentity, object]:
	"""Apply the validated partial update to one owned entry.

	Only the fields present on the validated payload move
	(``payload.model_fields_set``): an omitted field leaves its column
	untouched, a present ``null`` — or a stripped empty string, which the
	pinned payload model already normalized to ``""`` — clears it. Clearing a
	pinned core column (``address_1``, ``city``, ``country_code``) is refused
	with ``400 invalid_data``. The label recomposes only when the payload
	supplies a label field: a supplied ``address_name`` wins over the supplied
	names over the supplied company (recorded decision 5 mapping). Metadata
	merges through the reference like on every public record. A no-op payload
	writes nothing; every effective change saves the entry inside the
	caller's transaction, so its ``modified`` — the contract's ``updated_at``
	— advances. Returns the resolved ``(identity, reference)`` pair.
	"""
	identity, reference = resolve_customer_reference(user)
	address = _owned_address(address_id, identity.customer)
	fields = payload.model_fields_set
	with privileged_scope():
		changed = _apply_columns(address, payload, fields)
		changed = _apply_flags(address, payload, fields) or changed
		changed = _apply_metadata(address, identity, payload, fields) or changed
		if changed:
			address.save(ignore_permissions=True)
	return identity, reference


def delete_address(user: str, address_id: str) -> tuple[CustomerIdentity, object]:
	"""Remove one owned entry from the address book (recorded decision 9).

	The identity resolves first. The customer's ERPNext default-address slot
	is released when it names the entry, then the entry is destroyed through
	the normal ERPNext delete — static links from placed orders and
	quotations raise ``LinkExistsError``, and the entry is retained instead;
	the link check is never bypassed. An entry another Customer still owns is
	retained untouched for that owner and only unlinked from this book, and
	its reference record is dropped either way so the entry ``404``s here
	afterwards. The unlink removes the Dynamic Link rows directly, so a
	retained entry leaves the book even when the Address controller's
	owner-based relink would re-attach the customer's own link on a save.
	Returns the resolved ``(identity, reference)`` pair.
	"""
	identity, reference = resolve_customer_reference(user)
	address = _owned_address(address_id, identity.customer)
	with privileged_scope():
		_clear_default_slot(address, identity.customer)
		destroyed = False
		if _sole_owner(address, identity.customer):
			_drop_reference(address.name)
			destroyed = _destroy(address)
		if not destroyed:
			_unlink_customer(address, identity.customer)
			_drop_reference(address.name)
	return identity, reference


def list_addresses(user: str, query: StoreCustomerAddressFilters) -> dict:
	"""Return the pinned paginated address-book body for ``user``.

	The window is Ceto policy: ``offset`` defaults to 0 and ``limit`` to 20
	with a maximum of 100 (validated by the pinned query model); the body
	always reports the applied ``count`` / ``offset`` / ``limit`` and never an
	estimate. ``with_deleted`` is a validated no-op (Ceto keeps no soft-deleted
	address surface). The customer's enabled entries — including pre-existing
	ones under their existing names (recorded decision 5) — are filtered
	(``q``, ``city``, ``country_code``, ``postal_code``), ordered
	deterministically (``order`` plus a stable name tiebreak) and the page
	rows are projected through the pinned ``fields`` selector. The book of one
	customer is a bounded per-user list, so the matching names are resolved
	once and the window slices them.
	"""
	identity, reference = resolve_customer_reference(user)
	names = _matching_address_names(identity.customer, query)
	offset = query.offset or 0
	limit = query.limit or _DEFAULT_LIMIT
	page = names[offset : offset + limit]
	metadata = _metadata_map(page)
	rows = [
		AddressBookSerializer.select_fields(
			AddressBookSerializer.serialize(
				frappe.get_doc("Address", name), reference.name, metadata.get(name)
			).model_dump(mode="json"),
			query.fields,
		)
		for name in page
	]
	return {"addresses": rows, "count": len(names), "offset": offset, "limit": limit}


def _require(value: str | None, field: str) -> None:
	if not value:
		raise InvalidDataError(f"Address {field} is required")


def _resolved_country(country_code: str | None) -> str:
	"""Resolve the pinned ISO code through the shared helper; it is required."""
	if not country_code:
		raise InvalidDataError("Address country_code is required")
	return resolve_country(country_code)


def _label(
	address_name: str | None, first_name: str | None, last_name: str | None, company: str | None
) -> str | None:
	"""The stored label per the mapping: address_name, then names, then company."""
	return address_name or " ".join(part for part in (first_name, last_name) if part) or company or None


def _owned_address(address_id: str, customer: str):
	"""Load the enabled entry of ``customer``; everything else is the mask.

	A missing, foreign (no ``Customer`` Dynamic Link to ``customer``) or
	disabled address raises the same :class:`RouteNotFoundError`, so a
	response never confirms which addresses exist.
	"""
	try:
		address = frappe.get_doc("Address", address_id)
	except frappe.DoesNotExistError:
		raise RouteNotFoundError(_MASKED_404) from None
	if address.disabled or not is_customer_address(address.name, customer):
		raise RouteNotFoundError(_MASKED_404)
	return address


def _apply_columns(address, payload: StoreUpdateCustomerAddress, fields: set[str]) -> bool:
	"""Move the supplied text, country and label fields; True when one moved."""
	changed = False
	for payload_field, column in _TEXT_COLUMNS.items():
		if payload_field not in fields:
			continue
		value = getattr(payload, payload_field) or None
		if not value and payload_field in _REQUIRED_TEXT_FIELDS:
			raise InvalidDataError(f"Address {payload_field} is required")
		if (address.get(column) or None) != value:
			address.set(column, value)
			changed = True
	if "country_code" in fields:
		country = _resolved_country(payload.country_code)
		if address.country != country:
			address.country = country
			changed = True
	if _LABEL_FIELDS & fields:
		label = _label(payload.address_name, payload.first_name, payload.last_name, payload.company)
		if (address.address_title or None) != label:
			address.address_title = label
			changed = True
	return changed


def _apply_flags(address, payload: StoreUpdateCustomerAddress, fields: set[str]) -> bool:
	"""Move the supplied default flags; the controller clears the old holder."""
	changed = False
	for payload_field, column in _DEFAULT_FLAG_SLOTS:
		if payload_field not in fields:
			continue
		value = int(bool(getattr(payload, payload_field)))
		if int(address.get(column) or 0) != value:
			address.set(column, value)
			changed = True
	return changed


def _apply_metadata(
	address, identity: CustomerIdentity, payload: StoreUpdateCustomerAddress, fields: set[str]
) -> bool:
	"""Merge/clear the metadata through the reference; True when it moved."""
	if "metadata" not in fields:
		return False
	stored = frappe.db.get_value("Ceto Customer Address Reference", address.name, "metadata")
	merged = merged_metadata(stored, payload.metadata)
	if merged == (stored or None):
		return False
	_store_metadata(address, identity, merged)
	return True


def _store_metadata(address, identity: CustomerIdentity, metadata: str | None) -> None:
	"""Write ``metadata`` onto the entry's one reference record, creating it on demand."""
	name = frappe.db.get_value("Ceto Customer Address Reference", address.name)
	if name:
		record = frappe.get_doc("Ceto Customer Address Reference", name)
		record.metadata = metadata
		record.save(ignore_permissions=True)
		return
	record = frappe.new_doc("Ceto Customer Address Reference")
	record.address = address.name
	record.customer = identity.customer
	record.metadata = metadata
	record.insert(ignore_permissions=True)


def _clear_default_slot(address, customer: str) -> None:
	"""Release the Customer's ERPNext default slot when it names this entry.

	Recorded decision 9: the customer's default slot must not pin a deleted
	address. A peer whose slot drifted onto the entry keeps it — the normal
	ERPNext link check then retains the entry instead.
	"""
	if frappe.db.get_value("Customer", customer, "customer_primary_address") != address.name:
		return
	frappe.db.set_value("Customer", customer, "customer_primary_address", None)
	frappe.db.set_value("Customer", customer, "primary_address", None)


def _sole_owner(address, customer: str) -> bool:
	"""Whether ``customer`` is the entry's only ``Customer`` Dynamic Link owner."""
	return not frappe.db.exists(
		"Dynamic Link",
		{
			"parenttype": "Address",
			"parent": address.name,
			"link_doctype": "Customer",
			"link_name": ["!=", customer],
		},
	)


def _destroy(address) -> bool:
	"""Destroy through the normal ERPNext delete; False when links retain it."""
	try:
		frappe.delete_doc("Address", address.name, ignore_permissions=True)
	except frappe.LinkExistsError:
		return False
	return True


def _unlink_customer(address, customer: str) -> None:
	"""Remove this customer's Dynamic Link rows so the entry leaves the book.

	The rows are removed at the database level instead of saving the entry:
	saving runs the Address controller's owner-based ``link_address()``,
	which re-attaches the links of the Contact carrying the entry owner's
	email — for a legacy entry owned by the customer's own user that is
	exactly the Customer link being removed, so the unlink would undo itself
	and the entry would stay in the book behind a ``deleted: true``. Static
	links are untouched — the normal ERPNext link check keeps the entry
	retained — and no controller behavior changes for any other save.
	"""
	frappe.db.delete(
		"Dynamic Link",
		{
			"parenttype": "Address",
			"parent": address.name,
			"parentfield": "links",
			"link_doctype": "Customer",
			"link_name": customer,
		},
	)


def _drop_reference(address_name: str) -> None:
	"""Delete the reference record naming the entry: book membership ends.

	The record names the Address through a Link field, so it must go before
	the Address itself or the normal delete would be blocked by Ceto's own
	gap layer.
	"""
	if frappe.db.exists("Ceto Customer Address Reference", address_name):
		frappe.delete_doc("Ceto Customer Address Reference", address_name, ignore_permissions=True)


def _matching_address_names(customer: str, query: StoreCustomerAddressFilters) -> list[str]:
	"""The customer's enabled entry names matching the query, ordered."""
	filters = _book_filters(customer)
	if query.city:
		filters.append(["city", "=", query.city])
	if query.postal_code:
		filters.append(["pincode", "=", query.postal_code])
	if query.country_code:
		filters.append(["country", "=", resolve_country(query.country_code)])
	return frappe.get_all(
		"Address",
		filters=filters,
		or_filters=_q_filters(query.q),
		pluck="name",
		order_by=_order_clause(query.order),
	)


def _q_filters(q: str | None) -> list[list[str]]:
	"""Case-insensitive substring filters for the ``q`` search term."""
	if not q:
		return []
	return [[field, "like", f"%{q}%"] for field in _SEARCH_FIELDS]


def _order_clause(order: str | None) -> str:
	"""Translate the pinned ``order`` token into a deterministic clause.

	Unknown or empty field names are rejected; every clause carries the
	``name`` tiebreak so equal sort keys keep a stable order.
	"""
	if not order or not order.strip():
		return _DEFAULT_ORDER
	token = order.strip()
	field = token.lstrip("+-")
	if not field:
		raise InvalidDataError("Address order must name a field")
	column = _ORDER_COLUMNS.get(field)
	if not column:
		raise InvalidDataError(f"Unknown address order field: {field}")
	direction = "desc" if token[0] == "-" else "asc"
	return f"{column} {direction}, name asc"


def _metadata_of(address_name: str) -> dict | None:
	stored = frappe.db.get_value("Ceto Customer Address Reference", address_name, "metadata")
	return json.loads(stored) if stored else None


def _metadata_map(names: list[str]) -> dict[str, dict | None]:
	"""The decoded reference metadata of ``names``, resolved in one query."""
	if not names:
		return {}
	rows = frappe.get_all(
		"Ceto Customer Address Reference",
		filters={"address": ["in", names]},
		fields=["address", "metadata"],
	)
	return {row.address: (json.loads(row.metadata) if row.metadata else None) for row in rows}
