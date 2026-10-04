import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class CetoCartCreditReservation(Document):
	"""Amount a cart Quotation holds against one wallet.

	Reservations are the reservation-aware side of the wallet balance: every
	open ``Reserved`` reservation reduces what later reservations may hold,
	while ``Released`` and ``Consumed`` ones stop counting. Amounts must be
	positive — a hold with no value would only fake a balance.
	"""

	def validate(self) -> None:
		self._validate_amount()
		quotation = self._validate_quotation()
		self._validate_wallet(quotation)

	def _validate_amount(self) -> None:
		if flt(self.amount) <= 0:
			frappe.throw(_("Reservation amount must be positive"))

	def _validate_quotation(self) -> dict:
		quotation = frappe.db.get_value(
			"Quotation", self.quotation, ["company", "currency", "docstatus", "order_type"], as_dict=True
		)
		if quotation is None or quotation.order_type != "Shopping Cart":
			frappe.throw(_("Reservation must point to a Shopping Cart Quotation"))
		if quotation.docstatus == 2:
			frappe.throw(_("Reservation must not point to a cancelled Quotation"))
		return quotation

	def _validate_wallet(self, quotation: dict) -> dict:
		wallet = frappe.db.get_value(
			"Ceto Credit Wallet",
			self.wallet,
			["company", "currency", "expires_at", "credit_total", "debit_total"],
			as_dict=True,
		)
		if wallet is None:
			frappe.throw(_("Reservation must point to an existing wallet"))
		if wallet.company != quotation.company:
			frappe.throw(_("Reservation wallet must belong to the Quotation's company"))
		if wallet.currency != self.currency or wallet.currency != quotation.currency:
			frappe.throw(_("Reservation must use the wallet and Quotation currency"))
		if wallet.expires_at and wallet.expires_at < now_datetime():
			frappe.throw(_("Wallet {0} has expired").format(self.wallet))
		self._validate_available_balance(wallet)
		return wallet

	def _validate_available_balance(self, wallet: dict) -> None:
		"""Compare the amount against the balance net of the other open holds.

		Availability derives from the ledger totals (``credit_total -
		debit_total``, the authority), not the stored ``balance`` snapshot,
		mirroring the locked-row arithmetic in the cart credit service.
		"""
		available = flt(wallet.credit_total) - flt(wallet.debit_total) - self._reserved_excluding()
		if flt(self.amount) > available:
			frappe.throw(
				_("Wallet {0} has {1} available after open reservations, {2} requested").format(
					self.wallet, available, flt(self.amount)
				)
			)

	def _reserved_excluding(self) -> float:
		"""Sum the wallet's other open ``Reserved`` holds."""
		reserved = frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"wallet": self.wallet, "name": ("!=", self.name), "status": "Reserved"},
			pluck="amount",
		)
		return flt(sum(flt(amount) for amount in reserved))
