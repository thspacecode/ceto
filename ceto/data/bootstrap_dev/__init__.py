"""Explicit development/test bootstrap for a minimal viable ERPNext commerce dataset.

This layer seeds mutable master data that must stay editable by users, so it
deliberately uses no Frappe fixtures and runs only when invoked:

	bench --site <site> execute ceto.data.bootstrap_dev.setup_site.execute

Every value is development sample data; there is no production bootstrap.
"""
