# Security Policy

## Supported versions

Ceto is developed and released on the `version-16` branch against
Frappe / ERPNext `version-16`. Security fixes land on the latest `version-16`
line only; older tags and branches receive no patches.

## Reporting a vulnerability

Do **not** open a public GitHub issue for a security problem.

Report privately through GitHub's *Private vulnerability reporting* on this
repository, or by email to [p@spacecode.co.th](mailto:p@spacecode.co.th)
(Subject: "ceto security"). Please include:

- a description of the issue and its impact;
- the affected surface (route, service module or DocType);
- reproduction steps or a proof of concept;
- any suggested mitigation.

Reports receive an initial response within 7 days. We will keep the
discussion private, coordinate a fix and credit reporters in the release
notes unless anonymity is requested.

## Scope notes

Ceto's security-sensitive surfaces, for orientation when writing a report:

- the Store HTTP API under `ceto/api/store/` — publishable-key and
  session authorization boundaries;
- ownership transfers in `ceto/services/orders/transfer.py` — single-use,
  digest-only transfer tokens;
- cart credits in `ceto/services/carts/credits.py` — wallet codes are
  persisted as digests only;
- the routing layer in `ceto/routing/` — error masking and response
  envelopes.

Token or credential material must never appear in logs, hooks payloads or
API responses; a report showing otherwise is in scope here.
