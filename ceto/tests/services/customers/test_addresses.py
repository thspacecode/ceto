"""The customer address book service against the test site.

Pins the transport-independent CRUD/list surface on real records: the
identity resolves before any privileged write, ownership follows only the
``Address`` ↔ ``Customer`` Dynamic Link with missing/foreign/disabled masked
alike as ``404 not_found``, creates mint the stable ``addr_…`` public name
with exactly the Customer link, updates move only ``model_fields_set``,
metadata merges through the ``Ceto Customer Address Reference``, the default
flags stay exclusive per customer, listing paginates and filters
deterministically, and deletion keeps the normal ERPNext integrity —
retaining (unlinked) entries that legitimate references or other owners
still need. Each test rolls back.
"""

import json
import uuid

import frappe

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError, UnauthorizedError
from ceto.services.addresses import is_customer_address
from ceto.services.customers.addresses import (
	create_address,
	delete_address,
	list_addresses,
	retrieve_address,
	update_address,
)
from ceto.services.customers.creation import create_customer_profile
from ceto.tests.data.customer_test_data import (
	THROTTLE_USER_LIMIT,
	make_customer,
	new_identity,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.customers import (
	StoreCreateCustomerAddress,
	StoreCustomerAddressFilters,
	StoreUpdateCustomerAddress,
)

_ADDRESS_ROW_FIELDS = (
	"address_type",
	"address_title",
	"address_line1",
	"address_line2",
	"city",
	"state",
	"pincode",
	"country",
	"phone",
	"is_primary_address",
	"is_shipping_address",
	"disabled",
)


class TestCustomerAddressBook(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			self.email = new_identity("addresses")
			self.identity, self.reference = create_customer_profile(self.email)

	def _payload(self, **overrides) -> StoreCreateCustomerAddress:
		values = {"address_1": "1 Harbor Way", "city": "Portland", "country_code": "us"}
		values.update(overrides)
		return StoreCreateCustomerAddress(**values)

	def _book(self, customer: str) -> list[str]:
		"""The customer's enabled entry names, independent of the service query."""
		return frappe.get_all(
			"Address",
			filters=[
				["disabled", "=", 0],
				["Dynamic Link", "parenttype", "=", "Address"],
				["Dynamic Link", "link_doctype", "=", "Customer"],
				["Dynamic Link", "link_name", "=", customer],
			],
			pluck="name",
			order_by="creation asc, name asc",
		)

	def _create(self, identity=None, **overrides) -> str:
		"""Create through the service; return the new entry's public id."""
		identity = identity or self.identity
		before = set(self._book(identity.customer))
		create_address(identity.user, self._payload(**overrides))
		return (set(self._book(identity.customer)) - before).pop()

	def _peer(self) -> tuple:
		"""A second resolved profile; created lazily, cached for the test."""
		if not hasattr(self, "_peer_profile"):
			with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
				self._peer_profile = create_customer_profile(new_identity("address-peer"))
		return self._peer_profile

	def _row(self, name: str) -> dict:
		return frappe.db.get_value("Address", name, list(_ADDRESS_ROW_FIELDS), as_dict=True)

	def _flag(self, name: str, column: str) -> int:
		return int(frappe.db.get_value("Address", name, column) or 0)

	def _modified(self, name: str) -> str:
		return frappe.db.get_value("Address", name, "modified")

	def _stored_metadata(self, name: str) -> dict | None:
		stored = frappe.db.get_value("Ceto Customer Address Reference", name, "metadata")
		return json.loads(stored) if stored else None

	def _legacy_address(self, title: str | None = None) -> str:
		"""A pre-existing customer-linked Address named by ERPNext, not Ceto."""
		doc = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": "Billing",
				"address_line1": "9 Founders Row",
				"city": "Portland",
				"country": "United States",
				"links": [{"link_doctype": "Customer", "link_name": self.identity.customer}],
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc.name

	def _quotation_referencing(self, address_name: str) -> str:
		"""A Quotation statically linked to the entry, like a placed order."""
		item_code = f"CETO-ADDR-{uuid.uuid4().hex[:8]}"
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name", order_by="name"),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		quotation = frappe.get_doc(
			{
				"doctype": "Quotation",
				"company": frappe.get_all("Company", pluck="name")[0],
				"quotation_to": "Customer",
				"party_name": self.identity.customer,
				"order_type": "Sales",
				"customer_address": address_name,
				"items": [{"item_code": item_code, "qty": 1, "rate": 10}],
			}
		)
		quotation.insert(ignore_permissions=True)
		return quotation.name

	# ------------------------------------------------------------------ gate

	def test_unresolvable_identities_are_refused_before_any_write(self) -> None:
		email = new_identity("address-stranger")
		before = frappe.db.count("Address")

		with self.assertRaises(UnauthorizedError):
			create_address(email, self._payload())
		with self.assertRaises(UnauthorizedError):
			retrieve_address(email, "addr_" + "0" * 32)
		with self.assertRaises(UnauthorizedError):
			update_address(email, "any", StoreUpdateCustomerAddress(city="Salem"))
		with self.assertRaises(UnauthorizedError):
			delete_address(email, "any")
		with self.assertRaises(UnauthorizedError):
			list_addresses(email, StoreCustomerAddressFilters())

		self.assertEqual(frappe.db.count("Address"), before)

	def test_a_disabled_identity_is_refused(self) -> None:
		email = new_identity("address-disabled")
		frappe.db.set_value("User", email, "enabled", 0)

		with self.assertRaises(UnauthorizedError):
			create_address(email, self._payload())

	# --------------------------------------------------------------- create

	def test_create_mints_the_stable_public_name_with_exactly_the_customer_link(self) -> None:
		identity, reference = create_address(self.email, self._payload(address_2="Suite 3"))
		name = self._book(self.identity.customer)[-1]

		self.assertEqual(identity, self.identity)
		self.assertEqual(reference.name, self.reference.name)
		self.assertRegex(name, r"^addr_[0-9a-f]{32}$")
		links = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Address", "parent": name},
			fields=["link_doctype", "link_name"],
		)
		# Exactly the owning Customer: no Quotation link, no Contact.
		self.assertEqual(links, [{"link_doctype": "Customer", "link_name": self.identity.customer}])
		row = frappe.db.get_value("Address", name, list(_ADDRESS_ROW_FIELDS), as_dict=True)
		self.assertEqual(row.address_type, "Billing")
		self.assertEqual(row.address_line1, "1 Harbor Way")
		self.assertEqual(row.address_line2, "Suite 3")
		self.assertEqual(row.city, "Portland")
		self.assertEqual(row.country, "United States")
		self.assertEqual(row.disabled, 0)
		self.assertEqual(row.is_primary_address, 0)
		self.assertEqual(row.is_shipping_address, 0)
		self.assertIsNone(frappe.db.get_value("Ceto Customer Address Reference", name, "metadata"))

	def test_create_composes_the_label_with_the_documented_precedence(self) -> None:
		# A supplied address_name label wins over the composed names...
		name = self._create(address_name="Home", first_name="Aria", last_name="Stone")
		self.assertEqual(self._row(name).address_title, "Home")
		# ...the names compose when no label is supplied...
		name = self._create(first_name="Aria", last_name="Stone")
		self.assertEqual(self._row(name).address_title, "Aria Stone")
		# ...and the company is the last fallback.
		name = self._create(company="Harbor Co.")
		self.assertEqual(self._row(name).address_title, "Harbor Co.")

	def test_create_requires_the_pinned_core_columns(self) -> None:
		before = frappe.db.count("Address")

		for payload in (
			self._payload(address_1=None),
			self._payload(city=None),
			self._payload(country_code=None),
			# The ISO code resolves through the shared helper: unknown is invalid.
			self._payload(country_code="zz"),
		):
			with self.assertRaises(InvalidDataError):
				create_address(self.email, payload)

		self.assertEqual(frappe.db.count("Address"), before)

	def test_create_stores_metadata_through_the_reference(self) -> None:
		name = self._create(metadata={"wing": "east"})

		row = frappe.db.get_value(
			"Ceto Customer Address Reference", name, ["customer", "metadata"], as_dict=True
		)
		self.assertEqual(row.customer, self.identity.customer)
		self.assertEqual(json.loads(row.metadata), {"wing": "east"})

	def test_create_flags_clear_the_previous_holder_per_customer(self) -> None:
		first = self._create(is_default_billing=True, is_default_shipping=True)
		peer_identity, _ = self._peer()
		peer = self._create(peer_identity, is_default_billing=True)

		second = self._create(is_default_billing=True)

		self.assertEqual(self._flag(first, "is_primary_address"), 0)
		self.assertEqual(self._flag(second, "is_primary_address"), 1)
		# The shipping slot of the entry is untouched by a billing flag.
		self.assertEqual(self._flag(second, "is_shipping_address"), 0)
		self.assertEqual(self._flag(first, "is_shipping_address"), 1)
		# Another customer's flagged entry is never swept.
		self.assertEqual(self._flag(peer, "is_primary_address"), 1)

	# ------------------------------------------------------------- retrieve

	def test_retrieve_serializes_the_pinned_address_entity(self) -> None:
		name = self._create(
			address_name="Home",
			first_name="Aria",
			last_name="Stone",
			company="Harbor Co.",
			address_2="Suite 3",
			province="Oregon",
			postal_code="97201",
			phone="+1 555 0100",
			is_default_billing=True,
			metadata={"wing": "east"},
		)
		stored = frappe.get_doc("Address", name)

		body = retrieve_address(self.email, name)

		self.assertEqual(body["id"], name)
		self.assertEqual(body["customer_id"], self.reference.name)
		self.assertTrue(body["is_default_billing"])
		self.assertFalse(body["is_default_shipping"])
		self.assertEqual(body["address_name"], "Home")
		# The collapsed columns never serialize back (no dedicated columns).
		self.assertIsNone(body["first_name"])
		self.assertIsNone(body["last_name"])
		self.assertIsNone(body["company"])
		self.assertEqual(body["address_1"], "1 Harbor Way")
		self.assertEqual(body["address_2"], "Suite 3")
		self.assertEqual(body["city"], "Portland")
		self.assertEqual(body["province"], "Oregon")
		self.assertEqual(body["postal_code"], "97201")
		self.assertEqual(body["country_code"], "us")
		self.assertEqual(body["phone"], "+1 555 0100")
		self.assertEqual(body["metadata"], {"wing": "east"})
		self.assertEqual(body["created_at"], stored.creation.isoformat())
		self.assertEqual(body["updated_at"], stored.modified.isoformat())

	def test_missing_foreign_and_disabled_entries_are_masked_alike(self) -> None:
		own = self._create()
		peer_identity, _ = self._peer()
		foreign = self._create(peer_identity)
		frappe.db.set_value("Address", own, "disabled", 1)

		messages = []
		for address_id in (own, foreign, "addr_" + "0" * 32):
			with self.assertRaises(RouteNotFoundError) as raised:
				retrieve_address(self.email, address_id)
			messages.append(raised.exception.message)
		self.assertEqual(len(messages), 3)
		self.assertEqual(len(set(messages)), 1)

		with self.assertRaises(RouteNotFoundError):
			update_address(self.email, foreign, StoreUpdateCustomerAddress(city="Salem"))
		with self.assertRaises(RouteNotFoundError):
			delete_address(self.email, foreign)

	# --------------------------------------------------------------- update

	def test_partial_updates_move_only_the_supplied_fields(self) -> None:
		name = self._create(
			address_2="Suite 3",
			province="Oregon",
			postal_code="97201",
			phone="+1 555 0100",
			first_name="Aria",
			last_name="Stone",
		)

		identity, reference = update_address(
			self.email, name, StoreUpdateCustomerAddress(address_2="Suite 9")
		)

		self.assertEqual(identity, self.identity)
		self.assertEqual(reference.name, self.reference.name)
		row = self._row(name)
		self.assertEqual(row.address_line2, "Suite 9")
		self.assertEqual(row.state, "Oregon")
		self.assertEqual(row.pincode, "97201")
		self.assertEqual(row.phone, "+1 555 0100")
		self.assertEqual(row.address_title, "Aria Stone")
		self.assertEqual(row.country, "United States")

	def test_updates_clear_supplied_columns_and_refuse_clearing_required_ones(self) -> None:
		name = self._create(address_2="Suite 3", province="Oregon", postal_code="97201", phone="+1 555 0100")
		update_address(
			self.email,
			name,
			StoreUpdateCustomerAddress(address_2=None, province=None, postal_code=None, phone=None),
		)
		row = self._row(name)
		for column in ("address_line2", "state", "pincode", "phone"):
			self.assertIsNone(row[column])

		before = self._modified(name)
		for payload in (
			StoreUpdateCustomerAddress(address_1=None),
			StoreUpdateCustomerAddress(city=None),
			StoreUpdateCustomerAddress(country_code=None),
		):
			with self.assertRaises(InvalidDataError):
				update_address(self.email, name, payload)
		self.assertEqual(self._modified(name), before)

	def test_updates_resolve_country_codes(self) -> None:
		name = self._create()

		with self.assertRaises(InvalidDataError):
			update_address(self.email, name, StoreUpdateCustomerAddress(country_code="zz"))

		update_address(self.email, name, StoreUpdateCustomerAddress(country_code="DE"))
		self.assertEqual(self._row(name).country, "Germany")

	def test_updates_recompute_the_label_only_from_supplied_label_fields(self) -> None:
		name = self._create(first_name="Aria", last_name="Stone")

		update_address(self.email, name, StoreUpdateCustomerAddress(city="Salem"))
		self.assertEqual(self._row(name).address_title, "Aria Stone")
		update_address(self.email, name, StoreUpdateCustomerAddress(first_name="Ryn"))
		self.assertEqual(self._row(name).address_title, "Ryn")
		update_address(self.email, name, StoreUpdateCustomerAddress(address_name="Home"))
		self.assertEqual(self._row(name).address_title, "Home")
		# A cleared label falls back to the supplied names.
		update_address(self.email, name, StoreUpdateCustomerAddress(address_name=None, first_name="Ari"))
		self.assertEqual(self._row(name).address_title, "Ari")
		update_address(self.email, name, StoreUpdateCustomerAddress(address_name=None))
		self.assertIsNone(self._row(name).address_title)

	def test_update_flags_clear_the_previous_holder_per_customer(self) -> None:
		first = self._create(is_default_shipping=True)
		second = self._create()
		peer_identity, _ = self._peer()
		peer = self._create(peer_identity, is_default_billing=True)

		update_address(self.email, second, StoreUpdateCustomerAddress(is_default_shipping=True))
		self.assertEqual(self._flag(first, "is_shipping_address"), 0)
		self.assertEqual(self._flag(second, "is_shipping_address"), 1)

		update_address(self.email, second, StoreUpdateCustomerAddress(is_default_billing=True))
		self.assertEqual(self._flag(second, "is_primary_address"), 1)
		self.assertEqual(self._flag(peer, "is_primary_address"), 1)

	def test_metadata_merges_and_clears_through_the_reference(self) -> None:
		name = self._create(metadata={"tier": "gold", "wing": "east"})
		before = self._modified(name)

		update_address(self.email, name, StoreUpdateCustomerAddress(metadata={"wing": None, "note": "x"}))
		self.assertEqual(self._stored_metadata(name), {"tier": "gold", "note": "x"})
		# The metadata mutation advances the entry's contract updated_at.
		self.assertNotEqual(self._modified(name), before)

		update_address(self.email, name, StoreUpdateCustomerAddress(metadata=None))
		self.assertIsNone(self._stored_metadata(name))

		# The reference row is created on demand for a pre-existing entry.
		legacy = self._legacy_address()
		update_address(self.email, legacy, StoreUpdateCustomerAddress(metadata={"note": "y"}))
		self.assertEqual(self._stored_metadata(legacy), {"note": "y"})

	def test_noop_updates_write_nothing(self) -> None:
		name = self._create(address_2="Suite 3", metadata={"tier": "gold"})
		before = self._modified(name)

		update_address(
			self.email,
			name,
			StoreUpdateCustomerAddress(address_2="Suite 3", city="Portland", metadata={"tier": "gold"}),
		)
		update_address(self.email, name, StoreUpdateCustomerAddress(is_default_billing=False))

		self.assertEqual(self._modified(name), before)
		self.assertEqual(self._stored_metadata(name), {"tier": "gold"})

	def test_updates_stay_scoped_to_the_supplied_identity(self) -> None:
		peer_identity, _ = self._peer()
		peer = self._create(peer_identity)
		peer_before = self._modified(peer)

		name = self._create()
		update_address(self.email, name, StoreUpdateCustomerAddress(city="Salem", metadata={"note": "x"}))

		self.assertEqual(self._modified(peer), peer_before)
		self.assertEqual(self._row(peer).city, "Portland")
		self.assertIsNone(self._stored_metadata(peer))

	def test_the_privileged_scope_ends_with_the_call(self) -> None:
		name = self._create()

		with self.set_user(self.email):
			# A Website User owns no write on the Administrator-owned entry;
			# only the service's internal scope performs the write.
			update_address(self.email, name, StoreUpdateCustomerAddress(city="Salem"))
			self.assertEqual(frappe.session.user, self.email)

		self.assertEqual(self._row(name).city, "Salem")

	# ----------------------------------------------------------------- list

	def test_lists_paginate_deterministically(self) -> None:
		home = self._create(address_name="Home", city="Portland")
		beach = self._create(address_name="Beach house", city="Salem")
		depot = self._create(address_name="Depot", city="Portland")

		body = list_addresses(self.email, StoreCustomerAddressFilters())
		self.assertEqual(body["count"], 3)
		self.assertEqual(body["offset"], 0)
		self.assertEqual(body["limit"], 20)
		self.assertEqual({row["id"] for row in body["addresses"]}, {home, beach, depot})
		self.assertEqual(body["addresses"][0]["customer_id"], self.reference.name)

		# The window applies after the ordering; ``order=id`` is name-ordered.
		ordered = sorted([home, beach, depot])
		window = list_addresses(self.email, StoreCustomerAddressFilters(order="id", offset=1, limit=1))
		self.assertEqual([row["id"] for row in window["addresses"]], [ordered[1]])
		self.assertEqual((window["count"], window["offset"], window["limit"]), (3, 1, 1))

		# ``order=city`` is city asc with the name tiebreak: the Portland
		# pair keeps id order and the Salem entry closes the page.
		by_city = list_addresses(self.email, StoreCustomerAddressFilters(order="city"))
		self.assertEqual([row["id"] for row in by_city["addresses"]], [*sorted([home, depot]), beach])
		desc = list_addresses(self.email, StoreCustomerAddressFilters(order="-id"))
		self.assertEqual([row["id"] for row in desc["addresses"]], list(reversed(ordered)))

		with self.assertRaises(InvalidDataError):
			list_addresses(self.email, StoreCustomerAddressFilters(order="company"))

	def test_lists_filter_by_the_pinned_columns(self) -> None:
		home = self._create(address_name="Home", city="Portland", postal_code="97201", country_code="us")
		beach = self._create(
			address_name="Beach house",
			city="Salem",
			postal_code="97301",
			country_code="us",
			address_1="2 Shore Rd",
		)
		depot = self._create(address_name="Depot", city="Portland", postal_code="97201", country_code="de")

		def ids(**filters) -> list[str]:
			body = list_addresses(self.email, StoreCustomerAddressFilters(**filters))
			return sorted(row["id"] for row in body["addresses"])

		self.assertEqual(ids(city="Portland"), sorted([home, depot]))
		self.assertEqual(ids(postal_code="97301"), [beach])
		self.assertEqual(ids(country_code="US"), sorted([home, beach]))
		self.assertEqual(ids(country_code="de"), [depot])
		self.assertEqual(ids(city="Portland", country_code="de"), [depot])
		self.assertEqual(ids(q="beach"), [beach])
		self.assertEqual(ids(q="shore"), [beach])
		self.assertEqual(ids(q="zzz"), [])

	def test_lists_exclude_disabled_and_foreign_entries(self) -> None:
		mine = self._create()
		frappe.db.set_value("Address", mine, "disabled", 1)
		peer_identity, _ = self._peer()
		peer = self._create(peer_identity)

		body = list_addresses(self.email, StoreCustomerAddressFilters())
		self.assertEqual((body["count"], body["addresses"]), (0, []))

		peer_body = list_addresses(peer_identity.user, StoreCustomerAddressFilters())
		self.assertEqual([row["id"] for row in peer_body["addresses"]], [peer])

	def test_with_deleted_is_a_validated_noop(self) -> None:
		self._create()

		body = list_addresses(self.email, StoreCustomerAddressFilters(with_deleted=True))

		self.assertEqual(body["count"], 1)

	def test_list_and_retrieve_project_the_pinned_fields_selector(self) -> None:
		name = self._create(address_name="Home")

		body = list_addresses(self.email, StoreCustomerAddressFilters(fields="id,city"))
		self.assertEqual(body["addresses"], [{"id": name, "city": "Portland"}])
		self.assertEqual(retrieve_address(self.email, name, fields="id"), {"id": name})

		with self.assertRaises(InvalidDataError):
			list_addresses(self.email, StoreCustomerAddressFilters(fields="id,company"))
		with self.assertRaises(InvalidDataError):
			retrieve_address(self.email, name, fields="nonexistent")

	def test_pre_existing_addresses_surface_under_their_existing_names(self) -> None:
		legacy = self._legacy_address("Legacy ERP Home")

		body = list_addresses(self.email, StoreCustomerAddressFilters())

		self.assertEqual([row["id"] for row in body["addresses"]], [legacy])
		self.assertEqual(body["addresses"][0]["customer_id"], self.reference.name)
		self.assertIsNone(body["addresses"][0]["metadata"])
		self.assertTrue(is_customer_address(legacy, self.identity.customer))

	# --------------------------------------------------------------- delete

	def test_delete_destroys_an_unreferenced_entry(self) -> None:
		name = self._create(metadata={"wing": "east"})

		delete_address(self.email, name)

		self.assertIsNone(frappe.db.get_value("Address", name))
		self.assertIsNone(frappe.db.get_value("Ceto Customer Address Reference", name))
		self.assertIsNone(frappe.db.get_value("Dynamic Link", {"parenttype": "Address", "parent": name}))

	def test_delete_releases_the_customer_default_slot_it_holds(self) -> None:
		name = self._create(is_default_billing=True)
		frappe.db.set_value("Customer", self.identity.customer, "customer_primary_address", name)

		delete_address(self.email, name)

		self.assertIsNone(frappe.db.get_value("Address", name))
		self.assertIsNone(frappe.db.get_value("Customer", self.identity.customer, "customer_primary_address"))

	def test_delete_retains_an_entry_when_legitimate_references_exist(self) -> None:
		name = self._create()
		self._quotation_referencing(name)

		delete_address(self.email, name)

		# The placed Quotation keeps its historical address: the entry stays,
		# only the book membership (link + reference) is removed.
		self.assertIsNotNone(frappe.db.get_value("Address", name))
		self.assertFalse(is_customer_address(name, self.identity.customer))
		self.assertIsNone(frappe.db.get_value("Ceto Customer Address Reference", name))
		with self.assertRaises(RouteNotFoundError):
			retrieve_address(self.email, name)

	def test_delete_retains_an_entry_another_customer_still_owns(self) -> None:
		name = self._create()
		peer = make_customer("address-book-peer")
		doc = frappe.get_doc("Address", name)
		doc.append("links", {"link_doctype": "Customer", "link_name": peer})
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)

		delete_address(self.email, name)

		self.assertIsNotNone(frappe.db.get_value("Address", name))
		self.assertTrue(is_customer_address(name, peer))
		self.assertFalse(is_customer_address(name, self.identity.customer))
		self.assertIsNone(frappe.db.get_value("Ceto Customer Address Reference", name))
