# Version 1 requirement checklist

Every requirement from the Version 1 build brief, marked **Done**,
**Partly** or **Not done**. "Done" means implemented, verified by the
test suite or a live check, and documented where the brief asks for
documentation.

## Stack and project

- Python 3.12, Django 5.2 LTS pinned, PostgreSQL 16 in production,
  psycopg 3 — **Done** (production runs PostgreSQL via `DATABASE_URL`;
  local development falls back to SQLite, which is also how the backup
  restore was tested here).
- Templates + HTMX + Bootstrap 5 + Chart.js, all vendored at pinned
  versions, no CDN — **Done** (Bootstrap 5.3.3, HTMX 2.0.4, Chart.js
  4.4.1 under `static/vendor/`).
- django-simple-history, django-environ, whitenoise, gunicorn,
  django-axes, ReportLab, openpyxl — **Done** (all in
  `requirements.txt`, pinned).
- Apps: core, accounts, customers, sales, expenses, employees, reports
  — **Done**.

## Users and permissions

- Exactly two users, both with the same single ADMIN role (Django
  superusers, created by the developer); no user-management screen —
  **Done**.
- Permissions defined in ONE module (`core/permissions.py`) as a
  role→codes map — **Done**.
- Enforced server-side on every view, HTMX endpoint, export and
  download — **Done** (permission test suite hits every app URL plus
  every export/download/backup endpoint).
- Anonymous users redirect to login; authenticated users without
  permission get 403 — **Done** (a Phase 5 test run caught the mixin
  403-ing anonymous users too; fixed and tested).
- Django admin at a non-default URL from the environment, superusers
  only — **Done** (`ADMIN_URL`, default `site-admin/`).

## Scope

- Customers with opening balances + Excel/CSV import — **Done**.
- Products — **Done**.
- Sales + invoices — **Done**.
- Payments + customer ledger — **Done**.
- Expenses — **Done**.
- Employees + monthly payroll — **Done**.
- Dashboard — **Done**.
- Reports with PDF + Excel export — **Done**.
- Audit log — **Done**.
- Soft delete with restore — **Done**.
- Global search — **Done**.
- Settings — **Done**.
- PWA — **Done** (manifest, 192/512/maskable icons, standalone,
  theme color, apple-touch-icon, offline-only service worker).
- Backups — **Done** (command, rotation, off-server upload, log,
  settings display, manual download).
- VPS deployment guide — **Done** (`DEPLOYMENT.md`; provisioning the
  actual server, domain and keys is the owner's step, covered by the
  go-live checklist).
- Version 2 backlog NOT built — **Done** (no stock/production, damaged
  blocks, deliveries/vehicles/drivers, daily attendance, salary
  advances, daily cash closing, month locking, restricted Manager role,
  receipt photos, offline entry, Urdu, or customer price lists exist
  anywhere in the code).

## Money, dates, display

- Decimal(12,2) only, ROUND_HALF_UP through one helper — **Done**
  (`core.money.q2`).
- Totals always computed server-side — **Done**.
- UTC storage, Asia/Karachi display — **Done**.
- Business dates are DateFields; "today" is `timezone.localdate()` —
  **Done**.
- Sales, payments, expenses and salary payments cannot be future-dated
  — **Done** (validated server-side, tested).
- Display `Rs 1,250,000`, decimals only when non-zero — **Done**.
- Negative customer balance shows as "Rs X credit" — **Done**.

## Report definitions (printed on every report)

- Billed, Collected, Expenses, Sales profit, Cash profit, Customer
  balance, salary-counts-only-when-paid — **Done** (all verified
  against hand calculation, including a September salary paid in
  October counting in October, never double counted).

## Base model and audit

- created_at, updated_at, created_by, updated_by, is_deleted,
  deleted_at, deleted_by, delete_batch (UUID), version — **Done** on
  Customer, Sale, Payment, Expense, Employee, Payroll.
- Default manager hides deleted rows; `all_objects` sees all — **Done**.
- Product, ExpenseCategory, SaleItem have no soft delete — **Done**.
- All business FKs PROTECT; audit FKs SET_NULL — **Done**.
- Unique rules ignore deleted rows (partial UniqueConstraints) —
  **Done**.
- simple-history on every business table including SaleItem and
  Settings, with change reasons — **Done**.
- Optimistic concurrency: version on edit forms, `select_for_update`,
  mismatch refused with "This record was changed by NAME at TIME.
  Reload and try again." — **Done** (tested; version rises on every
  save including soft delete/restore).
- Soft delete only via ONE service function; children deleted with a
  parent share one delete_batch so restore brings back exactly those —
  **Done**.

## Customers

- Phone optional, normalized to 03XX-XXXXXXX, accepts 03XX-XXXXXXX and
  +92 forms — **Done** (tested).
- Duplicate phone = warning with link, still savable — **Done** (link
  fixed in Phase 5 to render as a real link with the name escaped).
- Cannot delete with any non-deleted sale/payment or non-zero balance;
  deactivate instead — **Done** (tested).
- Inactive customers hidden from new-sale pickers — **Done**.
- List balances via aggregate queries, not per-row — **Done**
  (query-count test guards it).
- Ledger = opening balance then sales + payments in date order
  (tie-break created_at) with running balance, date-range filter,
  PDF + Excel export — **Done**.
- Import .xlsx/.csv ≤ 5 MB ≤ 5,000 rows, upload → preview (row errors +
  duplicate warnings) → confirm → save in one transaction, file
  processed in memory and never stored — **Done** (tested: preview
  errors, duplicate warnings, atomic save).

## Products

- Name unique among active, size/description, default_price ≥ 0,
  is_active — **Done**.

## Sales

- Invoice INV-YYYY-0001, year of sale date at creation, 4-digit
  per-year sequence from a counter row locked with `select_for_update`
  (never max()+1), unique, never changes, deleted numbers never reused
  — **Done** (tested: sequence, year rollover, deleted reuse,
  simultaneous saves).
- SaleItem unit_price is a snapshot — **Done**.
- ≥1 item, discount 0..subtotal, total > 0 — **Done** (tested).
- Walk-in (customer null) must be fully paid at sale time — **Done**
  (tested).
- "Paid now" creates a Payment linked to the sale, ≤ total — **Done**
  (tested).
- Invoice status paid/partial/unpaid is COMPUTED by ONE allocation
  function (pool all customer payments, opening first, then sales by
  (date, id); negative opening counts as extra payment; leftover =
  advance credit), used by ledger, invoice, customer list, reports —
  **Done** (tested: partial, exact, overpayment, negative opening,
  edit after payment, delete with payments, restore).
- Sale edit replaces items in one transaction, edit reason required,
  warning if new total makes balance negative — **Done** (tested).
- Changing customer moves linked payments (sale-form payments only) —
  **Done** (tested).
- Changing to walk-in rejected unless fully paid — **Done** (tested).
- Editing a walk-in sale's total updates its linked payment — **Done**
  (tested).
- Sale soft-delete also soft-deletes the payments entered WITH it
  (same batch, confirmation states the amount); later general payments
  never deleted by this — **Done** (tested).
- Printable HTML invoice + ReportLab PDF (factory name/address/phone/
  logo, optional tax line, invoice number/date, customer or "Walk-in /
  Cash", items, subtotal, discount, total, amount received with this
  sale, remaining on this invoice at issue, customer's total
  outstanding at print time, print timestamp) — **Done**.
- Fast entry: HTMX customer search-as-you-type, default price
  prefilled, add rows, Paid in full / Paid nothing / Custom amount,
  Save / Save and print / Save and new — **Done**.

## Payments

- Customer empty only for a walk-in sale's payment; sale set only when
  entered on the sale form — **Done**.
- Amount > 0; method cash/bank transfer/other; reference note — **Done**.
- General payment screen shows current balance + overpayment warning
  (excess kept as advance credit) — **Done**.
- Editable/deletable with reason, audit logged — **Done**.

## Expenses

- ExpenseCategory name unique, is_active, is_system; 8 defaults
  including Salaries as system (cannot be deactivated or chosen
  manually) — **Done** (tested).
- Expense date/category/amount > 0/description/method; future-date
  blocked — **Done** (tested).
- Payroll-linked expenses read-only on expense screens — **Done**
  (tested).
- No file uploads in V1 except the import file — **Done**.

## Employees and payroll

- Employee CNIC optional, format 12345-1234567-1, unique among active
  employees, masked in lists, full only on detail — **Done** (tested).
- Role worker/driver/other — **Done**.
- Cannot delete if payroll exists — **Done** (tested via the view).
- Payroll unique per employee/year/month among non-deleted — **Done**
  (tested).
- Net = base + bonus − deductions computed server-side, must be ≥ 0
  (rejected, never clamped) — **Done** (tested).
- Proration: days_employed inclusive from max(joining, month start) to
  min(leaving or month end, month end); base = monthly_salary ×
  days_employed / days_in_month rounded 2dp; full month = exactly
  monthly_salary; no row if not employed that month — **Done**
  (tested: full month, mid-month joiner/leaver, Feb 28 + Feb 29,
  31-day month, not-employed).
- Generate creates drafts for all eligible employees, skips existing —
  **Done** (tested).
- Mark paid requires paid_date (not future) + net > 0 and creates
  linked Expense (category Salaries, date = paid_date, amount =
  net_salary, description "Salary MONTH YEAR - EMPLOYEE") in the same
  transaction; salary counts in the month PAID — **Done** (tested).
- Editing a paid row requires Reopen first (status back to draft,
  linked expense soft-deleted) — **Done** (tested).
- monthly_salary changes never alter past payroll — **Done** (tested).
- Payslip PDF (employee, month, days employed, base, bonus, deductions
  with note, net, paid date; masked CNIC) — **Done**.

## Dashboard

- Today's billed/collected, total outstanding dues; this month's
  billed/collected/expenses/sales profit/cash profit (green money in,
  red dues/expenses); 6-month chart billed/collected/expenses; top 5
  debtors; today's activity auto-refreshing every 30s via HTMX;
  quick-add sale/payment/expense — **Done**.

## Reports

- Monthly report (billed, collected, expenses by category, salaries
  paid, sales profit, cash profit, blocks sold per product, top 10
  customers by billed, outstanding at month end, definitions shown) —
  **Done**.
- Customer dues report (balance, oldest unpaid invoice date, last
  payment date) — **Done**.
- Sales register (date range, filter customer/product) — **Done**.
- Expense report (category + date range) — **Done**.
- Customer ledger — **Done**.
- Date filter on all reports; PDF + Excel for the first four — **Done**.
- Excel/CSV exports neutralize formula injection (leading apostrophe
  for cells starting = + - @) — **Done** (tested).

## System

- Audit log screen (who/what/when/object/old→new/reason; filter
  user/model/date/object) — **Done**.
- Recycle bin restore (restoring a sale restores its delete_batch; no
  permanent deletion in UI) — **Done** (tested, including the
  payroll-expense guard; restore is refused with a message when the
  sale's customer is still deleted, or when a live payroll row or
  CNIC already exists).
- Global search (customer name/phone, invoice number) — **Done**.
- Settings single row with history (factory name, address, phone,
  invoice prefix default INV, optional tax registration line, invoice
  footer note; logo is a static repo file) — **Done**.
- Backups: `backup_db` command (pg_dump custom format, compress,
  encrypt, upload OFF-server, keep 30 daily + 12 monthly, log
  success/failure), cron daily 02:00 Asia/Karachi, last successful
  backup shown on settings page, manual backup download requires
  password re-entry + audit log, restore instructions + tested restore
  on a fresh DB — **Done** (restore tested end-to-end on SQLite:
  decrypt + gunzip + open with correct data, AND on PostgreSQL: an
  encrypted backup restored into a fresh PostgreSQL database with
  matching row counts, verified 2026-10-22; the operator repeats the
  pg_restore run on the VPS per DEPLOYMENT.md).
- PWA manifest (192/512/maskable icons, standalone, theme color),
  apple-touch-icon, minimal service worker whose only job is a friendly
  no-connection page — never caches app pages/data — **Done**.
- Friendly 403/404/500 — **Done**.
- HTMX session expiry gives full login redirect (HX-Redirect) — **Done**.
- CSRF token on every HTMX request — **Done** (`hx-headers` on `<body>`).
- Toast on failed HTMX request — **Done**.
- Mobile 44px+ tap targets, inputmode decimal, tables become cards,
  native date inputs, thousands separators — **Done**.
- English UI wrapped for translation — **Partly**. The UI is English
  throughout, but template strings are not wrapped in `{% trans %}` /
  `{% blocktrans %}` tags. Translation would require a mechanical
  pass over the templates; nothing else blocks it, and no translation
  is needed for Version 1's single-language use.

## Validation, transactions, queries

- Server-side validation; DB CHECKs (amount > 0, quantity > 0,
  unit_price ≥ 0, discount ≥ 0, totals ≥ 0, month 1–12,
  bonus/deductions ≥ 0, salary ≥ 0) — **Done**.
- Indexes Sale(customer, date), Sale(date), Payment(customer, date),
  Expense(date, category), Payroll(year, month) — **Done**.
- transaction.atomic for sale + items + payment + invoice number, sale
  edit, sale delete, payroll generate, mark paid + expense, customer
  import — **Done**.
- Avoid N+1; assertNumQueries tests for dashboard, customer list,
  ledger — **Done** (8 / 34 / 11 queries with 10 customers).

## Security

- Password validators, minimum length 10 — **Done**.
- Axes lock after 5 failed logins for 15 min per (username, IP)
  combination, real client IP behind Nginx — **Done** (tested; Phase 5
  found and fixed two issues: the setting must be a nested list for
  combination semantics, and django-ipware is not installed, so a
  dedicated `core.axes_ip` callable reads the last X-Forwarded-For
  entry instead of silently falling back to REMOTE_ADDR).
- Sessions 7 days sliding, HttpOnly, Secure, SameSite=Lax — **Done**.
- HTTPS only, SSL redirect, HSTS, SECURE_PROXY_SSL_HEADER — **Done**.
- DEBUG=False in production — **Done** (enforced by the deployment
  guide; `check --deploy` is clean).
- `manage.py check --deploy` clean — **Done** (verified with a
  production-like environment).
- Secrets only in env, `.env` git-ignored, `.env.example` shipped —
  **Done**.
- No raw SQL — **Done** (ORM only).
- CSRF on every POST — **Done**.
- Never mark user text safe — **Done** (the one place markup is
  needed, the duplicate-phone warning link, uses `format_html`, which
  escapes the user-supplied name).
- Rotating error log file, no stack traces to users — **Done**.

## Deployment

- Single Ubuntu LTS VPS, step-by-step DEPLOYMENT.md (low-latency
  region, non-root user, SSH keys only, firewall SSH/80/443,
  PostgreSQL 16 on same server not exposed, venv, env file, migrate,
  collectstatic, superuser, gunicorn systemd, Nginx reverse proxy,
  DNS + Let's Encrypt auto-renew, log rotation, cron backup with
  encryption + off-server upload via rclone to Backblaze B2 or Google
  Drive, restore procedure, update + rollback) — **Done**.
- Go-live checklist — **Done** (in DEPLOYMENT.md).

## Deliverables

- requirements.txt — **Done**.
- .env.example — **Done** (includes backup variables).
- README.md — **Done**.
- DEPLOYMENT.md — **Done**.
- USER_GUIDE.md (plain English) — **Done**.
- This checklist — **Done**.

## Testing (Phase 5 suite: 85 tests, all passing)

- Money rounding — **Done**.
- Sale totals/discount — **Done**.
- Invoice sequence + uniqueness incl. simultaneous saves, year
  rollover, deleted numbers never reused — **Done**.
- Balance/allocation (partial, exact, overpayment, negative opening,
  edit after payment, delete sale with payments, restore) — **Done**.
- Walk-in fully paid — **Done**.
- Paid-now ≤ total — **Done**.
- Future dates blocked — **Done**.
- Payroll (full month, mid-month joiner/leaver, Feb 28 + 29, 31-day
  month, bonus/deduction, negative net rejected, duplicate month
  blocked, mark paid creates exactly one expense, reopen removes it,
  salary change doesn't alter past rows, salary paid next month
  counts in month paid) — **Done**.
- Reports match hand calculation, salary never double counted — **Done**.
- Permissions (every URL redirects anonymous to login; role-less user
  gets 403; every export/download/backup checked) — **Done**.
- Soft delete/restore — **Done**.
- Deletion blocked for customer with dues and employee with payroll —
  **Done**.
- Stale version rejected — **Done**.
- Phone/CNIC validation — **Done**.
- Duplicate phone warning — **Done**.
- Import preview/errors/atomic save — **Done**.
- Excel formula neutralization — **Done**.
- Axes lockout behind proxy header — **Done**.
- assertNumQueries for dashboard, customer list, ledger — **Done**.
- seed_demo command with hand-calculated expected totals file —
  **Done** (refuses unless DEBUG or forced with typed confirmation;
  refuses if demo data already exists).

## Group A fixes (2026-10-22; 115 tests, all passing on SQLite)

- One money source of truth: dashboard, monthly report, sales
  register, customer list and ledger all derive billed, collected,
  balance and outstanding from the same functions — sale totals are
  items minus discount, and deleted sales are excluded everywhere.
- Allocation: a sale's own payments apply to that sale first (capped
  at its total, overflow to the pool), then pool and general payments
  settle the oldest debt first (opening balance, then oldest sale).
  Customer balance totals are unchanged.
- Standalone payment requires a customer (form error, nothing saved);
  a database constraint enforces "customer or sale" on every payment
  row. The migration hard-deletes any existing orphan payments
  (their audit history rows are kept).
- Payment edits: the customer can never change; a walk-in sale's
  payment amount is locked (edit the sale instead); a credit sale's
  linked payment amount can change with a reason; editing a sale's
  date moves its linked payments to the new date.
- Payroll eligibility is by dates, not by active flag: a leaver
  deactivated before payroll ran still gets their last partial month.
  Deactivating an employee requires a leaving date; staff deactivated
  without one are listed as a warning and get no row.
- Customer import rejects non-finite balances (NaN/Infinity),
  balances over Rs 9,999,999,999.99, more than 2 decimals, names over
  200 characters and addresses over 1,000 characters — in the
  preview, never as a crash on confirm.
- Urdu names and addresses print correctly in every PDF (invoice,
  ledger, payslip, report PDFs) via a bundled Noto Sans Arabic font
  with reshaping; browser print of the HTML invoice is the
  recommended print path.
- Robustness: invalid query strings (bad customer id, bad date) are
  ignored instead of returning 500; money fields accept at most 2
  decimals; recycle-bin restore failures show a message instead of
  500.

## Process (from the brief)

- Questions-first reply, then wait — **Done** (Phase 0).
- Schema + flaw review, then wait for OK — **Done** (Step 2).
- Build in 5 phases, one per reply — **Done** (Phases 1–5).
- Re-check own code after each phase, report fixes + what to test by
  hand — **Done** (each phase report lists bugs found in self-review).
- Complete runnable code, no placeholders — **Done**.
- Final checklist marking every requirement Done/Partly/Not done —
  **Done** (this file).

## Edge cases tested (beyond the list above)

- Concurrent invoice creation under threads (distinct numbers).
- Edit of a walk-in sale updates its single linked payment.
- Customer move moves only sale-form payments, not general payments.
- Filtered ledger starts from opening + pre-period entries.
- Payroll-linked expense restore blocked when the payroll already has
  a different live expense (no double-count after reopen + re-pay).
- Zero-net payroll cannot be marked paid.
- Backup encryption round-trip (decrypt + gunzip + open, data intact).
- Manual backup download rejects a wrong password and returns a real
  gzip file with the right one.
- Locked-out account still refuses the correct password; a different
  IP (or username) is unaffected; a success resets the counter.
