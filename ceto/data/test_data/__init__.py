from .bootstrap_test_master_data import BootStrapTestMasterData


def bootstrap_test_master_data() -> dict[str, list[str]]:
	return BootStrapTestMasterData().make()


__all__ = ["BootStrapTestMasterData", "bootstrap_test_master_data"]
