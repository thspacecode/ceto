# Ceto development bootstrap

Explicit, idempotent seeding of a minimal viable ERPNext commerce dataset for
development and test sites. **Every record is non-production sample data.**
There is no production bootstrap in Ceto, and nothing runs automatically:
neither install, migrate, nor test setup invokes this package by itself.

## Usage

```sh
# Full bootstrap
bench --site <site> execute ceto.data.bootstrap_dev.setup_site.execute

# With settings overrides (any BootstrapSettings field in settings.py)
bench --site <site> execute ceto.data.bootstrap_dev.setup_site.execute \
  --kwargs "{'company': 'My Local Dev Co'}"

# Single seeders, useful while testing
bench --site <site> execute ceto.data.bootstrap_dev.seeders.setup_items.execute
```

`bench execute` commits after the entry point succeeds. On an already configured
site, a failing run is rolled back. Frappe's setup wizard commits its own work,
so a failure later in the first run can leave the new Company prerequisites in
place; rerun the bootstrap after correcting the error.

## What is seeded, in fixed order

| Step | Records | Identity (stable business key) |
| --- | --- | --- |
| Setup company | Setup wizard on fresh sites, then the target company | Company resolved from settings or the site default |
| Item groups | `Dev *` category tree | Item Group name |
| UOMs | Unit, Pair, Meter (create-if-missing) | UOM name; shared UOMs are never mutated |
| Warehouses | `Dev Warehouses` > `Dev Sellable Stock`, `Dev Returns` | warehouse name + company |
| Customer | `Ceto Guest` | `customer_name` field, not docname |
| Price list | `Ceto Dev Selling` (selling, company currency) | Price List name |
| Items | `DEV-*` catalog with Item Defaults row | Item `item_code` |
| Item prices | Selling rates active from a fixed development date | price list + item + stock UOM + configured start date, no end date/parties/packing unit |
| Sales taxes | `Ceto Dev Sales Taxes` template at 0% | title + company; only when exactly one leaf Tax account exists |

Values live in `settings.py` (cross-seeder settings) and `dataset.py` (the
fake catalog). Reports group every document under `created`, `updated`, or
`skipped`, plus `notes` for context such as skipped prerequisites.

## Deliberate exclusions

- No opening stock: no bins, stock ledger entries, or stock reconciliations.
  Items are stock-enabled masters with a default warehouse only.
- No accounting transactions: no invoices, payments, or GL entries. The tax
  artifact is a zero-rated template, never a posting.
- No Frappe fixtures: all seeded records stay user-editable.
- No secrets or site config in source; override settings per invocation.
