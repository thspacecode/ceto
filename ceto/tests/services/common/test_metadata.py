"""Pins the shared metadata helpers and the moved-helper compatibility imports.

The dump/merge contract is the one documented metadata semantics shared by
every public reference record (cart, line, customer): values merge per key,
a ``null`` value removes a key, an explicit ``metadata: null`` clears all.
"""

from ceto.services.carts.line_items import dump_metadata as line_dump_metadata
from ceto.services.carts.line_items import merged_metadata as line_merged_metadata
from ceto.services.carts.quotation import privileged_scope as quotation_privileged_scope
from ceto.services.common import dump_metadata, merged_metadata, privileged_scope
from ceto.tests.utils import CetoTestSuite


class TestReferenceMetadata(CetoTestSuite):
	def test_dump_serializes_compact_sorted_json_or_none(self) -> None:
		self.assertEqual(dump_metadata({"b": 1, "a": 2}), '{"a":2,"b":1}')
		self.assertIsNone(dump_metadata(None))
		self.assertIsNone(dump_metadata({}))

	def test_merge_applies_updates_and_null_removals(self) -> None:
		current = dump_metadata({"keep": 1, "drop": 2, "change": 3})
		self.assertEqual(
			merged_metadata(current, {"change": 4, "drop": None, "new": 5}),
			'{"change":4,"keep":1,"new":5}',
		)

	def test_merge_starts_from_empty_and_clears_on_a_null_update(self) -> None:
		self.assertEqual(merged_metadata(None, {"a": 1}), '{"a":1}')
		self.assertEqual(merged_metadata("", {"a": 1}), '{"a":1}')
		self.assertIsNone(merged_metadata('{"a":1}', None))

	def test_cart_modules_still_expose_the_moved_helpers(self) -> None:
		# Compatibility imports: the cart modules keep exposing the helpers
		# they use, so downstream imports of the old paths keep resolving.
		self.assertIs(line_dump_metadata, dump_metadata)
		self.assertIs(line_merged_metadata, merged_metadata)
		self.assertIs(quotation_privileged_scope, privileged_scope)
