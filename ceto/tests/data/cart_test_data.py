"""Thin adapter over the committed ``ceto.data.bootstrap_dev`` commerce baseline.

The Company, guest Customer, selling Price List, and catalog items are owned by
the bootstrap and imported once through ``ceto.tests.utils``; this module creates
no commerce masters. It only derives the cart ``ceto_cart`` configuration from
the same bootstrap settings, exposes the bootstrap items with their committed
rates, and layers test-only fixtures on top: one idempotent tax template so
cart totals carry a meaningful rate, the idempotent selling ``Shipping Rule``
fixtures Phase 4 shipping tests select from, the committed gift-card /
store-credit wallet fixtures Phase 5 tests apply, and a Website User linked to
its own Customer through a Contact for the authenticated-customer flows.
Currency is deliberately omitted: ``CartConfiguration`` resolves it from the
selling price list, which the bootstrap creates in the company currency.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import frappe

from ceto.data.base_importer import apply_values
from ceto.data.bootstrap_dev.dataset import ITEM_PRICES
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.services.carts.credits import hash_code
from ceto.tests.utils import boot_strap_test_master_data

TEST_TAX_ACCOUNT = "Ceto Test Cart Tax"
TEST_TAX_TEMPLATE_TITLE = "Ceto Test Cart Taxes"
TAX_RATE = 10.0
# A second, distinct template (own account, own rate) so configuration tests
# can watch a cart switch templates and prove stale rows are reloaded.
ALT_TEST_TAX_ACCOUNT = "Ceto Test Alt Cart Tax"
ALT_TEST_TAX_TEMPLATE_TITLE = "Ceto Test Alt Cart Taxes"
ALT_TAX_RATE = 5.0

TEST_SHIPPING_ACCOUNT = "Ceto Test Shipping Charges"
TEST_SHIPPING_COST_CENTER = "Ceto Test Shipping Cost Center"
SHIPPING_RULE_TYPE = "Selling"
SHIPPING_FLAT_RATE_LABEL = "Ceto Test Flat Rate"
SHIPPING_FLAT_RATE_AMOUNT = 50.0
SHIPPING_COUNTRY_RATE_LABEL = "Ceto Test Country Rate"
SHIPPING_COUNTRY_RATE_AMOUNT = 25.0
SHIPPING_DISABLED_RATE_LABEL = "Ceto Test Disabled Rate"


def _bootstrap_rate(item_code: str) -> float:
	"""Return the bootstrap selling rate for ``item_code`` as a float."""
	for seed in ITEM_PRICES:
		if seed.item_code == item_code:
			return float(seed.price_list_rate)
	raise ValueError(f"{item_code} is not priced by the ceto.data.bootstrap_dev dataset")


ITEM_PRICE = _bootstrap_rate("DEV-TSHIRT-001")
ITEM_PRICE_B = _bootstrap_rate("DEV-HOODIE-001")


class CartTestData:
	"""Expose the bootstrap commerce masters as cart test configuration."""

	def __init__(self) -> None:
		# Coupon Code names are globally unique, and the API suite commits its
		# coupons so they survive request rollbacks. Keep test codes unique.
		self.suffix = uuid.uuid4().hex[:8]
		self.settings: BootstrapSettings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(self.settings)
		# Same identity rule as the bootstrap: the guest is located by
		# customer_name, never by docname.
		self.customer = frappe.db.get_value("Customer", {"customer_name": self.settings.guest_customer_name})
		self.price_list = self.settings.selling_price_list
		# Catalog items and their rates come verbatim from the bootstrap.
		self.item = "DEV-TSHIRT-001"
		self.other_item = "DEV-HOODIE-001"
		self.taxes_and_charges = self._make_tax_template(TEST_TAX_TEMPLATE_TITLE, TAX_RATE, TEST_TAX_ACCOUNT)
		self.alt_taxes_and_charges = self._make_tax_template(
			ALT_TEST_TAX_TEMPLATE_TITLE, ALT_TAX_RATE, ALT_TEST_TAX_ACCOUNT
		)
		# Phase 4 shipping fixtures: committed Selling rules the shipping tests
		# select by label. All of them reuse the bootstrap company and its
		# masters; none introduces a parallel set of business data.
		self.shipping_country = self._ensure_country(self.settings.wizard_country)
		self.shipping_account = self._shipping_account(self.company)
		self.shipping_cost_center = self._shipping_cost_center(self.company)
		self.flat_rate_rule = self.make_shipping_rule(
			SHIPPING_FLAT_RATE_LABEL, shipping_amount=SHIPPING_FLAT_RATE_AMOUNT
		)
		self.country_rate_rule = self.make_shipping_rule(
			SHIPPING_COUNTRY_RATE_LABEL,
			shipping_amount=SHIPPING_COUNTRY_RATE_AMOUNT,
			countries=(self.shipping_country,),
		)
		self.disabled_rate_rule = self.make_shipping_rule(SHIPPING_DISABLED_RATE_LABEL, disabled=1)

	def disable_stale_promotion_rules(self) -> None:
		"""Disable committed promotion fixtures left by earlier API tests."""
		rules: set[str] = set()
		for title_pattern in ("Ceto Coupon %", "Ceto APISAVE %"):
			rules.update(
				frappe.get_all(
					"Pricing Rule",
					filters={
						"company": self.company,
						"coupon_code_based": 1,
						"title": ("like", title_pattern),
					},
					pluck="name",
				)
			)
		for rule in rules:
			frappe.db.set_value("Pricing Rule", rule, "disable", 1, update_modified=False)
		if rules:
			frappe.db.commit()  # nosemgrep

	@property
	def configuration(self) -> dict[str, Any]:
		return {
			"guest_customer": self.customer,
			"company": self.company,
			"selling_price_list": self.price_list,
			"taxes_and_charges": self.taxes_and_charges,
			"territory": self.settings.guest_territory,
			"default_region_id": "reg_test",
			"default_sales_channel_id": "sc_test",
		}

	def _make_tax_template(self, title: str, rate: float, account_name: str) -> str:
		"""Layer a fixed-name tax template over the bootstrap baseline.

		The bootstrap ships only zero-rated masters, and cart tests still need
		tax rates worth asserting on. Each template is anchored on a dedicated
		test account (so rows of two templates are distinguishable by account)
		and reused whenever it already exists, so re-instantiating
		``CartTestData`` converges instead of duplicating master data.
		Freshly created records are committed at once because the router rolls
		back the open transaction when it converts a failed request into an
		error response, and the template must outlive that rollback.
		"""
		company = self.company
		account = frappe.db.get_value(
			"Account", {"account_name": account_name, "company": company, "is_group": 0}
		)
		if not account:
			abbr = frappe.db.get_value("Company", company, "abbr")
			account = (
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": account_name,
						"parent_account": f"Duties and Taxes - {abbr}",
						"company": company,
						"account_type": "Tax",
						"is_group": 0,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
			frappe.db.commit()  # nosemgrep
		template = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"title": title, "company": company}
		)
		if template:
			return template
		template = (
			frappe.get_doc(
				{
					"doctype": "Sales Taxes and Charges Template",
					"title": title,
					"company": company,
					"is_default": 0,
					"taxes": [
						{
							"charge_type": "On Net Total",
							"account_head": account,
							"rate": rate,
							"description": account_name,
							"included_in_print_rate": 0,
						}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.commit()  # nosemgrep
		return template

	def make_shipping_rule(
		self,
		label: str,
		*,
		company: str | None = None,
		account: str | None = None,
		disabled: int = 0,
		countries: Sequence[str] = (),
		shipping_amount: float = SHIPPING_FLAT_RATE_AMOUNT,
	) -> str:
		"""Create or converge one committed test ``Shipping Rule``; return its name.

		Public so a shipping test can bind a variant to a company other than the
		bootstrap company — the wrong-company rejection case — by passing its own
		label and company, or to a dedicated account — the replacement case that
		must drop a charge row — by passing ``account`` instead of duplicating
		bootstrap masters. The account and cost center always resolve inside the
		same company, and ``label`` is also the document name
		(``autoname = field:label``), so labels are the global identities
		shipping options reference. Creation commits at once because the router
		rolls back the open transaction when it converts a failed request into
		an error response, and the rule must outlive that rollback.
		"""
		company = company or self.company
		account = account or self._shipping_account(company)
		name = frappe.db.get_value("Shipping Rule", {"label": label})
		if not name:
			rule = frappe.get_doc(
				{
					"doctype": "Shipping Rule",
					"label": label,
					"shipping_rule_type": SHIPPING_RULE_TYPE,
					"company": company,
					"account": account,
					"cost_center": self._shipping_cost_center(company),
					"calculate_based_on": "Fixed",
					"shipping_amount": shipping_amount,
					"disabled": disabled,
					"countries": [{"country": country} for country in countries],
				}
			)
			rule.insert(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep
			return rule.name

		rule = frappe.get_doc("Shipping Rule", name)
		changed = apply_values(
			rule,
			{
				"shipping_rule_type": SHIPPING_RULE_TYPE,
				"company": company,
				"account": account,
				"cost_center": self._shipping_cost_center(company),
				"calculate_based_on": "Fixed",
				"shipping_amount": shipping_amount,
				"disabled": disabled,
			},
		)
		if [row.country for row in rule.countries or []] != list(countries):
			rule.set("countries", [{"country": country} for country in countries])
			changed = True
		if changed:
			rule.save(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep
		return name

	def make_gift_card(
		self,
		code: str,
		*,
		credit_total: float = 100.0,
		customer: str | None = None,
		currency: str | None = None,
		company: str | None = None,
		expires_at: Any = None,
	) -> str:
		"""Create or converge one committed gift-card wallet; return its name.

		Public so credit tests can bind a card to another currency — the
		wrong-currency rejection case — or expire it, without duplicating
		masters. The wallet id is derived from the code hash, so the same
		code converges on the same wallet in every test run instead of
		colliding with the company-scoped code uniqueness. Creation (and
		any convergence) commits at once because the router rolls back the
		open transaction when it converts a failed request into an error
		response, and the wallet must outlive that rollback.
		"""
		fields = {
			"wallet_type": "Gift Card",
			"provider": "loyalty",
			"company": company or self.company,
			"customer": customer,
			"currency": currency or self.settings.wizard_currency,
			"code_hash": hash_code(code),
			"code_hint": gift_card_code_hint(code),
			"expires_at": expires_at,
			"credit_total": credit_total,
		}
		name = frappe.db.get_value(
			"Ceto Credit Wallet", {"company": fields["company"], "code_hash": fields["code_hash"]}
		)
		if not name:
			name = (
				frappe.get_doc(
					{"doctype": "Ceto Credit Wallet", "wallet_id": f"gc_{fields['code_hash'][:16]}", **fields}
				)
				.insert(ignore_permissions=True)
				.name
			)
			frappe.db.commit()  # nosemgrep
			return name
		wallet = frappe.get_doc("Ceto Credit Wallet", name)
		if apply_values(wallet, fields):
			wallet.save(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep
		return name

	def make_store_credit_wallet(
		self,
		*,
		credit_total: float = 100.0,
		customer: str | None = None,
		currency: str | None = None,
		company: str | None = None,
	) -> str:
		"""Create or converge one committed store-credit wallet; return its name.

		The customer-owned wallet (bootstrap guest by default) is unique per
		company and currency, so re-instantiating converges on the existing
		wallet — resetting its balance to ``credit_total`` — instead of
		colliding with the customer-wallet uniqueness rule. Commits at once,
		like :meth:`make_gift_card`, to survive request rollbacks.
		"""
		fields = {
			"wallet_type": "Store Credit",
			"provider": "loyalty",
			"company": company or self.company,
			"customer": customer or self.customer,
			"currency": currency or self.settings.wizard_currency,
			"credit_total": credit_total,
			"debit_total": 0,
		}
		name = frappe.db.get_value(
			"Ceto Credit Wallet",
			{
				"company": fields["company"],
				"currency": fields["currency"],
				"customer": fields["customer"],
				"wallet_type": "Store Credit",
			},
		)
		if not name:
			name = (
				frappe.get_doc(
					{"doctype": "Ceto Credit Wallet", "wallet_id": f"sca_{uuid.uuid4().hex[:16]}", **fields}
				)
				.insert(ignore_permissions=True)
				.name
			)
			frappe.db.commit()  # nosemgrep
			return name
		wallet = frappe.get_doc("Ceto Credit Wallet", name)
		if apply_values(wallet, fields):
			wallet.save(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep
		return name

	def _shipping_account(self, company: str) -> str:
		"""Reuse or create the leaf income account shipping charges post to."""
		account = frappe.db.get_value(
			"Account", {"account_name": TEST_SHIPPING_ACCOUNT, "company": company, "is_group": 0}
		)
		if account:
			return account
		abbr = frappe.db.get_value("Company", company, "abbr")
		account = (
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": TEST_SHIPPING_ACCOUNT,
					"parent_account": f"Direct Income - {abbr}",
					"company": company,
					"is_group": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.commit()  # nosemgrep
		return account

	def _shipping_cost_center(self, company: str) -> str:
		"""Resolve the shipping cost center without duplicating company masters.

		A bootstrapped company already carries the wizard's default cost center;
		a company without one falls back to its single leaf cost center, and only
		a company with several leaves and no default earns a dedicated committed
		row (reused by name on reruns).
		"""
		default = frappe.db.get_value("Company", company, "cost_center")
		if default:
			return default
		dedicated = frappe.db.get_value(
			"Cost Center", {"cost_center_name": TEST_SHIPPING_COST_CENTER, "company": company, "is_group": 0}
		)
		if dedicated:
			return dedicated
		leaves = frappe.get_all("Cost Center", filters={"company": company, "is_group": 0}, pluck="name")
		if len(leaves) == 1:
			return leaves[0]
		abbr = frappe.db.get_value("Company", company, "abbr")
		cost_center = (
			frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": TEST_SHIPPING_COST_CENTER,
					"company": company,
					"parent_cost_center": f"{company} - {abbr}",
					"is_group": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.commit()  # nosemgrep
		return cost_center

	def _ensure_country(self, country: str) -> str:
		"""Return ``country``, creating the standard master row only if missing."""
		if frappe.db.exists("Country", country):
			return country
		frappe.get_doc({"doctype": "Country", "country_name": country}).insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep
		return country


def gift_card_code_hint(code: str) -> str:
	"""Return the masked hint shape the DocType documents: ``GC-****-1234``."""
	return f"GC-****-{code[-4:]}"


def make_customer_with_user(label: str) -> tuple[str, str]:
	"""Create a Website User linked to its own Customer through a Contact.

	Returns ``(email, customer)``. The records stay uncommitted: callers
	that must survive a request rollback (the router rolls back the open
	transaction when it converts an error into a response) commit after
	setting up their fixtures, like the promotion API tests do.
	"""
	email = f"ceto.cart.{label}.{uuid.uuid4().hex[:8]}@example.com"
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": f"Cart {label}",
			"user_type": "Website User",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"Cart {label} {uuid.uuid4().hex[:8]}",
			"customer_type": "Individual",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": "All Territories",
		}
	)
	customer.flags.ignore_permissions = True
	customer.insert()
	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": f"Cart {label}",
			"email_id": email,
			"user": email,
			"links": [{"link_doctype": "Customer", "link_name": customer.name}],
		}
	)
	contact.flags.ignore_permissions = True
	contact.insert()
	return email, customer.name
