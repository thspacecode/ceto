"""Mechanical checks on docs/orders/field-mapping.md.

These tests are deliberately shallow: they pin that the required sections,
classifications, recorded decisions and the upstream-facts/Ceto-decisions
distinction exist so later phases can rely on the document, plus phrase-level
guards for the decisions that supersede or harden against the preliminary
PRD (ownership independent of cart history, digest-only tokens, the 7-day
Ceto lifetime, requester semantics, capability-based retrieval) and the list
``status`` filter hardening, whose pinned ``OrderStatus`` union is compared
against the code's own Literal so document and implementation cannot drift.
The implemented-route boundary the document states is compared against the
surface ``ceto/api/store/orders.py`` actually registers — the full pinned
six-route surface, complete since Phase 5 — and the README's Orders status
rows are parsed and pinned to the same surface, so neither prose nor README
can outgrow the code.
"""

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "orders" / "field-mapping.md"

# Read from source, not imported: importing the manifest initializes the
# orders package, whose carts-before-orders import order constraint is
# documented in the manifest test — a file read carries no such coupling.
MANIFEST = (
	Path(__file__).resolve().parents[3] / "ceto" / "types" / "http" / "store" / "orders" / "manifest.py"
)

ENTITIES = (
	Path(__file__).resolve().parents[3] / "ceto" / "types" / "http" / "store" / "orders" / "entities.py"
)

ORDERS_API = Path(__file__).resolve().parents[3] / "ceto" / "api" / "store" / "orders.py"

README = Path(__file__).resolve().parents[3] / "README.md"

DAY_COUNT_RE = re.compile(r"\b(\d+)[ -]days?\b")
LIFETIME_TITLE_RE = re.compile(r"\*\*Lifetime — (\d+) days")
LIFETIME_SENTENCE_RE = re.compile(r"expires \*\*(\d+) days after its request was created\*\*")
MANIFEST_LIFETIME_RE = re.compile(r"^ORDER_TRANSFER_LIFETIME_DAYS\s*=\s*(\d+)\s*$", re.MULTILINE)

#: The routes ``ceto/api/store/orders.py`` actually registers (decorator
#: method and path), parsed from source like the manifest read above.
REGISTERED_ROUTE_RE = re.compile(r'@ceto_router\.(\w+)\("([^"]+)"')

#: The registered surface since Phase 5: the whole pinned manifest, wired
#: exactly once — retrieval guest-dispatchable, listing and the transfer
#: request/cancel pair customer-authenticated, and the token-authorized
#: accept/decline pair guest-dispatchable like retrieval.
REGISTERED_ROUTES = {
	("GET", "/store/orders/{id}"),
	("GET", "/store/orders"),
	("POST", "/store/orders/{id}/transfer/request"),
	("POST", "/store/orders/{id}/transfer/accept"),
	("POST", "/store/orders/{id}/transfer/cancel"),
	("POST", "/store/orders/{id}/transfer/decline"),
}

#: The doc's pinned ``OrderStatus`` union list versus the code Literal the
#: ``StoreOrderFilters.status`` validation actually restricts to.
DOC_ORDER_STATUS_UNION_RE = re.compile(r"`OrderStatus` = `([^`]+)`")
CODE_ORDER_STATUS_RE = re.compile(r"^OrderStatus = Literal\[(.*?)\]\s*$", re.MULTILINE)

REQUIRED_SECTIONS = (
	"Pinned routes (Phase 0)",
	"Order → ERPNext data sources",
	"Status mapping",
	"Authorization and ownership",
	"Publishable-key scope",
	"List filters and stable ordering",
	"Transfer lifecycle",
	"Deliberate omissions",
	"Recorded Decisions",
	"Phase 0 boundary",
)

ALLOWED_CLASSIFICATIONS = {"direct", "derived", "gap", "direct/derived"}

REQUIRED_DECISION_KEYWORDS = (
	("public id", "order reference"),
	("owner_customer", "atomically"),
	("cart reference", "backfill"),
	("guest", "capability"),
	("publishable-key scope", "404"),
	("pending", "not_paid"),
	("creation desc", "order_id asc"),
	("$and", "invalid_data"),
	("ceto_order_transfer_requested", "hook"),
	("no recipient identifier", "requesting customer"),
	("digest", "plaintext"),
	("7-day", "not_allowed"),
	("expiry", "not_allowed"),
	("update_order_email", "never"),
	("no custom fields",),
)

REQUIRED_CONCEPTS = (
	("order_id", "Ceto Order Reference"),
	("customer_id", "owner_customer"),
	("owner_customer", "Ceto Order Reference"),
	("currency_code", "Sales Order.currency"),
	("items[]", "Sales Order Item"),
	("shipping_methods[]", "Shipping Rule"),
	("credit_line_total", "Ceto Cart Credit Reservation"),
	("status", "pending"),
	("token", "ceto_order_transfer_requested"),
	("digest", "SHA-256"),
)

PINNED_ROUTES = (
	"/store/orders/{id}",
	"/store/orders",
	"/store/orders/{id}/transfer/request",
	"/store/orders/{id}/transfer/accept",
	"/store/orders/{id}/transfer/cancel",
	"/store/orders/{id}/transfer/decline",
)

VERIFICATION_SOURCES = (
	"@medusajs/js-sdk@2.21.1",
	"@medusajs/types@2.21.1",
	"@medusajs/medusa@2.21.1",
	"dist/store/index.js",
	"dist/http/order/store/payloads.d.ts",
	"dist/api/store/orders/middlewares.js",
)

TABLE_ROW_RE = re.compile(r"^\|[^|]+\|[^|]+\|[^|]+\|$")

DECISION_RE = re.compile(r"^\d+\. \*\*(.+?)\*\*(.*?)(?=^\d+\. |\Z)", re.MULTILINE | re.DOTALL)

#: The Phase 0 implementation must not regress to these preliminary-PRD claims.
FORBIDDEN_PHRASES = (
	# Ownership must live on the order reference, not the immutable cart.
	"never copies it onto the order reference",
	# Ceto never persists the plaintext transfer token.
	"stores the single-use UUID token",
	"no server-side expiry (upstream parity",
)


def mapping_rows(text: str) -> list[str]:
	return [
		line
		for line in text.splitlines()
		if TABLE_ROW_RE.match(line) and "classification" not in line.lower() and "---" not in line
	]


def recorded_decisions(text: str) -> list[tuple[str, str]]:
	return re.findall(DECISION_RE, text)


def readme_order_statuses() -> dict[tuple[str, str], str]:
	"""Parse the Orders table's Method/Route/Status rows out of the README."""
	section = README.read_text().split("### Orders", 1)[1].split("\n### ", 1)[0]
	statuses: dict[tuple[str, str], str] = {}
	for line in section.splitlines():
		if not line.startswith("|"):
			continue
		columns = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
		if columns[0] == "Method" or set(columns[0]) <= {"-"}:
			continue
		statuses[(columns[0], columns[1])] = columns[2]
	return statuses


class TestOrdersFieldMappingDoc(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.text = DOC.read_text()
		cls.flat = " ".join(cls.text.split())

	def test_doc_exists_and_is_not_empty(self):
		self.assertTrue(DOC.is_file())
		self.assertGreater(len(self.text), 1000)

	def test_required_sections_present(self):
		for section in REQUIRED_SECTIONS:
			with self.subTest(section=section):
				self.assertIn(f"## {section}", self.text)

	def test_every_mapping_row_uses_known_classification(self):
		rows = mapping_rows(self.text)
		self.assertGreaterEqual(len(rows), 12)
		for row in rows:
			classification = row.rsplit("|", 2)[-2].strip().lower()
			with self.subTest(row=row):
				self.assertIn(classification, ALLOWED_CLASSIFICATIONS)

	def test_all_three_classifications_are_used(self):
		used = {row.rsplit("|", 2)[-2].strip().lower() for row in mapping_rows(self.text)}
		self.assertLessEqual({"direct", "derived", "gap"}, used)

	def test_customer_id_maps_to_the_effective_owner(self):
		"""``customer_id`` reads the order reference owner, with the legacy cart fallback."""
		row = next(row for row in mapping_rows(self.text) if row.startswith("| `customer_id`"))
		self.assertIn("Ceto Order Reference.owner_customer", row)
		self.assertIn("Ceto Cart Reference.owner_customer", row)
		self.assertIn("atomically", row)
		self.assertIn("backfill", row)

	def test_pinned_routes_are_all_documented(self):
		for path in PINNED_ROUTES:
			with self.subTest(path=path):
				self.assertIn(f"`{path}`", self.text)

	def test_verification_sources_are_cited(self):
		for source in VERIFICATION_SOURCES:
			with self.subTest(source=source):
				self.assertIn(source, self.text)

	def test_upstream_facts_and_ceto_decisions_are_distinguished(self):
		self.assertGreaterEqual(self.text.count("**Upstream contract fact"), 4)
		self.assertGreaterEqual(self.text.count("**Ceto decision"), 4)

	def test_key_concepts_are_mapped(self):
		for concept, target in REQUIRED_CONCEPTS:
			with self.subTest(concept=concept):
				self.assertIn(concept, self.text)
				self.assertIn(target, self.text)

	def test_thirteen_decisions_are_recorded(self):
		decision_lines = re.findall(r"^\d+\. \*\*", self.text, re.MULTILINE)
		self.assertEqual(len(decision_lines), 13)

	def test_decisions_cover_required_topics(self):
		decisions = recorded_decisions(self.text)
		self.assertEqual(len(decisions), 13)
		for keywords in REQUIRED_DECISION_KEYWORDS:
			matched = any(all(k.lower() in (t + " " + b).lower() for k in keywords) for t, b in decisions)
			with self.subTest(keywords=keywords):
				self.assertTrue(matched)

	def test_ownership_is_independent_of_cart_history(self):
		"""The order-reference snapshot owns; the immutable cart is fallback only."""
		decisions = {
			title.lower(): " ".join((title + " " + body).split()).lower()
			for title, body in recorded_decisions(self.text)
			if "effective ownership" in title.lower() or "legacy ownership fallback" in title.lower()
		}
		self.assertEqual(len(decisions), 2)
		ownership = next(text for title, text in decisions.items() if "effective ownership" in title)
		self.assertIn("owner_customer", ownership)
		self.assertIn("snapshot", ownership)
		self.assertIn("atomically", ownership)
		self.assertIn("never", ownership)
		fallback = next(text for title, text in decisions.items() if "legacy ownership fallback" in title)
		self.assertIn("owner_customer", fallback)
		self.assertIn("snapshot", fallback)
		self.assertIn("backfill", fallback)
		self.assertIn("never the live source", fallback)

	def test_transfer_token_is_never_persisted_as_plaintext(self):
		"""Only a digest is stored; the plaintext is handed to the hook once."""
		self.assertIn("SHA-256 digest", self.flat)
		self.assertIn("discarded", self.flat)
		self.assertIn("deliberately hardens", self.flat)
		self.assertIn("upstream stores the plaintext token", self.flat)
		storage = next(
			" ".join((t + " " + b).split()).lower()
			for t, b in recorded_decisions(self.text)
			if "digest-only storage" in t.lower()
		)
		self.assertIn("ceto_order_transfer_requested", storage)
		self.assertIn("digest", storage)
		self.assertIn("plaintext", storage)
		self.assertIn("discards", storage)

	def test_transfer_lifetime_is_a_ceto_decision_not_upstream_parity(self):
		matches = [
			(t + " " + b).lower()
			for t, b in recorded_decisions(self.text)
			if "7-day" in (t + " " + b).lower()
		]
		self.assertEqual(len(matches), 1)
		lifetime = " ".join(matches[0].split())
		self.assertIn("not_allowed", lifetime)
		self.assertIn("ceto decision", lifetime)
		self.assertIn("from request creation", lifetime)
		self.assertNotIn("upstream parity", lifetime)
		self.assertNotIn("no server-side expiry", lifetime)

	def test_expiry_decision_body_pins_exactly_seven_days(self):
		"""The lifetime decision body states exactly 7 days — no other count."""
		decisions = [
			" ".join((title + " " + body).split()).lower()
			for title, body in recorded_decisions(self.text)
			if "lifetime" in title.lower()
		]
		self.assertEqual(len(decisions), 1)
		self.assertEqual(set(DAY_COUNT_RE.findall(decisions[0])), {"7"})
		self.assertIn("7-day lifetime", decisions[0])
		self.assertIn("from request creation", decisions[0])

	def test_lifetime_prose_and_manifest_constant_agree_on_seven_days(self):
		"""The lifetime bullet, its expiry sentence and the manifest constant
		all pin 7 days — any one drifting to another number fails."""
		self.assertEqual(LIFETIME_TITLE_RE.findall(self.text), ["7"])
		self.assertEqual(LIFETIME_SENTENCE_RE.findall(self.text), ["7"])
		self.assertEqual(MANIFEST_LIFETIME_RE.findall(MANIFEST.read_text()), ["7"])

	def test_status_filter_union_hardening_is_recorded(self):
		"""The deliberate hardening and the upstream behavior it supersedes are
		both stated: the runtime validator accepts any string and yields an
		empty page, Ceto rejects out-of-union statuses as invalid data."""
		self.assertIn("looser than that pinned type", self.flat)
		self.assertIn("accepts any string", self.flat)
		self.assertIn("yields an empty page", self.flat)
		self.assertIn("validated against the pinned union", self.flat)
		self.assertIn("deliberate behavioral hardening", self.flat)
		self.assertIn("400 invalid_data", self.flat)

	def test_list_query_surface_decision_pins_the_status_union_hardening(self):
		decision = next(
			" ".join((title + " " + body).split()).lower()
			for title, body in recorded_decisions(self.text)
			if "list query surface" in title.lower()
		)
		self.assertIn("orderstatus", decision)
		self.assertIn("hardening", decision)
		self.assertIn("accepts any string", decision)
		self.assertIn("empty page", decision)
		self.assertIn("400 invalid_data", decision)

	def test_doc_status_union_matches_the_code_union(self):
		"""Mechanical drift pin: the union the hardening note restricts to must
		stay identical to the ``OrderStatus`` Literal the filters validate with
		(source-parsed, per the module comment above about imports)."""
		doc_unions = DOC_ORDER_STATUS_UNION_RE.findall(self.text)
		self.assertEqual(len(doc_unions), 1)
		doc_members = [member.strip() for member in doc_unions[0].split("|")]
		code_match = CODE_ORDER_STATUS_RE.search(ENTITIES.read_text())
		self.assertIsNotNone(code_match)
		code_members = re.findall(r'"([^"]+)"', code_match.group(1))
		self.assertTrue(code_members)
		self.assertEqual(doc_members, code_members)

	def test_transfer_requester_semantics_supersede_the_prd(self):
		"""The payload has no recipient: the requester seeks ownership for themselves."""
		self.assertIn("no recipient identifier", self.flat)
		self.assertIn("requesting customer", self.flat)
		self.assertIn("supersedes the PRD assumption", self.flat)
		self.assertIn("stored on the transfer", self.flat)

	def test_retrieval_stays_capability_based(self):
		"""Exact upstream compatibility resolves the PRD's open auth question."""
		self.assertIn("capability-based", self.flat)
		self.assertIn("guest-accessible", self.flat)
		self.assertIn("resolves the PRD's open authentication question", self.flat)
		self.assertIn("goal language referred to authenticated customers", self.flat)

	def test_no_preliminary_prd_claims_remain(self):
		for phrase in FORBIDDEN_PHRASES:
			with self.subTest(phrase=phrase):
				self.assertNotIn(phrase, self.flat)

	def test_phase_boundary_tracks_the_implemented_surface(self):
		"""The doc states the live boundary: the whole pinned six-route
		surface registered and implemented, the transfer record persisting
		with its digest and expiry window, the request/cancel behavior live
		since Phase 4 and the token-authorized accept/decline pair live and
		registered since Phase 5 — with none of the superseded Phase 0/3
		claims left."""
		boundary = self.flat.lower()
		self.assertIn("all six order routes are now registered and implemented", boundary)
		self.assertIn("exactly six order routes are registered", boundary)
		self.assertIn("the `owner_customer` snapshot on `ceto order reference` **exists**", boundary)
		self.assertIn("phase 4 persists it with its token digest and expiry window", boundary)
		self.assertIn("behaviors below are live since phase 4", boundary)
		self.assertIn("hook receives the plaintext token once", boundary)
		self.assertIn("the 7-day expiry is enforced", boundary)
		self.assertIn("**accept** and **decline** are live since phase 5", boundary)
		self.assertIn("both token-authorized routes registered behind them", boundary)
		self.assertIn("the token-authorized accept and decline endpoints since phase 5", boundary)
		self.assertIn("guest-dispatchable like retrieval", boundary)
		self.assertIn("ceto/types/http/store/orders/manifest.py", self.text)
		for stale in (
			"exactly two order routes",
			"exactly four order routes",
			"the four transfer routes remain contract-only",
			"the four transfer routes stay contract-only",
			"still pinned only, not created",
			"no transfer endpoint is registered yet",
			"remain contract-only",
			"stays contract-only",
			"still-unregistered",
			"the registration of both token-authorized routes remains",
		):
			with self.subTest(stale=stale):
				self.assertNotIn(stale, boundary)

	def test_doc_boundary_names_exactly_the_registered_routes(self):
		"""The implemented-route boundary the doc states is the surface
		``ceto/api/store/orders.py`` actually registers — the whole pinned
		six-route surface (source-parsed, no import coupling; the
		registered-surface equality with the manifest lives in
		``ceto.tests.types.http.store.test_orders_manifest``)."""
		registered = {
			(method.upper(), path) for method, path in REGISTERED_ROUTE_RE.findall(ORDERS_API.read_text())
		}
		self.assertEqual(registered, REGISTERED_ROUTES)
		for method, path in sorted(registered):
			with self.subTest(route=f"{method} {path}"):
				self.assertIn(f"`{method} {path}`", self.text)

	def test_readme_status_pins_exactly_the_registered_surface(self):
		"""The README's ✅ rows are exactly the six registered routes and no
		⚪ To-implement row remains — the advertised status cannot drift
		from the registered surface."""
		statuses = readme_order_statuses()
		self.assertEqual(len(statuses), 6)
		implemented = {route for route, status in statuses.items() if "✅" in status}
		pending = {route for route, status in statuses.items() if "⚪" in status}
		self.assertEqual(implemented, REGISTERED_ROUTES)
		self.assertEqual(pending, set())
		self.assertEqual(implemented | pending, set(statuses))

	def test_no_custom_field_commitment(self):
		self.assertIn("No Custom Fields", self.text)


if __name__ == "__main__":
	unittest.main()
