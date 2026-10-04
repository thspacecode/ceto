"""Atomic profile creation behind a registration identity.

Pins the create service on the test site: the reused auto-created Contact,
exactly one Customer/Contact/reference per create, the duplicate / ambiguous
/ disabled refusals that precede every privileged write, the unique-race
convergence and the caller-owned transaction (rollback leaves nothing).
"""

import json
import uuid

import frappe

from ceto.routing.exceptions import UnauthorizedError
from ceto.services.customers.creation import create_customer_profile
from ceto.tests.data.customer_test_data import THROTTLE_USER_LIMIT, make_customer, new_identity
from ceto.tests.utils import CetoTestSuite


class TestCustomerProfileCreation(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")

	def _new_identity(self, label: str) -> str:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			return new_identity(label)

	def test_creates_exactly_one_chain_and_reference(self) -> None:
		email = self._new_identity("create")

		identity, reference = create_customer_profile(
			email,
			first_name="Aria",
			last_name="Stone",
			company_name="Harbor Co.",
			phone="+1 555 0100",
			metadata={"loyalty_tier": "gold"},
		)

		# The public reference names one Customer and the identity.
		self.assertRegex(reference.name, r"^cus_[0-9a-f]{32}$")
		self.assertEqual(reference.customer, identity.customer)
		self.assertEqual(reference.user, email)
		self.assertEqual(json.loads(reference.metadata), {"loyalty_tier": "gold"})

		# The auto-created registration Contact was reused, not duplicated.
		self.assertEqual(identity.contact, frappe.db.get_value("Contact", {"user": email}))
		self.assertEqual(identity.user, email)
		self.assertEqual(frappe.db.count("Contact", {"user": email}), 1)
		contact = frappe.get_doc("Contact", identity.contact)
		self.assertEqual(contact.user, email)
		self.assertEqual(contact.first_name, "Aria")
		self.assertEqual(contact.last_name, "Stone")
		self.assertEqual(contact.company_name, "Harbor Co.")
		self.assertTrue(contact.has_link("Customer", identity.customer))
		self.assertIn(email, [row.email_id for row in contact.email_ids])

		# Exactly one selling Customer, shaped by recorded decision 2.
		self.assertEqual(frappe.db.count("Customer", {"name": identity.customer}), 1)
		customer = frappe.get_doc("Customer", identity.customer)
		self.assertEqual(customer.customer_name, "Aria Stone")
		self.assertEqual(customer.customer_type, "Individual")
		self.assertEqual(frappe.db.get_value("Customer Group", customer.customer_group, "is_group"), 0)

	def test_creates_the_contact_when_the_registration_job_has_not_run(self) -> None:
		email = self._new_identity("no-contact")
		# Simulate the production window before Frappe's post-commit contact
		# job ran: the identity has no Contact yet.
		frappe.delete_doc("Contact", frappe.db.get_value("Contact", {"user": email}), force=True)

		identity, reference = create_customer_profile(email, first_name="Aria")

		self.assertEqual(frappe.db.count("Contact", {"user": email}), 1)
		contact = frappe.get_doc("Contact", identity.contact)
		self.assertEqual(contact.first_name, "Aria")
		self.assertEqual(contact.user, email)
		self.assertEqual([(row.email_id, row.is_primary) for row in contact.email_ids], [(email, 1)])
		self.assertTrue(contact.has_link("Customer", identity.customer))
		self.assertEqual(reference.user, email)

	def test_falls_back_to_the_email_for_the_customer_name(self) -> None:
		email = self._new_identity("fallback")

		identity, _reference = create_customer_profile(email)

		self.assertEqual(frappe.db.get_value("Customer", identity.customer, "customer_name"), email)

	def test_refuses_a_duplicate_create(self) -> None:
		email = self._new_identity("duplicate")
		create_customer_profile(email, first_name="Aria")

		with self.assertRaises(UnauthorizedError) as raised:
			create_customer_profile(email, first_name="Retry")

		self.assertEqual(str(raised.exception), "User already owns a customer account")
		self.assertEqual(frappe.db.count("Ceto Customer Reference", {"user": email}), 1)
		self.assertEqual(frappe.db.count("Contact", {"user": email}), 1)

	def test_refuses_an_identity_that_already_owns_a_customer(self) -> None:
		# A pre-existing account (Contact linked outside Ceto) must never be
		# minted a second, parallel profile.
		email = self._new_identity("preowned")
		customer = make_customer("preowned")
		contact = frappe.get_doc("Contact", frappe.db.get_value("Contact", {"user": email}))
		contact.append("links", {"link_doctype": "Customer", "link_name": customer})
		contact.flags.ignore_permissions = True
		contact.save(ignore_permissions=True)

		with self.assertRaises(UnauthorizedError) as raised:
			create_customer_profile(email, first_name="Aria")

		self.assertEqual(str(raised.exception), "User already owns a customer account")
		self.assertFalse(frappe.db.count("Ceto Customer Reference", {"user": email}))

	def test_refuses_an_ambiguous_identity(self) -> None:
		email = self._new_identity("ambiguous")
		frappe.get_doc({"doctype": "Contact", "first_name": "Second", "user": email}).insert(
			ignore_permissions=True
		)

		with self.assertRaises(UnauthorizedError) as raised:
			create_customer_profile(email, first_name="Aria")

		self.assertEqual(str(raised.exception), "User is linked to multiple contacts")
		self.assertFalse(frappe.db.count("Ceto Customer Reference", {"user": email}))

	def test_refuses_a_disabled_identity(self) -> None:
		email = self._new_identity("disabled")
		frappe.db.set_value("User", email, "enabled", 0)
		customers_before = frappe.db.count("Customer")

		with self.assertRaises(UnauthorizedError):
			create_customer_profile(email, first_name="Aria")

		self.assertEqual(frappe.db.count("Customer"), customers_before)
		self.assertFalse(frappe.db.count("Ceto Customer Reference", {"user": email}))

	def test_refuses_an_unknown_registration_identity(self) -> None:
		with self.assertRaises(UnauthorizedError):
			create_customer_profile(f"ceto.ghost.{uuid.uuid4().hex}@example.com")

	def test_converges_a_lost_reference_race_to_unauthorized(self) -> None:
		email = self._new_identity("race")
		identity, _reference = create_customer_profile(email, first_name="Aria")

		# Simulate the concurrent create that won the unique index: its
		# reference row for the same User becomes visible while the drifted
		# chain still lets the pre-check pass. The lost insert must refuse
		# instead of minting a second reference.
		contact = frappe.get_doc("Contact", identity.contact)
		contact.links = []
		contact.flags.ignore_permissions = True
		contact.save(ignore_permissions=True)

		with self.assertRaises(UnauthorizedError) as raised:
			create_customer_profile(email, first_name="Retry")

		self.assertEqual(str(raised.exception), "User already owns a customer account")
		self.assertEqual(frappe.db.count("Ceto Customer Reference", {"user": email}), 1)

	def test_rolls_back_with_the_caller_transaction(self) -> None:
		email = self._new_identity("rollback")

		create_customer_profile(email, first_name="Aria", metadata={"k": "v"})

		frappe.db.rollback()

		self.assertFalse(frappe.db.count("Ceto Customer Reference", {"user": email}))
		self.assertFalse(frappe.db.count("Customer", {"customer_name": "Aria"}))
		self.assertFalse(frappe.db.count("User", {"name": email}))
		self.assertFalse(frappe.db.count("Contact", {"user": email}))
