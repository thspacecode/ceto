"""Pinned golden fixtures for the Ceto Store surfaces.

A golden suite builds one fully deterministic assortment — fixed codes,
titles, ids, attribute names and record timestamps — and pins the exact
serialized JSON body each route must answer, so any unintended change to a
served contract (a renamed column, a re-ordered list, a re-derived id, a
re-formatted timestamp) fails loudly beside the fixture that names it.

The expected bodies live beside the builder that feeds them
(``product_responses.py`` pins the product/variant/option reads). The
bodies are literals: the derived public ids are the frozen digests of the
fixture's exact codes, so a change to the id derivation itself is a
deliberate golden update, never a silent drift.
"""
