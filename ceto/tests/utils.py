import frappe

from ceto.tests.data.bootstrap_test_master_data import BootStrapTestMasterData
from ceto.tests.testsuite import CetoTestSuite

# Importing the integration-test utilities establishes the committed baseline,
# following erpnext.tests.utils: the commerce masters come from
# ceto.data.bootstrap_dev (the only bootstrap layer Ceto ships) and the
# test-only auth records are layered on top. Other tests import the suite from
# here, so importing ceto.tests.utils is all a test module needs.
boot_strap_test_master_data = BootStrapTestMasterData()
boot_strap_test_master_data.make()

# Publication is site configuration and the bootstrap never writes it, so the
# harness overlays the documented demo roots onto the process configuration:
# the bootstrap items are published exactly like the demo deployment in the
# bootstrap README, and cart resolution reads the same boundary every suite
# tests against. Suites pinning the unconfigured behaviour scope their own
# ``ceto_catalog`` through ``set_conf``.
frappe.conf.update({"ceto_catalog": {"category_roots": ["Dev Apparel"]}})

__all__ = ["CetoTestSuite", "boot_strap_test_master_data"]
