# Ceto

Ceto is named after the primordial sea goddess in Greek mythology and the mother of Medusa.

Ceto is an ERPNext commerce API adapter that connects ERPNext to a Medusa-compatible API interface. It follows the [Medusa Store API](https://docs.medusajs.com/api/store) to provide a standardized commerce contract for storefront applications.

## Specification

- Ceto exposes Medusa's sibling `/auth` and `/store` namespaces below the `/ceto` application prefix.
- Ceto's FastAPI-style router owns route matching, parameters, authorization policy, dispatch, and JSON errors.
- Endpoint functions are not whitelisted and cannot be called through Frappe's `/api/method/` route.
- API behavior can be replaced by downstream apps with the route-based `ceto_route_overrides` hook.
- A reverse proxy, such as Nginx, only forwards `/ceto/`; it does not translate paths or parameters.
- Request and response schemas use Pydantic.

For example:

| Interface | Endpoint |
| --- | --- |
| Medusa authentication | `GET /ceto/auth/customer/providers` |
| Medusa authentication | `POST /ceto/auth/customer/emailpass` |
| Medusa Store API | `GET /ceto/store/products` |

Ceto dispatches these routes directly and returns their JSON objects without Frappe's `message` envelope.

The official `@medusajs/js-sdk` preserves the pathname in its `baseUrl`, so configure it with the Ceto root and let the SDK append `/auth` or `/store`:

```ts
const sdk = new Medusa({
  baseUrl: "https://api.example.com/ceto",
})
```

## API implementation status

Medusa API implementation status, grouped by scope. Routes follow the [Medusa Store API reference](https://docs.medusajs.com/api/store/auth) and are exposed below Ceto's `/ceto` prefix.

**Status:** ✅️ Implemented · ⚪️ To implement

### Auth

| Method | Route | Status |
| --- | --- | --- |
| GET | `/auth/customer/providers` | ✅️ |
| POST | `/auth/customer/{auth_provider}` | ✅️ |
| POST | `/auth/verification/confirm` | ✅️ |
| POST | `/auth/customer/{auth_provider}/reset-password` | ✅️ |
| POST | `/auth/token/refresh` | ✅️ |
| POST | `/auth/verification/request` | ✅️ |
| POST | `/auth/customer/{auth_provider}/update` | ✅️ |
| POST | `/auth/customer/{auth_provider}/register` | ✅️ |
| POST | `/auth/session` | ✅️ |
| POST | `/auth/customer/{auth_provider}/callback` | ✅️ |
| POST | `/auth/customer/emailpass/verification/confirm` | ✅️ |
| DELETE | `/auth/session` | ✅️ |

### Carts

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/carts/{id}` | ✅️ |
| POST | `/store/carts/{id}/gift-cards` | ✅️ |
| POST | `/store/carts/{id}/line-items` | ✅️ |
| POST | `/store/carts/{id}/promotions` | ✅️ |
| POST | `/store/carts/{id}/shipping-methods` | ✅️ |
| POST | `/store/carts/{id}/store-credits` | ✅️ |
| POST | `/store/carts/{id}/taxes` | ✅️ |
| POST | `/store/carts/{id}/customer` | ✅️ |
| POST | `/store/carts/{id}/complete` | ✅️ |
| POST | `/store/carts` | ✅️ |
| POST | `/store/carts/{id}` | ✅️ |
| POST | `/store/carts/{id}/line-items/{line_id}` | ✅️ |
| DELETE | `/store/carts/{id}/gift-cards` | ✅️ |
| DELETE | `/store/carts/{id}/line-items/{line_id}` | ✅️ |
| DELETE | `/store/carts/{id}/promotions` | ✅️ |

### Collections

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/collections/{id}` | ⚪️ |
| GET | `/store/collections` | ⚪️ |

### Currencies

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/currencies/{code}` | ✅️ |
| GET | `/store/currencies` | ✅️ |

### Customers

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/customers/me/addresses/{address_id}` | ✅️ |
| GET | `/store/customers/me` | ✅️ |
| GET | `/store/customers/me/addresses` | ✅️ |
| POST | `/store/customers/me/addresses` | ✅️ |
| POST | `/store/customers` | ✅️ |
| POST | `/store/customers/me` | ✅️ |
| POST | `/store/customers/me/addresses/{address_id}` | ✅️ |
| DELETE | `/store/customers/me/addresses/{address_id}` | ✅️ |

### Gift Cards

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/gift-cards/{idOrCode}` | ⚪️ |

### Locales

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/locales` | ✅️ |

### Orders

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/orders/{id}` | ✅️ |
| GET | `/store/orders` | ✅️ |
| POST | `/store/orders/{id}/transfer/accept` | ✅️ |
| POST | `/store/orders/{id}/transfer/cancel` | ✅️ |
| POST | `/store/orders/{id}/transfer/decline` | ✅️ |
| POST | `/store/orders/{id}/transfer/request` | ✅️ |

### Payment Collections

| Method | Route | Status |
| --- | --- | --- |
| POST | `/store/payment-collections` | ⚪️ |
| POST | `/store/payment-collections/{id}/payment-sessions` | ⚪️ |

### Payment Providers

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/payment-providers` | ⚪️ |

### Product Categories

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/product-categories/{id}` | ⚪️ |
| GET | `/store/product-categories` | ⚪️ |

### Product Options

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/product-options/{id}` | ⚪️ |
| GET | `/store/product-options` | ⚪️ |

### Product Tags

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/product-tags/{id}` | ⚪️ |
| GET | `/store/product-tags` | ⚪️ |

### Product Types

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/product-types/{id}` | ⚪️ |
| GET | `/store/product-types` | ⚪️ |

### Product Variants

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/product-variants` | ⚪️ |

### Products

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/products/{id}` | ⚪️ |
| GET | `/store/products` | ⚪️ |

### Regions

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/regions/{id}` | ✅️ |
| GET | `/store/regions` | ✅️ |

### Return Reasons

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/return-reasons/{id}` | ⚪️ |
| GET | `/store/return-reasons` | ⚪️ |

### Returns

| Method | Route | Status |
| --- | --- | --- |
| POST | `/store/returns` | ⚪️ |

### Shipping Options

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/shipping-options` | ⚪️ |
| POST | `/store/shipping-options/{id}/calculate` | ⚪️ |

### Store Credit Accounts

| Method | Route | Status |
| --- | --- | --- |
| GET | `/store/store-credit-accounts/{id}` | ⚪️ |
| GET | `/store/store-credit-accounts` | ⚪️ |
| POST | `/store/store-credit-accounts/claim` | ⚪️ |

## Project structure

Ceto separates public HTTP contracts, route adapters, application behavior, and Frappe integration. Domains follow this scalable structure, which mirrors Medusa's domain-oriented HTTP types layout:

```text
ceto/
├── api/
│   ├── routes.py                     # explicit imports that register all endpoint modules
│   └── <area>/
│       ├── <capability>.py            # thin Ceto-owned HTTP endpoints
│       └── validators.py              # route-specific runtime validation, when needed
├── types/
│   ├── <area>/                        # transport-neutral internal DTOs, when needed
│   └── http/
│       └── <area>/
│           ├── common.py              # fields shared by Store and Admin contracts
│           ├── entities.py            # reusable public objects embedded in responses
│           ├── payloads.py            # public request body contracts
│           ├── queries.py             # public query parameter contracts
│           ├── responses.py           # complete public response body contracts
│           └── __init__.py             # stable public exports for the area
├── services/
│   └── <area>/
│       ├── <capability>.py            # application and business operations
│       └── <concern>.py               # focused integration concerns, such as tokens
├── routing/
│   ├── router.py                      # route registration, matching, and dispatch
│   ├── response.py                    # typed JSON and JSONModel response primitives
│   └── medusa.py                      # Frappe page-renderer integration and error adapter
├── tests/                              # endpoint, routing, contract, and service tests
├── hooks.py                            # Frappe hooks and route override examples
└── modules.txt                         # Frappe Module Def registration only
```

Directories and files should be added when the corresponding behavior exists; empty architectural placeholders are unnecessary.

### Conventions

#### API layer: `ceto/api`

The API layer defines the external Medusa-compatible transport contract. Files in this layer should:

- expose methods with `@ceto_router.get`, `@ceto_router.post`, or another explicit router method;
- declare guest access explicitly;
- use FastAPI-style `{parameter}` placeholders for dynamic path segments;
- parse and validate request data with Pydantic;
- serialize responses according to the Medusa API schema;
- delegate application behavior to the service layer;
- remain small enough that endpoint behavior is easy to inspect.

Do not place reusable business logic, authentication implementations, token handling, or database workflows in API modules. Authentication routes resolve providers through the service registry; they must not branch on provider identifiers. Each provider belongs in its own module under `services/auth/providers` and implements the shared provider contract.

A routed endpoint looks like this:

```python
from ceto.routing import ceto_router
from ceto.types.http.auth import AuthProvidersListResponse


@ceto_router.get("/auth/customer/providers", allow_guest=True)
def list_customer_auth_providers() -> AuthProvidersListResponse:
	return AuthProvidersListResponse(providers=[])


@ceto_router.post("/auth/customer/{auth_provider}", allow_guest=True)
def authenticate(auth_provider: str, **credentials): ...
```

`ceto_router` adds the `/ceto` application prefix and dispatches the function directly through Ceto's Frappe page renderer. Endpoint paths include their Medusa namespace (`/auth`, `/store`, and potentially `/admin`). The router does not apply `frappe.whitelist`; do not stack `@frappe.whitelist` on a routed endpoint. It automatically serializes response schemas inheriting `JSONModel`; endpoints only need the explicit `JSON` wrapper when they must set a non-default status code or response headers.

Downstream apps can replace an endpoint by its complete external contract rather than its Python path:

```python
ceto_route_overrides = {"POST /ceto/auth/customer/{auth_provider}": "my_app.api.authenticate_customer"}
```

#### Service layer: `ceto/services`

The service layer contains reusable application behavior. Files in this layer should:

- implement authentication, commerce, and ERPNext integration workflows;
- be callable independently of the HTTP transport;
- use focused names such as `customer.py`, `tokens.py`, or `providers.py`;
- avoid generic modules such as `helper.py` or `utils.py` when a domain-specific name is available;
- avoid importing API modules or API schemas.

The dependency direction is one-way: `api` may import `services`, but `services` must not import `api`.

#### Frappe modules

Do not use a top-level `modules/` directory for service code. “Module” has a specific meaning in Frappe through `modules.txt`, Module Def records, and DocType organization. Non-DocType application logic belongs in `services/`.

#### Types and schemas

Public HTTP contracts are reusable types and should not remain owned by one endpoint module once they are shared. Place shared contracts under `ceto/types/http/<area>/` and separate them by purpose:

- `common.py` contains fields or base models shared across API namespaces;
- `entities.py` contains reusable objects embedded in one or more responses;
- `payloads.py` contains public request body contracts;
- `queries.py` contains public query parameter contracts;
- `responses.py` contains complete response bodies and is the appropriate place for `JSONModel` subclasses;
- `__init__.py` re-exports the area's supported public contracts so callers do not depend on internal file placement.

For example, `AuthProvider` is an entity while `AuthProvidersListResponse` is a response:

```python
# ceto/types/http/auth/entities.py
from typing import Literal

from pydantic import BaseModel


class AuthProvider(BaseModel):
	id: str
	identifier: str
	display_name: str
	flow: Literal["credentials", "redirect"]
```

```python
# ceto/types/http/auth/responses.py
from ceto.routing import JSONModel
from ceto.types.http.auth.entities import AuthProvider


class AuthProvidersListResponse(JSONModel):
	providers: list[AuthProvider]
```

Only a complete response body should inherit `JSONModel`. Embedded entities and request payloads should normally inherit Pydantic's `BaseModel`.

Route-specific runtime validators may remain in `ceto/api/<area>/validators.py` when they implement adapter behavior rather than a reusable public contract. Transport-neutral internal objects exchanged between services are DTOs and belong under `ceto/types/<area>/`; they must not inherit HTTP response behavior.

Do not create one global `schemas.py`. Domain-oriented packages keep contracts discoverable and prevent unrelated Store, Admin, and internal models from becoming coupled.

#### Dependency direction

Dependencies flow inward from transport adapters to application behavior:

```text
api ───────► types/http
 │
 └─────────► services ─────► internal DTOs and Frappe/ERPNext

routing ───► endpoint return values
```

- `api` may import public HTTP types and services;
- `services` must not import `api`, `ceto_router`, `JSON`, or HTTP response models;
- public HTTP types must not query Frappe or contain business workflows;
- routing primitives must remain independent of commerce domains such as auth, customer, cart, or order.

#### Tests

Tests belong in `ceto/tests`. Endpoint tests should verify validation, serialization, and delegation. Service tests should verify application behavior independently from the endpoint adapter.

## Authentication configuration

Ceto customer tokens use HS256 and expire after 24 hours by default. Unless configured explicitly, the signing key is derived from the site's Frappe encryption key with HKDF-SHA256 and a Ceto-specific context. It can be overridden in `site_config.json`:

```json
{
  "ceto_jwt_secret": "replace-with-a-secure-random-secret",
  "ceto_jwt_expiry_seconds": 86400
}
```

The authentication hook accepts Ceto tokens supplied as:

```http
Authorization: Bearer <token>
```

Ceto follows Medusa's auth response contracts at `/ceto/auth/...`. Configure the official `@medusajs/js-sdk` with a `baseUrl` ending in `/ceto`; the SDK then resolves its `/auth/...` and `/store/...` requests below that prefix. Cookie-authenticated browser requests to unsafe `/ceto/*` methods must include Frappe's `X-Frappe-CSRF-Token` header; bearer-token and guest clients do not use a session CSRF token.

Authenticated customers can refresh a bearer token with `POST /ceto/auth/token/refresh`, exchange a bearer token for a Frappe cookie session with `POST /ceto/auth/session`, and delete that cookie session with `DELETE /ceto/auth/session`.

### Registration, password reset, and credential updates

`POST /ceto/auth/customer/{auth_provider}/register` validates registration credentials and creates the login Website User, but never the ERP Customer profile; it returns a single-purpose `registration` token that `POST /ceto/store/customers` exchanges to complete the registration by creating that customer profile. `POST /ceto/auth/customer/{auth_provider}/reset-password` returns `200` with an empty body whether or not the identifier is registered, so it cannot be used to enumerate customers. For a registered website customer Ceto issues a single-purpose `password_reset` token and calls every handler in the `ceto_auth_password_reset` hook:

```python
ceto_auth_password_reset = ["my_app.auth.deliver_password_reset_token"]
```

The handler receives `identifier`, `token`, and `metadata` keyword arguments. The customer then submits new credentials with the reset token to `POST /ceto/auth/customer/{auth_provider}/update`:

```http
Authorization: Bearer <password_reset token>
```

Ceto bearer tokens are purpose-bound: `registration` and `password_reset` tokens are valid signatures but never authenticate requests; only `auth`-purpose tokens do. Token lifetimes default to 24 hours for `auth`, 1 hour for `password_reset`, and 1 hour for `registration`, and can be overridden in `site_config.json`:

```json
{
  "ceto_password_reset_token_expiry_seconds": 3600,
  "ceto_registration_token_expiry_seconds": 3600
}
```

`POST /ceto/auth/customer/emailpass/verification/confirm` verifies a customer's email with the token delivered out of band (the Medusa `token` shape for the emailpass provider).

### Customer verification

`POST /ceto/auth/verification/request` creates a cryptographically random, single-use token. Ceto stores only the token's SHA-256 lookup key, expires requests after 15 minutes by default, and calls every handler in the `ceto_auth_verification_requested` hook. A delivery app can send the code by email, SMS, or another channel:

```python
ceto_auth_verification_requested = ["my_app.auth.deliver_verification_code"]
```

The handler receives `entity_id`, `entity_type`, `code_provider`, `code`, `expires_at`, and `metadata` keyword arguments. `POST /ceto/auth/verification/confirm` consumes the code once and calls the optional `ceto_auth_verification_confirmed` hook. A confirmed identity remains available to downstream registration logic through `ceto.services.auth.verification.is_verified` for one hour by default.

Only the Medusa-compatible `token` code provider is built in. The expiration windows can be overridden in `site_config.json`:

```json
{
  "ceto_auth_verification_expiry_seconds": 900,
  "ceto_auth_verified_expiry_seconds": 3600
}
```

### Google OAuth

Ceto exposes Google as a redirect provider when an enabled `google` **Social Login Key** with a client ID and secret is configured in Frappe. Add every storefront callback URL to the Google OAuth client's authorized redirect URIs.

Start the authorization-code flow with the storefront callback URL:

```http
POST /ceto/auth/customer/google
Content-Type: application/json

{"callback_url":"https://shop.example.com/auth/google"}
```

Redirect the browser to the returned `location`. After Google redirects to the callback URL, submit its `code` and `state` to Ceto:

```http
POST /ceto/auth/customer/google/callback
Content-Type: application/json

{"code":"...","state":"..."}
```

The callback returns the same `{"token":"..."}` Ceto JWT shape as email/password authentication. OAuth state is single-use and expires after ten minutes. Existing System Users cannot authenticate through the customer endpoint; new users follow Frappe's Social Login signup policy and are created as Website Users.

## Installation

Install this app using the [Bench CLI](https://github.com/frappe/bench):

```bash
cd "$PATH_TO_YOUR_BENCH"
bench get-app "$URL_OF_THIS_REPO" --branch version-16
bench install-app ceto
```

## Contributing

Install and enable pre-commit before contributing:

```bash
cd apps/ceto
pre-commit install
```

Pre-commit runs Ruff, ESLint, Prettier, pyupgrade, and repository hygiene checks.

## Continuous integration

The repository includes workflows for application tests, Frappe Semgrep rules, and dependency auditing.

## License

MIT
