import frappe


def create_customer_session() -> dict[str, object]:
	"""Create a Frappe cookie session for the authenticated website customer."""
	user = frappe.session.user
	user_details = frappe.db.get_value(
		"User",
		user,
		["name", "email", "first_name", "last_name", "enabled", "user_type"],
		as_dict=True,
	)
	if not user_details or not user_details.enabled or user_details.user_type != "Website User":
		raise frappe.AuthenticationError

	frappe.local.login_manager.login_as(user)
	return {
		"id": user_details.name,
		"email": user_details.email or user_details.name,
		"first_name": user_details.first_name or "",
		"last_name": user_details.last_name or "",
	}


def delete_customer_session() -> None:
	"""Delete the current Frappe session and expire its authentication cookies."""
	frappe.local.login_manager.logout()
