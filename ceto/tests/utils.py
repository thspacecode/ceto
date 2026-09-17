from ceto.data.test_data.bootstrap_test_master_data import BootStrapTestMasterData
from ceto.tests.testsuite import CetoTestSuite

# Importing the integration-test utilities establishes the committed baseline.
boot_strap_test_master_data = BootStrapTestMasterData()
boot_strap_test_master_data.make()

__all__ = ["CetoTestSuite", "boot_strap_test_master_data"]
