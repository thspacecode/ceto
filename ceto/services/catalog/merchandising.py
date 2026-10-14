"""Catalog storage maintenance for the Ceto-owned product merchandising.

The ``Ceto Product Merchandising`` records are the single Ceto-owned link
between an ERPNext ``Item`` and the Ceto-stored collection / curated
product type masters (products field-mapping Recorded Decision 4). This
module owns the lifecycle the masters trigger: deleting a collection or a
product type must leave no dangling reference behind, while a record that
still carries its other link survives detached.
"""

import frappe


def detach_deleted_master(fieldname: str, master: str) -> None:
	"""Detach one deleted catalog master from every merchandising row naming it.

	Runs from the master's ``on_trash``, before Frappe's delete-time link
	check, so the deletion stays possible: each naming record keeps its
	other link (cleared of the dead one), and a record left without any
	link is deleted outright instead of lingering empty.
	"""
	for name in frappe.get_all("Ceto Product Merchandising", filters={fieldname: master}, pluck="name"):
		row = frappe.get_doc("Ceto Product Merchandising", name)
		row.set(fieldname, None)
		if row.collection or row.product_type:
			row.save(ignore_permissions=True)
		else:
			frappe.delete_doc("Ceto Product Merchandising", name, ignore_permissions=True, force=True)
