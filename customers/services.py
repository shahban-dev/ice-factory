"""Customer import from Excel/CSV.

Flow: upload (max 5 MB, max 5,000 rows) -> parse -> preview with row
errors and duplicate warnings -> confirm -> save in ONE transaction.
The uploaded file is processed in memory and never stored; parsed rows
live in the session only until confirmed or discarded.

Row errors block that row (missing name, bad phone, bad balance).
Duplicate phones are warnings only: the row can still be saved, matching
the customer rule that a duplicate phone is a warning, not a block.
"""

import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from customers.models import Customer, normalize_phone, validate_phone

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000


def parse_import_file(uploaded_file):
    """Parse an uploaded .xlsx or .csv file. Returns a list of row dicts:
    row_no, name, phone, address, opening_balance (Decimal), error, warnings.
    Raises ValidationError for file-level problems."""
    name = (uploaded_file.name or "").lower()
    if uploaded_file.size > MAX_FILE_BYTES:
        raise ValidationError("File is too large (maximum 5 MB).")
    if name.endswith(".xlsx"):
        raw_rows = _read_xlsx(uploaded_file)
    elif name.endswith(".csv"):
        raw_rows = _read_csv(uploaded_file)
    else:
        raise ValidationError("Only .xlsx and .csv files are accepted.")
    if len(raw_rows) > MAX_ROWS:
        raise ValidationError("Too many rows (maximum 5,000).")

    existing_phones = set(
        Customer.objects.filter(is_active=True)
        .exclude(phone="")
        .values_list("phone", flat=True)
    )
    seen_phones = set()
    rows = []
    for row_no, raw in enumerate(raw_rows, start=2):  # row 1 is the header
        row = {
            "row_no": row_no,
            "name": (raw.get("name") or "").strip(),
            "phone": normalize_phone(raw.get("phone") or ""),
            "address": (raw.get("address") or "").strip(),
            "opening_balance": Decimal("0"),
            "error": None,
            "warnings": [],
        }
        if not row["name"]:
            row["error"] = "Name is required."
        elif len(row["name"]) > 200:
            row["error"] = "Name is too long (maximum 200 characters)."
        if len(row["address"]) > 1000:
            row["error"] = "Address is too long (maximum 1000 characters)."
        balance_raw = (raw.get("opening_balance") or "").strip()
        if balance_raw:
            try:
                value = Decimal(balance_raw.replace(",", ""))
            except InvalidOperation:
                row["error"] = "Opening balance is not a number."
            else:
                # These used to pass the preview and crash the confirm
                # step (NaN, Infinity and huge values blow up the
                # database column), rolling back the whole import.
                if not value.is_finite():
                    row["error"] = "Opening balance must be a real number."
                elif abs(value) > Decimal("9999999999.99"):
                    row["error"] = (
                        "Opening balance is too large "
                        "(maximum Rs 9,999,999,999.99)."
                    )
                elif value != value.quantize(Decimal("0.01")):
                    row["error"] = (
                        "Opening balance must have at most 2 decimal places."
                    )
                else:
                    row["opening_balance"] = value
        if row["phone"]:
            try:
                validate_phone(row["phone"])
            except ValidationError:
                row["error"] = "Phone number is not a valid Pakistani mobile."
            else:
                if row["phone"] in existing_phones:
                    row["warnings"].append(
                        "Same phone as an existing customer."
                    )
                if row["phone"] in seen_phones:
                    row["warnings"].append(
                        "Same phone appears twice in this file."
                    )
                seen_phones.add(row["phone"])
        rows.append(row)
    return rows


def _read_xlsx(uploaded_file):
    import openpyxl

    workbook = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
    sheet = workbook.active
    iterator = sheet.iter_rows(values_only=True)
    try:
        header = next(iterator)
    except StopIteration:
        return []
    field_to_header = _map_columns(header)
    header_index = {}
    for index, name in enumerate(header):
        if name is not None:
            header_index.setdefault(str(name).strip().lower(), index)
    rows = []
    for values in iterator:
        if all(v is None or str(v).strip() == "" for v in values):
            continue
        row = {}
        for field, header_name in field_to_header.items():
            index = header_index.get(header_name.strip().lower())
            value = values[index] if index is not None and index < len(values) else None
            row[field] = "" if value is None else str(value)
        rows.append(row)
    return rows


def _read_csv(uploaded_file):
    text = uploaded_file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    field_to_header = _map_columns(reader.fieldnames)
    rows = []
    for raw in reader:
        if all((v or "").strip() == "" for v in raw.values()):
            continue
        row = {}
        for field, header_name in field_to_header.items():
            row[field] = raw.get(header_name) or ""
        rows.append(row)
    return rows


def _map_columns(headers):
    """Map header names (case-insensitive) to our fields. Returns
    {field: actual header string as it appears in the file}."""
    wanted = {"name": "name", "phone": "phone", "address": "address",
              "opening_balance": "opening_balance",
              "opening balance": "opening_balance",
              "balance": "opening_balance"}
    columns = {}
    for header in headers:
        if header is None:
            continue
        field = wanted.get(str(header).strip().lower())
        if field and field not in columns:
            columns[field] = str(header)
    return columns


def save_import_rows(rows, user):
    """Save error-free rows in one transaction. Rows are saved one by one
    (not bulk_create) so the audit history records every row. Returns how
    many were saved."""
    saved = 0
    with transaction.atomic():
        for row in rows:
            if row.get("error"):
                continue
            customer = Customer(
                name=row["name"], phone=row["phone"], address=row["address"],
                opening_balance=Decimal(str(row["opening_balance"])),
                created_by=user, updated_by=user,
            )
            customer._change_reason = "Imported from Excel/CSV"
            customer.save()
            saved += 1
    return saved
