# Ceto

Ceto is named after the primordial sea goddess in Greek mythology and the mother of Medusa.

Ceto is an ERPNext commerce API adapter that connects ERPNext to a Medusa-compatible API interface. It follows the [Medusa Store API](https://docs.medusajs.com/api/store) to provide a standardized commerce contract for storefront applications.

## Specification

- Endpoints follow the Medusa Store API contract under the `/store` namespace.
- Ceto's FastAPI-style router owns route matching, parameters, authorization policy, dispatch, and JSON errors.
- Endpoint functions are not whitelisted and cannot be called through Frappe's `/api/method/` route.
- API behavior can be replaced by downstream apps with the route-based `ceto_route_overrides` hook.
- A reverse proxy, such as Nginx, only forwards `/store/`; it does not translate paths or parameters.
- Request and response schemas use Pydantic.

For example:

| Interface | Endpoint |
| --- | --- |
| Medusa-compatible | `GET /store/auth/customer/providers` |
| Medusa-compatible | `POST /store/auth/customer/emailpass` |

Ceto dispatches these routes directly and returns their JSON objects without Frappe's `message` envelope. Nginx can forward the namespace without knowing its Python implementation:

```nginx
location /store/ {
    proxy_pass http://frappe_backend;
}
```

## Project structure

Ceto separates the HTTP adapter from application and integration logic:

```text
ceto/
├── api/
│   └── <area>/
│       ├── <resource>.py   # Ceto-owned HTTP endpoints
│       └── schemas.py      # Pydantic API contracts
├── services/
│   └── <area>/
│       ├── <resource>.py   # application and business operations
│       └── <concern>.py    # focused integration concerns, such as tokens
├── routing/
│   ├── router.py           # FastAPI-style route registration
│   └── medusa.py           # Frappe request/response adapter
├── tests/
├── hooks.py
└── modules.txt
```

The customer authentication implementation is organized as follows:

```text
ceto/
├── api/
│   └── auth/
│       ├── customer.py
│       └── schemas.py
└── services/
    └── auth/
        ├── customer.py
        └── tokens.py
```

### Conventions

#### API layer: `ceto/api`

The API layer defines the external Medusa-compatible transport contract. Files in this layer should:

- expose methods with `@store_router.get`, `@store_router.post`, or another explicit router method;
- declare guest access explicitly;
- use FastAPI-style `{parameter}` placeholders for dynamic path segments;
- parse and validate request data with Pydantic;
- serialize responses according to the Medusa API schema;
- delegate application behavior to the service layer;
- remain small enough that endpoint behavior is easy to inspect.

Do not place reusable business logic, authentication implementations, token handling, or database workflows in API modules.

A routed endpoint looks like this:

```python
from ceto.routing import store_router


@store_router.get("/auth/customer/providers", allow_guest=True)
def providers(): ...


@store_router.post("/auth/customer/{auth_provider}", allow_guest=True)
def authenticate(auth_provider: str, **credentials): ...
```

`store_router` adds the `/store` prefix and dispatches the function directly through Ceto's Frappe page renderer. It does not apply `frappe.whitelist`; do not stack `@frappe.whitelist` on a routed endpoint.

Downstream apps can replace an endpoint by its external contract rather than its Python path:

```python
ceto_route_overrides = {"POST /store/auth/customer/{auth_provider}": "my_app.api.authenticate_customer"}
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

#### Schemas

Pydantic models describing the public request or response contract belong beside the endpoints in `api/<area>/schemas.py`. Internal domain types that are not part of the HTTP contract should live in the relevant service package.

#### Tests

Tests belong in `ceto/tests`. Endpoint tests should verify validation, serialization, and delegation. Service tests should verify application behavior independently from the endpoint adapter.

## Authentication configuration

Ceto customer tokens use HS256 and expire after 24 hours by default. The signing secret defaults to the site's Frappe encryption key. It can be overridden in `site_config.json`:

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
