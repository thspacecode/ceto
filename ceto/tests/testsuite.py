import unittest
import uuid
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import frappe
from frappe.tests.utils import load_test_records_for

if TYPE_CHECKING:
	from frappe.model.document import Document
	from werkzeug.wrappers import Request


class CetoTestSuite(unittest.TestCase):
	"""Frappe-aware base class for Ceto integration tests."""

	@classmethod
	def registerAs(
		cls, _as: Callable[[Callable[..., Any]], Any]
	) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
		def decorator(cm_func: Callable[..., Any]) -> Callable[..., Any]:
			setattr(cls, cm_func.__name__, _as(cm_func))
			return cm_func

		return decorator

	@classmethod
	def setUpClass(cls) -> None:
		cls.globalTestRecords = {}

	def tearDown(self) -> None:
		frappe.db.rollback()
		frappe.local.request_cache.clear()
		if hasattr(frappe.local, "future_sle"):
			frappe.local.future_sle.clear()

	def load_test_records(self, doctype: str) -> None:
		if doctype not in self.globalTestRecords:
			records = load_test_records_for(doctype)
			self.globalTestRecords[doctype] = records[doctype]

	@staticmethod
	def insert_doc(doc_dict: dict[str, Any]) -> "Document":
		doc = frappe.new_doc(doctype=doc_dict.get("doctype"))
		doc.update(doc_dict)
		doc.save()
		return doc

	@contextmanager
	def set_user(self, user: str) -> Iterator[None]:
		old_user = frappe.session.user
		try:
			frappe.set_user(user)
			yield
		finally:
			frappe.set_user(old_user)

	@contextmanager
	def set_flags(self, **flags: Any) -> Iterator[None]:
		previous = {name: frappe.flags.get(name) for name in flags}
		try:
			frappe.flags.update(flags)
			yield
		finally:
			frappe.flags.update(previous)

	@contextmanager
	def set_request(self, request: "Request") -> Iterator[None]:
		previous = getattr(frappe.local, "request", None)
		previous_request_ip = getattr(frappe.local, "request_ip", None)
		try:
			frappe.local.request = request
			frappe.local.request_ip = request.remote_addr
			yield
		finally:
			frappe.local.request = previous
			frappe.local.request_ip = previous_request_ip

	@contextmanager
	def set_conf(self, **values: Any) -> Iterator[None]:
		missing = object()
		previous = {name: frappe.conf.get(name, missing) for name in values}
		try:
			frappe.conf.update(values)
			yield
		finally:
			for name, value in previous.items():
				if value is missing:
					frappe.conf.pop(name, None)
				else:
					frappe.conf[name] = value

	@contextmanager
	def patch_hooks(self, overridden_hooks: dict[str, Any]) -> Iterator[None]:
		get_hooks = frappe.get_hooks

		def get_test_hooks(hook=None, default="_KEEP_DEFAULT_LIST", app_name=None):
			if hook in overridden_hooks:
				return overridden_hooks[hook]
			return get_hooks(hook, default, app_name)

		try:
			frappe.get_hooks = get_test_hooks
			yield
		finally:
			frappe.get_hooks = get_hooks

	@contextmanager
	def set_create_user(self, roles: list[str] | None = None) -> Iterator[str]:
		email = f"ceto.test.{uuid.uuid4().hex[:12]}@example.com"
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "Ceto Test"
		user.send_welcome_email = 0
		user.flags.no_welcome_mail = True
		for role in roles or []:
			user.append("roles", {"role": role})
		user.insert(ignore_permissions=True)

		with self.set_user(email):
			yield email


@CetoTestSuite.registerAs(staticmethod)
@contextmanager
def change_settings(
	doctype: str,
	settings_dict: MutableMapping[str, Any] | None = None,
	/,
	*,
	docname: str | None = None,
	**settings: Any,
) -> Iterator[None]:
	"""Temporarily change fields on a singleton or named document."""
	import copy

	if settings_dict is None:
		settings_dict = settings

	document = frappe.get_doc(doctype, docname) if docname else frappe.get_doc(doctype)
	previous_settings = {key: copy.deepcopy(document.get(key)) for key in settings_dict}
	for key, value in settings_dict.items():
		document.set(key, value)
	document.save(ignore_permissions=True)

	try:
		yield
	finally:
		document = frappe.get_doc(doctype, docname) if docname else frappe.get_doc(doctype)
		for key, value in previous_settings.items():
			document.set(key, value)
		document.save(ignore_permissions=True)
