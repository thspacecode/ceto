import frappe
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
			frappe.throw("Reservation amount must be positive")

	def _validate_quotation(self) -> dict:
		quotation = frappe.db.get_value(
			"Quotation", self.quotation, ["company", "currency", "docstatus", "order_type"], as_dict=True
		)
		if quotation is None:
			frappe.throw("Reservation must point to a Shopping Cart Quotation")
		if quotation.order_type != "Shopping Cart":
			frappe.throw("Reservation must point to a Shopping Cart Quotation")
		if quotation.docstatus == 2:
			frappe.throw("Reservation must not point to a cancelled Quotation")
		return quotation

	def _validate_wallet(self, quotation: dict) -> dict:
		wallet = frappe.db.get_value(
			"Ceto Credit Wallet",
			self.wallet,
			["company", "currency", "expires_at", "balance"],
			as_dict=True,
		)
		if wallet is None:
			frappe.throw("Reservation must point to an existing wallet")
		if wallet.company != quotation.company:
			frappe.throw("Reservation wallet must belong to the Quotation's company")
		if wallet.currency != self.currency or wallet.currency != quotation.currency:
			frappe.throw("Reservation must use the wallet and Quotation currency")
		if wallet.expires_at and wallet.expires_at < now_datetime():
			frappe.throw(f"Wallet {self.wallet} has expired")
		self._validate_available_balance(wallet.balance)
		return wallet

	def _validate_available_balance(self, balance: float) -> None:
		"""Compare the amount against the balance net of the other open holds."""
		reserved = frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"wallet": self.wallet, "name": ("!=", self.name), "status": "Reserved"},
			pluck="amount",
		)
		available = flt(balance) - flt(sum(flt(amount) for amount in reserved))
		if flt(self.amount) > available:
			frappe.throw(
				f"Wallet {self.wallet} has {available} available after open reservations,"
				f" {flt(self.amount)} requested"
			)
