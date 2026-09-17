# Ceto

Ceto is named after the primordial sea goddess in Greek mythology and the mother of Medusa.

In this project, Ceto is an ERPNext commerce API adapter that connects ERPNext to a Medusa-compatible API interface. It follows the [Medusa Store API](https://docs.medusajs.com/api/store) because Medusa provides a standardized, mature interface for commerce applications.

## Specification

- API behavior can be overridden through `hooks.py`.
- Endpoints follow the same API contract as Medusa.js.
- Endpoints continue to use `frappe.whitelist`, so they remain available through Frappe's `/api/method/` route.
- A reverse proxy, such as Nginx, can expose the endpoints with Medusa-compatible paths.
- Input and output schemas use Pydantic.

### Endpoint mapping

For example, a Medusa endpoint maps to its Ceto implementation as follows:

| Service | Endpoint |
| --- | --- |
| Medusa | `/auth/customer/providers` |
| Ceto (Frappe) | `/api/method/ceto.api.auth.customer.providers` |

A reverse proxy can transform the public Medusa-style path into the corresponding Frappe method path.

## Installation

Install this app using the [Bench CLI](https://github.com/frappe/bench):

```bash
cd "$PATH_TO_YOUR_BENCH"
bench get-app "$URL_OF_THIS_REPO" --branch version-16
bench install-app ceto
```

## Contributing

This app uses [pre-commit](https://pre-commit.com/#installation) for code formatting and linting. Install pre-commit and enable it for this repository:

```bash
cd apps/ceto
pre-commit install
```

Pre-commit is configured to use the following tools:

- Ruff
- ESLint
- Prettier
- pyupgrade

## Continuous integration

The following GitHub Actions workflows are configured:

- **CI:** Installs the app and runs unit tests on every push to the `develop` branch.
- **Linters:** Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.

## License

MIT
