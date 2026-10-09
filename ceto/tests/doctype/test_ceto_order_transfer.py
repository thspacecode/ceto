"""Phase 4 transfer record: Ceto Order Transfer persistence and lifecycle.

Runs a real guest cart through completion-shaped fixtures on the test site
inside a single rolled-back transaction: the record names the pending
ownership transfer by its public ``tr_…`` id (``tr_`` + 32 lowercase hex),
carries the requesting customer against the guest order's ``Ceto Order
Reference``, and persists the single-use token digest-only, uniquely (a
shared digest fails closed at insert) alongside the stored ``expires_at``
window — Phase 4 stores the expiry even though a lifetime could be derived
from creation — and the pinned optional request ``description``, retained
for audit. The controller pins the three-state lifecycle — born
``Pending``, ``Accepted``/``Declined`` terminal — and the digest shape. It
deliberately does *not* pin one active transfer per order (the transfer
service's locked invariant: cancel removes the record and expiry frees the
order, neither expressible as a schema constraint) nor guest-order
eligibility (a request-time refusal) — orders field-mapping Recorded
Decisions 9-12.
"""

import hashlib
import uuid

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from ceto.services.carts.conversion import convert_quotation_to_sales_order
from ceto.services.carts.quotation import CartService
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class TestCetoOrderTransfer(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.order_reference = self._make_order_reference()

	def _make_cart(self):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return CartService().create(StoreCreateCart(email="guest@example.com"))

	def _make_order_reference(self):
		"""Book a guest order reference through the real completion shape.

		ERPNext requires line items before a Quotation can be submitted, so
		the fixture prices one item, submits the Quotation and maps it into
		a submitted Sales Order through the ERPNext mapper — the same shape
		``Ceto Order Reference`` validates before it books an order. The
		order stays guest-owned: transfers recover exactly those orders.
		"""
		reference, quotation = self._make_cart()
		quotation.append("items", {"item_code": self.masters.item, "qty": 1})
		quotation.flags.ignore_mandatory = True
		quotation.save(ignore_permissions=True)
		quotation.submit()
		sales_order = convert_quotation_to_sales_order(quotation.name, submit=True)
		return frappe.get_doc(
			{
				"doctype": "Ceto Order Reference",
				"order_id": f"order_{uuid.uuid4().hex}",
				"sales_order": sales_order.name,
				"cart_id": reference.name,
			}
		).insert(ignore_permissions=True)

	def _make_transfer(self, **overrides):
		"""A valid pending transfer against the fixture's guest order.

		``status`` is left to the schema default on purpose: every record is
		born ``Pending``, and the happy path must prove it. ``expires_at``
		mirrors the pinned 7-day lifetime (Recorded Decision 11) the minting
		request will compute.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Order Transfer",
				"transfer_id": f"tr_{uuid.uuid4().hex}",
				"order_reference": self.order_reference.name,
				"requested_by": self.masters.customer,
				"token_hash": hashlib.sha256(f"token-{uuid.uuid4().hex}".encode()).hexdigest(),
				"expires_at": add_to_date(now_datetime(), days=7),
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_transfer_by_its_public_id(self) -> None:
		transfer = self._make_transfer()

		loaded = frappe.get_doc("Ceto Order Transfer", transfer.transfer_id)
		self.assertEqual(loaded.name, transfer.transfer_id)
		self.assertEqual(loaded.order_reference, self.order_reference.name)
		self.assertEqual(loaded.requested_by, self.masters.customer)
		self.assertEqual(loaded.status, "Pending")

	def test_transfer_id_is_unique(self) -> None:
		transfer = self._make_transfer()

		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self._make_transfer(transfer_id=transfer.transfer_id)

	def test_transfer_id_format_is_strict(self) -> None:
		# The id is never normalized: a transfer_id that is not exactly the
		# minted ``tr_`` + 32 lowercase hex shape is refused outright, so a
		# padded or case-folded near-miss can never become an addressable
		# record.
		hex32 = uuid.uuid4().hex
		for transfer_id in (
			hex32,  # missing the tr_ prefix
			f"TR_{hex32}",  # uppercase prefix
			f"tr_{hex32.upper()}",  # uppercase hex
			f"tr_{hex32[:31]}",  # one hex character short
			f"tr_{hex32}0",  # one hex character long
			f"tr_g{hex32[:31]}",  # a non-hex character inside
			f" tr_{hex32}",  # whitespace-padded
			f"tr_{hex32} ",  # trailing whitespace
		):
			with self.subTest(transfer_id=transfer_id):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_transfer(transfer_id=transfer_id)

	def test_token_hash_is_normalized_and_strict(self) -> None:
		# Unlike the id, the digest is normalized (stripped, lowercased)
		# before validation — presentation variants land on the same value.
		# Each insert carries its own token, because a digest is unique
		# across records: sharing one digest twice would fail closed.
		for presented in (
			hashlib.sha256(b"a transfer token").hexdigest().upper(),
			f"  {hashlib.sha256(b'another token').hexdigest()}  ",
			f"  {hashlib.sha256(b'one more token').hexdigest().upper()}  ",
		):
			transfer = self._make_transfer(token_hash=presented)
			self.assertEqual(transfer.token_hash, presented.strip().lower())

		# But it must still be a real SHA-256 hex string: a digest is
		# compared exactly, and a malformed one must fail loudly instead of
		# silently never matching.
		for token_hash in (
			"tr-token-1234",
			"z" * 64,
			hashlib.sha256(b"short").hexdigest()[:-1],  # 63 characters
			f"{hashlib.sha256(b'long').hexdigest()}0",  # 65 characters
			f"{hashlib.sha256(b'tail').hexdigest()[:-4]}BE EF",  # non-hex tail
		):
			with self.subTest(token_hash=token_hash):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_transfer(token_hash=token_hash)

	def test_token_hash_is_unique(self) -> None:
		# The digest is the credential: a second record carrying the same
		# digest must fail closed at insert instead of silently sharing
		# another transfer's single-use token.
		transfer = self._make_transfer()

		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self._make_transfer(token_hash=transfer.token_hash)

	def test_expires_at_stores_the_window_not_a_derivation(self) -> None:
		# The window is its own persisted column — Phase 4 stores the expiry
		# explicitly even though a lifetime could be derived from creation —
		# so a non-default window round-trips exactly as the minting request
		# computed it and is never recomputed from creation.
		expiry = add_to_date(now_datetime(), days=3).replace(microsecond=0)
		transfer = self._make_transfer(expires_at=expiry)

		loaded = frappe.get_doc("Ceto Order Transfer", transfer.transfer_id)
		self.assertEqual(get_datetime(loaded.expires_at), expiry)
		self.assertNotEqual(
			get_datetime(loaded.expires_at),
			add_to_date(get_datetime(loaded.creation), days=7),
		)

	def test_description_is_optional_and_retained(self) -> None:
		# The pinned request payload's optional description is kept verbatim
		# for audit instead of being silently discarded.
		transfer = self._make_transfer()
		self.assertIsNone(transfer.description)

		described = "Requested without an account; placed as guest@example.com."
		kept = self._make_transfer(description=described)
		loaded = frappe.get_doc("Ceto Order Transfer", kept.transfer_id)
		self.assertEqual(loaded.description, described)

	def test_requires_order_reference_requester_digest_and_expiry(self) -> None:
		for overrides in (
			{"order_reference": None},
			{"requested_by": None},
			{"token_hash": None},
			{"expires_at": None},
		):
			with self.subTest(overrides=overrides):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_transfer(**overrides)

	def test_unknown_order_reference_or_requester_is_rejected(self) -> None:
		with self.assertRaises(frappe.exceptions.LinkValidationError):
			self._make_transfer(order_reference=f"order_{uuid.uuid4().hex}")

		with self.assertRaises(frappe.exceptions.LinkValidationError):
			self._make_transfer(requested_by=f"Ceto Missing Customer {uuid.uuid4().hex[:8]}")

	def test_status_holds_only_the_pinned_states(self) -> None:
		for status in ("Cancelled", "requested", "pending", "REQUESTED", "PENDING"):
			with self.subTest(status=status):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_transfer(status=status)

	def test_transfers_are_born_pending(self) -> None:
		# A transfer that mints directly in a terminal state never existed:
		# consumption happens through the service's accept flow on a live
		# pending record, never at insert time.
		for status in ("Accepted", "Declined"):
			with self.subTest(status=status):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_transfer(status=status)

	def test_pending_transfer_reaches_terminal_states(self) -> None:
		for status in ("Accepted", "Declined"):
			transfer = self._make_transfer()
			transfer.status = status
			transfer.save(ignore_permissions=True)

			self.assertEqual(frappe.db.get_value("Ceto Order Transfer", transfer.name, "status"), status)

	def test_terminal_transfers_cannot_change_status(self) -> None:
		for terminal in ("Accepted", "Declined"):
			transfer = self._make_transfer()
			transfer.status = terminal
			transfer.save(ignore_permissions=True)

			loaded = frappe.get_doc("Ceto Order Transfer", transfer.name)
			for status in ("Pending", "Declined" if terminal == "Accepted" else "Accepted"):
				loaded.status = status
				with self.subTest(terminal=terminal, status=status):
					with self.assertRaises(frappe.exceptions.ValidationError):
						loaded.save(ignore_permissions=True)

			# A failed save stamps the in-memory copy with its attempted
			# timestamp, so reload before the idempotent re-save of the
			# terminal state — which stays legal.
			reloaded = frappe.get_doc("Ceto Order Transfer", transfer.name)
			reloaded.status = terminal
			reloaded.save(ignore_permissions=True)

	def test_emails_are_optional_and_stripped(self) -> None:
		transfer = self._make_transfer()
		self.assertIsNone(transfer.original_email)
		self.assertIsNone(transfer.new_email)

		padded = self._make_transfer(
			original_email="  guest@example.com  ",
			new_email="  claimer@example.com  ",
		)
		self.assertEqual(padded.original_email, "guest@example.com")
		self.assertEqual(padded.new_email, "claimer@example.com")

		blank = self._make_transfer(original_email="   ")
		self.assertIsNone(blank.original_email)

	def test_many_transfers_may_attach_to_one_order(self) -> None:
		# One active transfer per order is the transfer service's locked
		# invariant, not a schema constraint: cancel removes the record and
		# expiry frees the order for a fresh request, and a terminal record
		# stays addressable beside a new pending one. The schema therefore
		# holds any number of records per order reference.
		first = self._make_transfer()
		self._make_transfer()

		first.status = "Accepted"
		first.save(ignore_permissions=True)

		third = self._make_transfer()
		self.assertEqual(third.status, "Pending")
		self.assertEqual(
			frappe.db.count("Ceto Order Transfer", {"order_reference": self.order_reference.name}),
			3,
		)
