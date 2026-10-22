# User guide — Ice Factory Management System

This is the plain-English guide for the two people who run the factory
system. Everything is in English. Money is in rupees (Rs). Dates are
shown day-month-year.

## Logging in

Open the site in your browser and log in with your username and
password. There are exactly two accounts, both with full access. If you
type the wrong password 5 times, your account locks for 15 minutes —
this is protection against guessing, not a fault. Wait, or ask the
other user to clear the lock from the admin panel.

To change your own password, use **Change password** next to your
username in the top menu. If you forget your password entirely, you
cannot reset it yourself — ask the developer to reset it from the
server (see DEPLOYMENT.md); it takes a minute and your data is
untouched.

On a phone, the menu is behind the button at the top. All buttons are
big enough to tap, and tables turn into stacked cards.

## The dashboard (home page)

- **Today's billed / collected** — what was sold and what was received today.
- **Today's expenses / profit** — today's expenses, and today's profit
  (billed minus expenses).
- **Total outstanding dues** — everything all customers owe right now.
- **This month** — billed, collected, expenses, and two profit numbers:
  - *Sales profit* = billed minus expenses.
  - *Cash profit* = collected minus expenses.
  - They differ because customers don't always pay on the day they buy.
- **Last 6 months** — a bar chart of billed, collected and expenses.
- **Top 5 debtors** — the customers who owe the most. Tap a name to see
  their ledger.
- **Today's activity** — every sale, payment and expense from today,
  refreshing itself every 30 seconds.
- **Quick add** — New sale, Record payment, Add expense.

## Customers

**Adding a customer:** Customers → Add customer. Name is required. Phone
is optional; type it any way you like (03001234567, +92 300 1234567) and
it is stored as 0300-1234567. Opening balance is what the customer
already owes (or a negative number if they paid in advance) before you
started using this system.

If another customer already has the same phone number, you still can
save — but a warning appears with a link to the other customer, so you
can check it isn't a duplicate entry.

**Customer page:** shows the balance, all sales and payments, and the
running balance (the ledger). You can filter the ledger by dates and
download it as PDF or Excel.

**Importing existing customers:** Customers → Import. Upload an Excel
or CSV file (maximum 5 MB, 5,000 rows) with columns name, phone,
address, opening_balance. You see a preview first: rows with errors are
marked, duplicates are warned about. A row is rejected in the preview
if its opening balance is not a plain number (values like NaN or
Infinity do not pass), is larger than Rs 9,999,999,999.99, has more
than 2 decimal places, or the name is longer than 200 characters.
Nothing is saved until you confirm. If a row has an error, that row is
skipped but the good rows still save.

**Deleting a customer:** a customer with sales, payments or a non-zero
balance cannot be deleted — the screen tells you and offers
*Deactivate instead*. Deactivated customers disappear from the sale
form but keep their history. A customer with nothing on record can be
deleted; the record goes to the recycle bin and can be restored.

## Products

Sales → Products. A product has a name, a size or description, and a
default price. The default price is just a starting point — you can
change the price on every sale. Products can be deactivated instead of
deleted; deactivated products disappear from the sale form.

## Sales

**New sale:** Sales → New sale, or Quick add on the dashboard.

1. Pick the customer by typing their name or phone (the list narrows
   as you type), or leave it blank for a walk-in cash sale.
2. Add rows: pick a product (its default price fills in), enter the
   number of blocks, change the price if needed.
3. Discount, if any (it cannot be more than the subtotal).
4. Payment: *Paid in full*, *Paid nothing*, or a custom amount.
5. Save, Save and print, or Save and new.

If you tap Save twice by accident, only one sale is created — the
second tap shows you the sale that was already saved. The same guard
covers payments and expenses.

**Invoice numbers** look like INV-2026-0001: the year, then a running
number. A deleted invoice's number is never reused, and a deleted
invoice prints with CANCELLED across it.

**What "paid" means:** a sale shows as paid, partial or unpaid based on
the payments made on that sale first, then on the customer's older
debts. A payment entered with a sale pays THAT sale first (up to its
total); any extra settles the customer's older debts. A general
payment (entered on the payment screen, not tied to a sale) settles
the oldest debt first: opening balance, then the oldest sale. So a
new sale paid in full at the counter shows as paid even if the
customer still owes from before — the old debt stays on the ledger,
and the invoice's "Customer's total outstanding" line shows it.

**Walk-in sales** (no customer) must be paid in full at the time of
sale — there is nobody to owe the balance.

**Editing a sale:** open the sale and press Edit. You must write a
reason (it is kept in the audit log). Changing the customer moves the
payments made on that sale to the new customer. Changing the sale's
date moves its payments to the new date as well, so daily cash stays
correct. If two people edit the same record at once, the second one
is stopped with a message naming who changed it and when — reload and
try again.

**Deleting a sale:** the sale and the payments entered with it go to
the recycle bin together. Payments the customer made separately (on the
payment screen) are NOT deleted with the sale.

**Invoice print:** open a sale and press Invoice, or Save and print.
The invoice shows the factory name, address and phone, the invoice
number and date, the customer (or "Walk-in / Cash"), the items,
subtotal, discount, total, how much was received with this sale, how
much is still unpaid on this invoice, and the customer's total
outstanding at the time of printing. For the sharpest print, use the
browser's print function on the invoice page — that is the
recommended path. The PDF download prints the same invoice, and
Urdu names and addresses print correctly in it (as in every PDF in
the system).

## Payments

Sales → Payments → Record payment, or Quick add on the dashboard.

Pick the customer, the date, the amount and the method (cash, bank
transfer, or other). A payment recorded on its own must have a
customer — the form will not save without one. The screen shows the
customer's current balance before you save. If you enter more than
they owe, the extra stays as advance credit — the system warns you,
but it is allowed, and the next sale will use it first.

Payments can be edited or deleted (with a reason). A payment entered on
a sale form belongs to that sale; a general payment belongs to the
customer's account. When you edit a payment, the customer cannot be
changed — delete it and enter a new one instead. If the payment
belongs to a walk-in sale, its amount cannot be changed here either:
edit the sale instead. A payment on a credit sale can change amount,
with a reason.

## Expenses

Expenses → Add expense. Pick a category, the date, the amount, the
method, and a short description. Dates cannot be in the future, and the
amount must be more than zero.

Categories are: Electricity, Diesel and fuel, Salaries, Maintenance,
Packaging, Rent, Transport, Other. *Salaries* is special: you cannot
pick it yourself — salary expenses appear automatically when a payroll
row is marked paid, and they cannot be edited or deleted from the
expense screen (reopen the payroll row instead).

## Employees and payroll

**Employees:** Employees → Add employee. Name, joining date and monthly
salary are required. CNIC is optional; if you enter it, type 13 digits
and it is stored as 12345-1234567-1. In lists the CNIC is masked
(12345-*******-1); the full number shows only on the employee's own
page. An employee with payroll rows cannot be deleted — deactivate
them instead.

**Monthly payroll:** Employees → Payroll → Generate for a month. The
system creates a draft row for everyone who worked that month,
decided by dates, not by whether they are still active: someone who
joined on or before the last day of the month and left on or after
the first day gets a row — so a person who left mid-month and was
deactivated before payroll ran still gets their last partial month.
Deactivating an employee requires a leaving date (the screen sends
you to add one if it is missing). Staff deactivated without a
leaving date are listed as a warning and get no row.

- *Days employed* counts inclusively: someone who joined on the 16th of
  a 31-day month gets 16 days.
- *Base salary* is the monthly salary scaled by days employed. A full
  month is exactly the monthly salary, to the rupee.
- Add a bonus or deductions by hand. Net = base + bonus − deductions; it can never be
  negative.
- Changing an employee's monthly salary later does not change payroll
  rows that are already made.

**Loans:** an employee's page has a Loans section. Give a loan with the
date, the amount and the monthly installment. A loan is money the
employee owes you — it is NOT an expense, so giving one does not change
that month's profit. Each month's payroll proposes a deduction from the
oldest active loan: the installment, or what is left of the loan,
whichever is smaller, and never more than the month's pay (so net never
goes below zero). When that payroll row is marked paid, the deduction
counts as repaid and the loan balance drops; reopening the row reverses
it. A loan is settled automatically when nothing is left. You cannot
delete a loan that has already had repayments; deleting a loan with no
repayments yet clears it from any draft payroll rows.

**Paying:** open a payroll row and press Mark paid. Enter the date
actually paid (it cannot be in the future) — the salary counts as an
expense in the month it was PAID, not the month it was earned. The
amount paid is normally the net, but you can pay a different amount
(for example a part-payment) — then a note is required, saying why.
The system creates exactly one Salaries expense for the amount paid
plus any loan deduction, on the same date. So a repayment never reduces
the salary expense: a Rs 30,000 salary with a Rs 5,000 loan deduction
shows a Rs 30,000 expense, of which Rs 25,000 reached the employee and
Rs 5,000 repaid the loan. A row whose net is zero but which repays a
loan can still be marked paid. To change a paid row, press Reopen
first: the row goes back to draft and its salary expense is removed;
paying again creates a new one.

**Payslip:** open a payroll row and press Payslip PDF. It shows the
employee, month, days employed, base, bonus, deductions, net, and paid
date. The CNIC on the payslip is masked.

## Reports

Reports → pick a report. Every report can be downloaded as PDF or
Excel. The definitions below are printed on every report.

**Profit report:** Reports → Profit report. Pick Today, Yesterday,
This week, Last week, This month, Last month, or your own dates, and
see billed, collected, expenses and both profit numbers for exactly
that period. The week starts on the day set in Settings (Monday by
default).

**Monthly report** shows two salary lines, because they are different
things: *salary earned* is what the month's payroll rows add up to,
and *salaries paid* is what was actually paid out during the month
(a September salary paid on 2 October counts in October). It also
shows *loans outstanding to employees* at the end of the month.

- **Monthly report** — billed, collected, expenses by category,
  salaries paid, both profits, blocks sold per product, top 10
  customers by billed, and outstanding at month end.
- **Customer dues report** — everyone who owes, their balance, their
  oldest unpaid invoice date, and their last payment date.
- **Sales register** — all sales in a date range, filterable by
  customer or product.
- **Expense report** — all expenses in a date range, filterable by
  category, with totals by category.

Definitions used everywhere:

- *Billed* = sum of sale totals by sale date. Opening balances are NOT
  billed. A sale total is its items minus its discount, and deleted
  sales are not counted.
- *Collected* = sum of payments by payment date, including payments
  toward opening balances.
- *Expenses* = sum of expenses by expense date, including salary
  payments.
- *Sales profit* = Billed − Expenses. *Cash profit* = Collected −
  Expenses.
- *Customer balance* = opening balance + sale totals − payments.
  Positive means the customer owes; negative means advance credit.
  Deleted sales and their payments are excluded from every figure.

## Audit log

Reports → Audit log. Every change to every record: who did it, when,
what changed (old value → new value), and the reason they wrote. You
can filter by user, record type, date, and record name. Nothing in the
audit log can be edited or deleted.

## Recycle bin

Reports → Recycle bin. Everything deleted, in one place, with who
deleted it and when. Press Restore to bring a record back. Restoring a
sale also restores the payments deleted with it. Restoring a payment
that was deleted with its sale restores the whole sale. Nothing is
permanently deleted from this screen. A restore can be refused with a
message: a sale whose customer is still deleted cannot come back
until the customer is restored first, and a payroll row or employee
cannot be restored if a live row already uses that month or CNIC.

## Settings

Reports → Settings. Factory name, address, phone, invoice prefix
(default INV), an optional tax registration line that prints on
invoices, a footer note for invoices, and which day the week starts
on (for the profit report's week buttons). The page also shows the
last successful backup.

## Backups

Backups run automatically every night at 02:00 and are stored encrypted
and copied off the server. Backup files on the server can only be read
by the server's own user — nobody else on the machine can open them.
If no backup has succeeded for 36 hours, a warning appears on the
dashboard: do not ignore it. From the Settings page you can also download
a fresh backup at any time — you will be asked for your login password
again, and the download is logged. Keep the backup passphrase somewhere
safe off the server: without it, encrypted backups cannot be restored.
If the server ever fails, the restore steps are in DEPLOYMENT.md.

## WhatsApp messages

Nothing is sent automatically. On a sale's page and on the invoice there
is a **Share invoice on WhatsApp** button, on a customer's page a
**Send dues reminder** button, and on the dues report one per customer.
Each opens WhatsApp with a ready-written message — you check it and
press send yourself. The button only appears for a Pakistani mobile
number (03XX…); landline numbers get no button, because WhatsApp
cannot message them.
