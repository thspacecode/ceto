"""The shared ``ceto_catalog`` parser: one config shape, one reader.

``ceto.config.catalog`` is the only place that parses the storefront catalog
site configuration. The category directory must never grow its own config
reading, so these tests pin the parser semantics: the raw mapping reader and
the ``category_roots`` normalization that keeps the configured order, drops
junk and collapses duplicates — with an absent or unusable value meaning
"publish nothing", never an error.
"""

from ceto.config.catalog import CATALOG_CONFIG_KEY, catalog_settings, category_roots
from ceto.tests.utils import CetoTestSuite


class TestCatalogConfigParser(CetoTestSuite):
	def test_reads_the_private_site_configuration(self):
		settings = {"category_roots": ["Dev Apparel"]}
		with self.set_conf(ceto_catalog=settings):
			self.assertEqual(catalog_settings(), settings)

	def test_absent_or_non_mapping_configuration_reads_as_empty(self):
		self.assertEqual(catalog_settings(), {})
		with self.set_conf(ceto_catalog="not-a-mapping"):
			self.assertEqual(catalog_settings(), {})

	def test_the_config_key_is_stable(self):
		self.assertEqual(CATALOG_CONFIG_KEY, "ceto_catalog")

	def test_a_single_root_string_is_accepted(self):
		self.assertEqual(category_roots({"category_roots": "Dev Apparel"}), ("Dev Apparel",))

	def test_roots_keep_the_configured_order_and_collapse_duplicates(self):
		settings = {"category_roots": ["Dev Clearance", "Dev Apparel", "Dev Clearance"]}
		self.assertEqual(category_roots(settings), ("Dev Clearance", "Dev Apparel"))

	def test_blank_and_non_string_entries_are_dropped(self):
		settings = {"category_roots": ["Dev Apparel", "   ", "", 42, None, ["Dev Footwear"]]}
		self.assertEqual(category_roots(settings), ("Dev Apparel",))

	def test_padded_names_are_trimmed(self):
		self.assertEqual(category_roots({"category_roots": ["  Dev Apparel  "]}), ("Dev Apparel",))

	def test_an_absent_or_unusable_value_publishes_nothing(self):
		self.assertEqual(category_roots({}), ())
		self.assertEqual(category_roots({"category_roots": None}), ())
		self.assertEqual(category_roots({"category_roots": {"Dev Apparel": True}}), ())
