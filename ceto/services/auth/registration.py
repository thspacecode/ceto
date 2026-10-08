"""The credential half of a customer registration: the login identity.

A registration call mints the ``User`` that owns the registered credentials and
returns a single-purpose registration token. The customer profile is a separate,
later transaction that consumes that token; nothing in this module touches the
profile.
"""

import frappe
from frappe.utils.password import update_password


def create_registration_identity(email: str, password: str) -> str:
	"""Create the enabled Website User that backs a new customer registration.

	The plaintext password only lives in this call frame: Frappe's supported
	``update_password`` API stores a salted hash in the ``__Auth`` table, and
	neither the registration token nor the cache layer ever receives it. The
	identity and its password share the caller's transaction, so a failure
	anywhere leaves no half-registered identity behind.
	"""
	user = frappe.new_doc("User")
	user.email = email
	user.first_name = _display_fallback(email)
	user.enabled = 1
	user.user_type = "Website User"
	user.send_welcome_email = 0
	user.flags.no_welcome_mail = True
	# Registration runs as a guest: the public register route is the boundary.
	user.flags.ignore_permissions = True
	user.insert()
	update_password(user.name, password)
	return user.name


def _display_fallback(email: str) -> str:
	"""Derive the mandatory display name from the email until a profile provides one."""
	return email.partition("@")[0]
