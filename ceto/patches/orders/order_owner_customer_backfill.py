"""One-time backfill of the ``owner_customer`` snapshot on order references.

References completed before the snapshot column existed carry only
``{order_id, sales_order, cart_id}`` (orders field-mapping Recorded Decision
3): the completed cart's ``Ceto Cart Reference.owner_customer`` — the
Customer the claim resolved at completion time — is copied onto the order
reference once, so effective ownership afterwards never consults the
immutable cart history again. Guest orders stay ownerless.

``update_modified=False`` keeps the reference's ``modified`` — which the
order serializer serves as ``updated_at`` — unchanged, so replaying a
completed cart after the migration returns byte-identical output.
"""

import frappe


def execute():
	orders = frappe.qb.DocType("Ceto Order Reference")
	carts = frappe.qb.DocType("Ceto Cart Reference")
	legacy = (
		frappe.qb.from_(orders)
		.left_join(carts)
		.on(orders.cart_id == carts.name)
		.select(orders.name, carts.owner_customer.as_("cart_owner"))
		.where((orders.owner_customer.isnull()) | (orders.owner_customer == ""))
		.run(as_dict=True)
	)
	for row in legacy:
		if row.cart_owner:
			frappe.db.set_value(
				"Ceto Order Reference", row.name, "owner_customer", row.cart_owner, update_modified=False
			)
