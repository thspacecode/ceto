# Ceto

Ceto is named after the primordial sea goddess in Greek mythology and the mother of Medusa.

Ceto is an ERPNext commerce API adapter that connects ERPNext to a Medusa-compatible API interface. It follows the [Medusa Store API](https://docs.medusajs.com/api/store) to provide a standardized commerce contract for storefront applications.

## Specification

- Endpoints follow the Medusa Store API contract.
- Endpoints use `frappe.whitelist`, so they remain available through Frappe's `/api/method/` route.
- API behavior can be replaced by downstream apps with Frappe's `override_whitelisted_methods` hook.
- A reverse proxy, such as Nginx, can expose endpoints with Medusa-compatible paths.
- Request and response schemas use Pydantic.

For example:

| Service | Endpoint |
| --- | --- |
| Medusa | `GET /auth/customer/providers` |
| Ceto | `GET /api/method/ceto.api.auth.customer.providers` |
| Medusa | `POST /auth/customer/{auth_provider}` |
| Ceto | `POST /api/method/ceto.api.auth.customer.authenticate` |

The reverse proxy is responsible for transforming a public Medusa path into its Ceto method path and passing path parameters such as `auth_provider` to the method.

## Project structure

Ceto separates the HTTP adapter from application and integration logic:

```text
ceto/
├── api/
│   └── <area>/
│       ├── <resource>.py   # whitelisted endpoints
│       └── schemas.py      # Pydantic API contracts
├── services/
│   └── <area>/
│       ├── <resource>.py   # application and business operations
│       └── <concern>.py    # focused integration concerns, such as tokens
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

- expose methods with `@frappe.whitelist`;
- declare the allowed HTTP method and guest access explicitly;
- parse and validate request data with Pydantic;
- serialize responses according to the Medusa API schema;
- delegate application behavior to the service layer;
- remain small enough that endpoint behavior is easy to inspect.

Do not place reusable business logic, authentication implementations, token handling, or database workflows in API modules.

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
