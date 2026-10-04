"""Shared fields selector: the entity-neutral ``fields`` contract.

Every store route narrows its response with the same selector
(``ceto.services.serialization.select_fields``) — carts and orders alike,
including both members of the completion union. This module pins that
contract without touching a serializer or the database: plain selection,
additive/subtractive tokens, dotted truncation, whitespace tolerance and
the fail-closed unknown-field errors.
"""

from ceto.routing.exceptions import InvalidDataError
from ceto.services.serialization import select_fields
from ceto.tests.utils import CetoTestSuite

ORDER = {"id": "order_1", "email": "guest@example.com", "total": 10}


class TestSelectFields(CetoTestSuite):
	def test_empty_fields_return_the_payload_unchanged(self) -> None:
		self.assertIs(select_fields(ORDER, None, entity="order"), ORDER)
		self.assertIs(select_fields(ORDER, "", entity="order"), ORDER)

	def test_plain_tokens_select_exactly_the_named_fields(self) -> None:
		selected = select_fields(ORDER, "total, id", entity="order")

		self.assertEqual(selected, {"id": "order_1", "total": 10})
		# The payload's own field order is preserved.
		self.assertEqual(list(selected), ["id", "total"])

	def test_subtractive_tokens_remove_from_the_full_selection(self) -> None:
		self.assertEqual(select_fields(ORDER, "-email", entity="order"), {"id": "order_1", "total": 10})
		self.assertEqual(select_fields(ORDER, "id,-id", entity="order"), {})

	def test_additive_tokens_keep_the_full_selection(self) -> None:
		self.assertEqual(select_fields(ORDER, "+total", entity="order"), ORDER)

	def test_additive_tokens_extend_a_plain_selection(self) -> None:
		self.assertEqual(
			select_fields(ORDER, "id,+total,-email", entity="order"), {"id": "order_1", "total": 10}
		)

	def test_dotted_tokens_take_the_top_level_field(self) -> None:
		items = [{"quantity": 2}]

		self.assertEqual(
			select_fields({"id": "order_1", "items": items}, "items.quantity", entity="order"),
			{"items": items},
		)

	def test_unknown_fields_fail_closed(self) -> None:
		with self.assertRaises(InvalidDataError) as raised:
			select_fields(ORDER, "id,nonsense", entity="order")
		self.assertEqual(str(raised.exception), "Unknown order field: nonsense")

		# Unknown fields are refused on signed tokens too — never ignored.
		with self.assertRaises(InvalidDataError):
			select_fields(ORDER, "-nonsense", entity="order")
		with self.assertRaises(InvalidDataError):
			select_fields(ORDER, "+nonsense", entity="order")

	def test_blank_tokens_are_ignored(self) -> None:
		self.assertEqual(select_fields(ORDER, " , id , ", entity="order"), {"id": "order_1"})

	def test_empty_field_names_are_rejected(self) -> None:
		with self.assertRaises(InvalidDataError) as raised:
			select_fields(ORDER, "*", entity="cart")

		self.assertEqual(str(raised.exception), "Cart fields must not be empty")
