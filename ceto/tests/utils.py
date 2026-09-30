from ceto.tests.data.bootstrap_test_master_data import BootStrapTestMasterData
from ceto.tests.testsuite import CetoTestSuite

# Importing the integration-test utilities establishes the committed baseline,
# following erpnext.tests.utils: the commerce masters come from
# ceto.data.bootstrap_dev (the only bootstrap layer Ceto ships) and the
# test-only auth records are layered on top. Other tests import the suite from
# here, so importing ceto.tests.utils is all a test module needs.
boot_strap_test_master_data = BootStrapTestMasterData()
boot_strap_test_master_data.make()

__all__ = ["CetoTestSuite", "boot_strap_test_master_data"]
