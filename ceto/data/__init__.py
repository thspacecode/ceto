"""Reusable bootstrap data foundation for Ceto.

Importers in this package seed explicit, mutable initial data on demand. They
locate records by stable business keys, write only the fields they own, and
report every outcome as ``created``, ``updated``, or ``skipped``. Nothing here
runs automatically on install or migrate, and library classes never commit.
"""
