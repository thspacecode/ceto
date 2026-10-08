"""Sparse profile updates behind an already-resolved identity.

Pins the update service on the test site: only supplied payload fields move
(omitted stays, ``null`` and stripped-empty clear), the phone payload owns the
Contact's primary phone slot through the controller-derived column, the
display name recomposes from the effective names with the email fallback,
metadata merges with the shared reference semantics, effective mutations —
and only those — advance the Customer timestamp the contract serializes as
``updated_at``, and every write stays inside the caller's transaction and
privileged scope.
"""

import json
from unittest.mock import patch

import frappe
from frappe.model.document import Document

from ceto.services.customers.creation import create_customer_profile
from ceto.services.customers.update import update_customer
from ceto.tests.data.customer_test_data import THROTTLE_USER_LIMIT, new_identity
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.customers import StoreUpdateCustomer


class TestCustomerProfileUpdate(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			self.email = new_identity("update")
			self.identity, self.reference = create_customer_profile(
				self.email,
				first_name="Aria",
				last_name="Stone",
				company_name="Harbor Co.",
				phone="+1 555 0100",
				metadata={"loyalty_tier": "gold"},
			)

	def _profile(self) -> dict:
		"""The stored profile columns, normalized so cleared reads as ``None``."""
		profile = frappe.db.get_value(
			"Contact",
			self.identity.contact,
			["first_name", "last_name", "company_name", "phone"],
			as_dict=True,
		)
		return {field: value or None for field, value in profile.items()}

	def _phone_rows(self) -> list[dict]:
		"""The Contact's phone rows in stored order."""
		return frappe.get_all(
			"Contact Phone",
			filters={"parent": self.identity.contact},
			fields=["phone", "is_primary_phone"],
			order_by="idx asc",
		)

	def _modified(self, identity=None, reference=None) -> dict[str, str]:
		"""The current modified stamps of every record the chain serializes."""
		identity = identity or self.identity
		reference = reference or self.reference
		return {
			"contact": frappe.db.get_value("Contact", identity.contact, "modified"),
			"customer": frappe.db.get_value("Customer", identity.customer, "modified"),
			"reference": frappe.db.get_value("Ceto Customer Reference", reference.name, "modified"),
		}

	def _stored_metadata(self) -> dict | None:
		stored = frappe.db.get_value("Ceto Customer Reference", self.reference.name, "metadata")
		return json.loads(stored) if stored else None

	def test_sparse_update_moves_only_the_supplied_field(self) -> None:
		before = self._modified()

		update_customer(self.identity, self.reference, StoreUpdateCustomer(last_name="Vale"))

		profile = self._profile()
		self.assertEqual(profile["last_name"], "Vale")
		self.assertEqual(profile["first_name"], "Aria")
		self.assertEqual(profile["company_name"], "Harbor Co.")
		self.assertEqual(profile["phone"], "+1 555 0100")
		self.assertEqual(self._stored_metadata(), {"loyalty_tier": "gold"})
		self.assertEqual(
			frappe.db.get_value("Customer", self.identity.customer, "customer_name"), "Aria Vale"
		)
		after = self._modified()
		self.assertNotEqual(after["contact"], before["contact"])
		self.assertNotEqual(after["customer"], before["customer"])
		self.assertEqual(after["reference"], before["reference"])

	def test_updates_every_profile_column_together(self) -> None:
		update_customer(
			self.identity,
			self.reference,
			StoreUpdateCustomer(
				first_name="Ryn", last_name="Vale", company_name="Vale & Co.", phone="+1 555 0199"
			),
		)

		profile = self._profile()
		self.assertEqual(profile["first_name"], "Ryn")
		self.assertEqual(profile["last_name"], "Vale")
		self.assertEqual(profile["company_name"], "Vale & Co.")
		# The derived column follows the primary row the controller picked.
		self.assertEqual(profile["phone"], "+1 555 0199")
		self.assertEqual(frappe.db.get_value("Customer", self.identity.customer, "customer_name"), "Ryn Vale")
		rows = self._phone_rows()
		# The previous number stays as a plain row; exactly one primary exists.
		self.assertEqual(
			[(row["phone"], row["is_primary_phone"]) for row in rows],
			[("+1 555 0100", 0), ("+1 555 0199", 1)],
		)

	def test_promotes_an_existing_phone_row_instead_of_duplicating_it(self) -> None:
		update_customer(self.identity, self.reference, StoreUpdateCustomer(phone="+1 555 0199"))

		update_customer(self.identity, self.reference, StoreUpdateCustomer(phone="+1 555 0100"))

		# The number that was demoted is promoted back in place, never re-added.
		self.assertEqual(
			[(row["phone"], row["is_primary_phone"]) for row in self._phone_rows()],
			[("+1 555 0100", 1), ("+1 555 0199", 0)],
		)
		self.assertEqual(self._profile()["phone"], "+1 555 0100")

	def test_null_clears_the_profile_columns_and_releases_the_primary_phone(self) -> None:
		before = self._modified()

		update_customer(
			self.identity,
			self.reference,
			StoreUpdateCustomer(first_name=None, last_name=None, company_name=None, phone=None),
		)

		profile = self._profile()
		self.assertIsNone(profile["first_name"])
		self.assertIsNone(profile["last_name"])
		self.assertIsNone(profile["company_name"])
		self.assertIsNone(profile["phone"])
		self.assertEqual([row["is_primary_phone"] for row in self._phone_rows()], [])
		# A fully anonymous profile names itself after the identity email.
		self.assertEqual(frappe.db.get_value("Customer", self.identity.customer, "customer_name"), self.email)
		after = self._modified()
		self.assertNotEqual(after["customer"], before["customer"])
		self.assertEqual(after["reference"], before["reference"])

	def test_stripped_empty_string_clears_like_null(self) -> None:
		payload = StoreUpdateCustomer.model_validate(
			{"first_name": "   ", "last_name": "\t", "company_name": "", "phone": "   "}
		)
		# The pinned payload model strips before the service sees the value,
		# but the field still counts as supplied.
		self.assertEqual(payload.first_name, "")
		self.assertIn("first_name", payload.model_fields_set)

		update_customer(self.identity, self.reference, payload)

		profile = self._profile()
		self.assertIsNone(profile["first_name"])
		self.assertIsNone(profile["last_name"])
		self.assertIsNone(profile["company_name"])
		self.assertIsNone(profile["phone"])
		self.assertEqual([row["is_primary_phone"] for row in self._phone_rows()], [])

	def test_effective_names_compose_with_the_email_fallback(self) -> None:
		update_customer(self.identity, self.reference, StoreUpdateCustomer(first_name=None, last_name=None))
		self.assertEqual(frappe.db.get_value("Customer", self.identity.customer, "customer_name"), self.email)

		# The effective columns compose: the cleared last name stays cleared.
		update_customer(self.identity, self.reference, StoreUpdateCustomer(first_name="Ryn"))

		self.assertEqual(frappe.db.get_value("Customer", self.identity.customer, "customer_name"), "Ryn")

	def test_metadata_merges_per_key_and_null_removes(self) -> None:
		update_customer(
			self.identity,
			self.reference,
			StoreUpdateCustomer(metadata={"newsletter": True, "loyalty_tier": None}),
		)

		self.assertEqual(self._stored_metadata(), {"newsletter": True})
		# The mutation lands on the supplied reference, not only in the database.
		self.assertEqual(json.loads(self.reference.metadata), {"newsletter": True})

	def test_metadata_null_clears_every_key(self) -> None:
		update_customer(self.identity, self.reference, StoreUpdateCustomer(metadata=None))

		self.assertIsNone(self._stored_metadata())

	def test_metadata_only_update_still_advances_the_customer_timestamp(self) -> None:
		before = self._modified()

		update_customer(self.identity, self.reference, StoreUpdateCustomer(metadata={"new": 1}))

		after = self._modified()
		self.assertEqual(self._stored_metadata(), {"loyalty_tier": "gold", "new": 1})
		# The Contact holds no profile change, yet updated_at still moves.
		self.assertEqual(after["contact"], before["contact"])
		self.assertNotEqual(after["customer"], before["customer"])
		self.assertNotEqual(after["reference"], before["reference"])

	def test_noop_payload_writes_nothing(self) -> None:
		before = self._modified()

		update_customer(self.identity, self.reference, StoreUpdateCustomer())
		update_customer(self.identity, self.reference, StoreUpdateCustomer(metadata={}))
		# Removing an absent key and re-supplying current values change nothing.
		update_customer(self.identity, self.reference, StoreUpdateCustomer(metadata={"absent": None}))
		update_customer(
			self.identity,
			self.reference,
			StoreUpdateCustomer(
				first_name="Aria", last_name="Stone", company_name="Harbor Co.", phone="+1 555 0100"
			),
		)

		self.assertEqual(self._modified(), before)
		self.assertEqual(self._stored_metadata(), {"loyalty_tier": "gold"})
		self.assertEqual(
			frappe.db.get_value("Customer", self.identity.customer, "customer_name"), "Aria Stone"
		)

	def test_a_mid_write_failure_rolls_back_with_the_caller_transaction(self) -> None:
		# Like the boundary suites, the chain under test is committed first so
		# the caller's rollback erases exactly the update's own writes.
		frappe.db.commit()  # nosemgrep
		before = self._modified()
		real_save = Document.save

		def fail_on_customer(doc, *args, **kwargs):
			if doc.doctype == "Customer":
				raise RuntimeError("injected mid-write fault")
			return real_save(doc, *args, **kwargs)

		with patch.object(Document, "save", fail_on_customer):
			# The Contact write already happened when the fault hits the
			# Customer save; the caller's rollback must erase even that.
			with self.assertRaises(RuntimeError):
				update_customer(
					self.identity,
					self.reference,
					StoreUpdateCustomer(first_name="Ryn", metadata={"newsletter": True}),
				)

		frappe.db.rollback()

		self.assertEqual(self._profile()["first_name"], "Aria")
		self.assertEqual(
			frappe.db.get_value("Customer", self.identity.customer, "customer_name"), "Aria Stone"
		)
		self.assertEqual(self._stored_metadata(), {"loyalty_tier": "gold"})
		self.assertEqual(self._modified(), before)

	def test_an_optimistic_timestamp_mismatch_translates_normally(self) -> None:
		# The chain is committed first: the caller's rollback after the lost
		# race must erase exactly the update's own writes.
		frappe.db.commit()  # nosemgrep
		before = self._modified()
		real_get_doc = frappe.get_doc
		raced = []

		def race_the_contact_load(*args, **kwargs):
			doc = real_get_doc(*args, **kwargs)
			if not raced and args[:2] == ("Contact", self.identity.contact):
				raced.append(doc.name)
				# A concurrent writer lands between the service's read and save.
				frappe.db.set_value("Contact", doc.name, "company_name", "Raced In")
			return doc

		with patch("frappe.get_doc", side_effect=race_the_contact_load):
			with self.assertRaises(frappe.TimestampMismatchError):
				update_customer(self.identity, self.reference, StoreUpdateCustomer(first_name="Ryn"))

		frappe.db.rollback()

		self.assertEqual(self._profile()["first_name"], "Aria")
		self.assertEqual(self._modified(), before)

	def test_updates_stay_scoped_to_the_supplied_identity(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			peer_email = new_identity("peer")
			peer_identity, peer_reference = create_customer_profile(
				peer_email, first_name="Peer", last_name="Person", phone="+1 555 0200"
			)
		peer_before = self._modified(peer_identity, peer_reference)
		peer_profile_before = frappe.db.get_value(
			"Contact", peer_identity.contact, ["first_name", "phone"], as_dict=True
		)
		peer_customer_name = frappe.db.get_value("Customer", peer_identity.customer, "customer_name")

		update_customer(self.identity, self.reference, StoreUpdateCustomer(first_name="Ryn"))

		self.assertEqual(
			frappe.db.get_value("Contact", peer_identity.contact, ["first_name", "phone"], as_dict=True),
			peer_profile_before,
		)
		self.assertEqual(
			frappe.db.get_value("Customer", peer_identity.customer, "customer_name"), peer_customer_name
		)
		self.assertIsNone(frappe.db.get_value("Ceto Customer Reference", peer_reference.name, "metadata"))
		self.assertEqual(self._modified(peer_identity, peer_reference), peer_before)

	def test_the_privileged_scope_ends_with_the_call(self) -> None:
		with self.set_user(self.email):
			# A Website User owns no write permission on Customer or Contact;
			# only the service's internal scope performs the writes.
			update_customer(self.identity, self.reference, StoreUpdateCustomer(first_name="Ryn"))
			self.assertEqual(frappe.session.user, self.email)

		self.assertEqual(self._profile()["first_name"], "Ryn")
