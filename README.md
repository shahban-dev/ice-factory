# Ice Factory Management System

Internal management system for an ice factory in Pakistan. Currency is PKR,
timezone is Asia/Karachi, dates are shown as DD-MM-YYYY.

Two admin users share full access in Version 1. There is no customer login,
no online ordering and no payment gateway. Everything is entered manually:
customers and what they owe, bulk ice sales and payments, expenses, monthly
salaries, and monthly expense and profit reports.

## Development setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit SECRET_KEY at least
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in with the superuser account.

Local development uses SQLite when `DATABASE_URL` is unset. Production uses
PostgreSQL 16 (see DEPLOYMENT.md).

## Running the tests

```bash
python manage.py test
```

85 tests cover money rounding, sale totals and discounts, invoice numbering
(including year rollover, deleted numbers never reused, and simultaneous
saves), the payment allocation rules, walk-in sales, payroll proration and
paying, report math against hand-calculated values, permissions on every
page and export, the login lockout, and query-count guards against N+1
queries on the dashboard, customer list and ledger.

## Demo data

```bash
python manage.py seed_demo
```

Seeds sample customers, products and employees plus one month of sales,
payments, expenses and payroll, and writes `seed_demo_expected_totals.txt`
with hand-calculated expected report totals so the demo can be checked
against the reports. Refuses to run with DEBUG off unless you pass
`--force` and type `SEED DEMO` at the prompt. Refuses if demo data already
exists.

## Backups

```bash
python manage.py backup_db
```

Dumps the database, compresses it, encrypts it when
`BACKUP_ENCRYPTION_PASSPHRASE` is set, uploads it off-server when
`BACKUP_RCLONE_REMOTE` is set, rotates old backups (newest per day for
30 days, newest per month for 12 months), and logs the result. See
DEPLOYMENT.md for the cron line and the restore procedure.

## Documentation

- `DEPLOYMENT.md` — the full VPS setup, go-live checklist, update and
  rollback procedures, and backup restore steps.
- `USER_GUIDE.md` — plain-English daily use: sales, payments, customers,
  expenses, payroll, reports, recycle bin, settings and backups.
- `CHECKLIST.md` — every requirement from the Version 1 build brief,
  marked Done, Partly or Not done.

## Project layout

- `config/` — project settings, URLs, WSGI/ASGI.
- `core/` — shared base models, permission map, money helpers, settings,
  soft delete, history, concurrency guards, PWA shell.
- `accounts/` — login/logout (users are Django superusers in V1).
- `customers/` — customers, opening balances, Excel/CSV import, ledger.
- `sales/` — products, sales, invoices, payments, allocation.
- `expenses/` — expense categories and expenses.
- `employees/` — employees and monthly payroll.
- `reports/` — dashboard, reports, exports.

Frontend libraries are vendored under `static/vendor/` (Bootstrap 5.3.3,
HTMX 2.0.4, Chart.js 4.4.1) — no CDN. The PWA icons in `static/icons/`
also ship as `.b64` text files (the GitHub App cannot push binaries);
decode them after checkout with
`for f in static/icons/*.b64; do base64 -d "$f" > "${f%.b64}"; done`.
