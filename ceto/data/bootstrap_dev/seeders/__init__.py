"""Idempotent seeders for the Ceto development bootstrap.

Each seeder owns one domain, resolves records by a stable business key, and
reports every document as ``created``, ``updated``, or ``skipped``.
"""
