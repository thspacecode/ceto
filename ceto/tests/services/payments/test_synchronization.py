"""paygi success-hook synchronization: capture exactly once, race-safely.

The ``paygi_payment_succeeded`` hook hands Ceto the succeeded
``Payment Attempt``; Ceto captures the session it references (the
reference every cart charge carries) and completes the collection — but
only when the captured session is still the collection's current one,
and only from a decision taken under the collection-then-session row
locks. These tests pin the handshake and its exactly-once, replay-safe
behavior, its answer to a session recreation racing the webhook, and the
failure contract (a mid-sync failure propagates and the caller's
rollback leaves both rows unchanged).

paygi is not installed on the test site, so the attempts are stub objects
carrying the only attributes the handler reads (``reference_doctype`` /
``reference_name``) — the real documents are paygi's own.
"""

from dataclasses import dataclass
from threading import Event, Thread, Timer
from unittest import mock

import frappe

from ceto.services.carts.quotation import CartService
from ceto.services.payments.collections import PaymentCollections
from ceto.services.payments.sessions import PaymentSessions
from ceto.services.payments.synchronization import (
	attempt_status_to_session,
	capture_session,
	on_paygi_payment_succeeded,
	session_for_attempt,
)
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.services.payments.test_sessions import (
	BEAM,
	StubProvider,
	session_payload,
	stub_registry,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class SyncFailure(Exception):
	"""A provider-delivery failure raised mid-synchronization."""


@dataclass
class AttemptStub:
	"""The succeeded ``Payment Attempt`` as the success hook hands it over."""

	reference_doctype: str = "Ceto Payment Session"
	reference_name: str = ""
	name: str = "attempt_1"
	provider: str = "beam"
	status: str = "Succeeded"
	amount_minor: int = 100
	currency: str = "USD"


class RecordingCharger:
	def __init__(self, response) -> None:
		self.response = response

	def __call__(self, request):
		return self.response


class TestCaptureSynchronization(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.reference, self.quotation = CartService().create(StoreCreateCart(email="guest@example.com"))
		self.quotation.append("items", {"item_code": self.masters.item, "qty": 1})
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()
		self.collection = PaymentCollections.ensure_collection(self.reference.cart_id)

	def _pending_session(self) -> "frappe._dict":
		service = PaymentSessions(
			registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger(None)
		)
		service.initialize_session(self.collection.payment_collection_id, session_payload(BEAM))
		return frappe.db.get_value(
			"Ceto Payment Session",
			{"payment_collection": self.collection.name, "is_current": 1},
			["name", "payment_collection", "is_current", "status"],
			as_dict=True,
		)

	def _current_session_row(self) -> "frappe._dict | None":
		return frappe.db.get_value(
			"Ceto Payment Session",
			{"payment_collection": self.collection.name, "is_current": 1},
			["name", "status"],
			as_dict=True,
		)

	def _collection_status(self) -> str:
		return frappe.db.get_value("Ceto Payment Collection", self.collection.name, "status")

	def _session_status(self, session_id: str) -> str:
		return frappe.db.get_value("Ceto Payment Session", session_id, "status")

	def _change_cart_total(self, qty: int) -> None:
		self.quotation.items[0].qty = qty
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()

	def test_a_succeeded_attempt_captures_its_session_and_completes_the_collection(self):
		session = self._pending_session()

		on_paygi_payment_succeeded(AttemptStub(reference_name=session.name))

		self.assertEqual(self._session_status(session.name), "captured")
		self.assertEqual(self._collection_status(), "completed")

	def test_capture_is_exactly_once(self):
		session = self._pending_session()

		self.assertTrue(capture_session(session.name))
		self.assertFalse(capture_session(session.name))
		# A replayed webhook delivery is a no-op too.
		on_paygi_payment_succeeded(AttemptStub(reference_name=session.name))
		self.assertEqual(self._session_status(session.name), "captured")
		self.assertEqual(self._collection_status(), "completed")

	def test_a_stale_session_captures_as_history_only(self):
		session = self._pending_session()
		# The cart total changes and a fresh current session replaces it.
		self._change_cart_total(qty=3)
		PaymentSessions(
			registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger(None)
		).initialize_session(self.collection.payment_collection_id, session_payload(BEAM))
		self.assertEqual(frappe.db.get_value("Ceto Payment Session", session.name, "is_current"), 0)

		self.assertTrue(capture_session(session.name))

		self.assertEqual(self._session_status(session.name), "captured")
		# The collection keeps tracking its live (unpaid) session.
		self.assertEqual(self._collection_status(), "not_paid")
		current = self._current_session_row()
		self.assertNotEqual(current.name, session.name)
		self.assertEqual(current.status, "pending")

	def test_a_recreation_behind_a_webhook_capture_resets_then_recompletes(self):
		session = self._pending_session()

		# The webhook wins the race: capture and completion land first.
		self.assertTrue(capture_session(session.name))
		self.assertEqual(self._collection_status(), "completed")

		# The racing recreation lands behind it: the captured session is
		# history and the collection tracks the fresh unpaid attempt again.
		self._change_cart_total(qty=3)
		PaymentSessions(
			registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger(None)
		).initialize_session(self.collection.payment_collection_id, session_payload(BEAM))
		self.assertEqual(self._collection_status(), "not_paid")
		fresh = self._current_session_row()
		self.assertIsNotNone(fresh)
		self.assertNotEqual(fresh.name, session.name)
		self.assertEqual(fresh.status, "pending")

		# The fresh session's own webhook completes the collection again.
		self.assertTrue(capture_session(fresh.name))
		self.assertEqual(self._collection_status(), "completed")
		self.assertEqual(frappe.db.get_value("Ceto Payment Session", session.name, "is_current"), 0)

	def test_a_failure_after_the_capture_rolls_back_session_and_collection(self):
		session = self._pending_session()
		real_set_value = frappe.db.set_value

		def failing_completion(doctype, name, *args, **kwargs):
			if doctype == "Ceto Payment Collection":
				raise SyncFailure("webhook delivery aborted mid-sync")
			return real_set_value(doctype, name, *args, **kwargs)

		frappe.db.savepoint("sync_failure")
		with mock.patch.object(frappe.db, "set_value", failing_completion):
			with self.assertRaises(SyncFailure):
				on_paygi_payment_succeeded(AttemptStub(reference_name=session.name))
		# The caller rolls its transaction back: the delivery will be
		# retried, and neither row answers for the failed capture.
		frappe.db.rollback(save_point="sync_failure")
		self.assertEqual(self._session_status(session.name), "pending")
		self.assertEqual(self._collection_status(), "not_paid")

	def test_foreign_attempts_are_ignored(self):
		session = self._pending_session()
		foreign = AttemptStub(reference_doctype="Sales Invoice", reference_name="SINV-FOREIGN")

		on_paygi_payment_succeeded(foreign)

		self.assertEqual(self._session_status(session.name), "pending")
		self.assertEqual(self._collection_status(), "not_paid")

	def test_unknown_and_non_captureable_sessions_are_left_alone(self):
		self.assertFalse(capture_session("payses_missing"))
		session = self._pending_session()
		frappe.db.set_value("Ceto Payment Session", session.name, "status", "canceled")
		self.assertFalse(capture_session(session.name))
		self.assertEqual(self._collection_status(), "not_paid")


class TestWebhookRacingRecreation(CetoTestSuite):
	"""The success webhook racing a session recreation, on real row locks.

	The recreation runs on its own database connection and parks holding
	the collection row lock, so the webhook cannot even read the session
	row until the recreation has committed: whatever the capture decides,
	it decides about the race's committed outcome, never about a pre-race
	snapshot. The fixture is committed first because the racer's
	transaction must be able to see and lock it.
	"""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.reference, self.quotation = CartService().create(StoreCreateCart(email="guest@example.com"))
		self.quotation.append("items", {"item_code": self.masters.item, "qty": 1})
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()
		self.collection = PaymentCollections.ensure_collection(self.reference.cart_id)
		PaymentSessions(
			registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger(None)
		).initialize_session(self.collection.payment_collection_id, session_payload(BEAM))
		# The recreation races because the cart's payable changed: the
		# committed session no longer answers for it, so the racer's
		# creation must replace it instead of reusing it.
		self.quotation.items[0].qty = 3
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()
		frappe.db.commit()  # nosemgrep - the racing connection must see and lock the rows

	def tearDown(self) -> None:
		frappe.db.rollback()
		self._discard_committed_rows()
		super().tearDown()

	def _discard_committed_rows(self) -> None:
		"""Delete this test's committed payment and cart rows; nothing lingers."""
		for name in frappe.get_all(
			"Ceto Payment Session", filters={"payment_collection": self.collection.name}, pluck="name"
		):
			frappe.delete_doc("Ceto Payment Session", name, ignore_permissions=True)
		frappe.delete_doc("Ceto Payment Collection", self.collection.name, ignore_permissions=True)
		frappe.delete_doc("Ceto Cart Reference", self.reference.cart_id, ignore_permissions=True)
		frappe.delete_doc("Quotation", self.quotation.name, force=1, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep - the discard must survive the tearDown rollback

	def _capture_with_deadlock_retry(self, session_id: str) -> bool:
		"""Run the capture with the retry a provider redelivery performs.

		This transaction's read view predates the racer's commit, so the
		first locking read of a row the racer changed raises Frappe's
		deadlock-class ``QueryDeadlockError`` (before any write) — a real
		webhook request would fail and be redelivered. The retry re-runs
		the capture on a fresh transaction, which is what that redelivery
		does.
		"""
		for attempt in range(3):
			try:
				return capture_session(session_id)
			except frappe.QueryDeadlockError:
				if attempt == 2:
					raise
				frappe.db.rollback()

	def test_the_capture_answers_the_raced_recreation_never_its_own_snapshot(self):
		stale = frappe.db.get_value(
			"Ceto Payment Session", {"payment_collection": self.collection.name, "is_current": 1}, "name"
		)
		booked = Event()
		release = Event()
		site, sites_path = frappe.local.site, getattr(frappe.local, "sites_path", None)

		def recreate():
			frappe.init(site, sites_path=sites_path or "sites")
			frappe.connect()
			try:
				frappe.set_user("Administrator")
				PaymentSessions(
					registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger(None)
				).initialize_session(self.collection.payment_collection_id, session_payload(BEAM))
				booked.set()  # the stale flip and the fresh session are written
				release.wait(30)
				frappe.db.commit()
			finally:
				frappe.destroy()

		racer = Thread(target=recreate, name="payment-session-recreation", daemon=True)
		racer.start()
		self.assertTrue(booked.wait(30), "the racing recreation never booked its session")
		# The webhook can only read the session once the racer releases the
		# collection row lock; release it from a watchdog while this thread
		# blocks inside the capture.
		watchdog = Timer(1.0, release.set)
		watchdog.daemon = True
		watchdog.start()
		try:
			captured = self._capture_with_deadlock_retry(stale)
		finally:
			release.set()
			watchdog.cancel()
			racer.join(30)

		self.assertTrue(captured)
		# Locking reads: the plain snapshot this transaction began with
		# predates the racer's commit.
		self.assertEqual(
			frappe.db.get_value("Ceto Payment Session", stale, "status", for_update=True), "captured"
		)
		self.assertEqual(frappe.db.get_value("Ceto Payment Session", stale, "is_current", for_update=True), 0)
		current = frappe.db.get_value(
			"Ceto Payment Session",
			{"payment_collection": self.collection.name, "is_current": 1},
			["name", "status"],
			as_dict=True,
			for_update=True,
		)
		self.assertIsNotNone(current)
		self.assertNotEqual(current.name, stale)
		self.assertEqual(current.status, "pending")
		self.assertEqual(
			frappe.db.get_value("Ceto Payment Collection", self.collection.name, "status", for_update=True),
			"not_paid",
		)


class TestSynchronizationHelpers(CetoTestSuite):
	def test_the_reference_answers_the_session(self):
		self.assertEqual(session_for_attempt(AttemptStub(reference_name="payses_1")), "payses_1")
		foreign = AttemptStub(reference_doctype="Sales Order", reference_name="SO-1")
		self.assertIsNone(session_for_attempt(foreign))

	def test_only_terminal_attempt_statuses_move_a_session(self):
		self.assertEqual(attempt_status_to_session("Succeeded"), "captured")
		self.assertEqual(attempt_status_to_session("Failed"), "error")
		self.assertEqual(attempt_status_to_session("Canceled"), "canceled")
		for in_flight in ("Initiated", "Requires Action", "Pending", "Unknown", None):
			with self.subTest(status=in_flight):
				self.assertIsNone(attempt_status_to_session(in_flight))
