"""Exceptions shared by the reusable bootstrap data importers."""


class BootstrapError(Exception):
	"""Base exception for bootstrap data import failures."""


class AmbiguousIdentityError(BootstrapError):
	"""A stable business key unexpectedly resolved to multiple records.

	Raised instead of guessing which record a seeder should modify; the caller
	must resolve the duplicate before rerunning the bootstrap.
	"""
