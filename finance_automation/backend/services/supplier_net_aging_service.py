"""Creditor aging and supplier-wise net balance report generation."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

AGING_BUCKETS = (
    ("Current", None, 0),
    ("00-30", 1, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("91-180", 91, 180),
    ("181-365", 181, 365),
    ("366-730", 366, 730),
    ("731-1095", 731, 1095),
    ("1096+", 1096, None),
)

DEBTOR_BUCKET_HEADERS = (
    "currentbucket",
    "age0030",
    "age3160",
    "age6190",
    "age91180",
    "age181365",
    "age366730",
    "age7311095",
    "age1096above",
)

LEGAL_SUFFIXES = {
    "ag",
    "bv",
    "co",
    "corp",
    "corporation",
    "company",
    "gmbh",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "ltd",
    "nv",
    "plc",
    "pte",
    "berhad",
    "qsc",
    "sa",
    "sarl",
    "spa",
}

MONEY_FORMAT = '#,##0.00;[Red](#,##0.00);-'
DATE_FORMAT = "dd-mmm-yyyy"
HEADER_FILL = PatternFill("solid", fgColor="0B3041")
HEADER_FONT = Font(color="FFFFFF", bold=True)


class CreditorAgingError(ValueError):
    """Raised when an uploaded workbook is not valid for this report."""


def _header_token(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _supplier_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).casefold()
    words = re.findall(r"[a-z0-9]+", text)
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return "".join(words)


def _to_date(value: Any, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for date_format in (
            "%Y-%m-%d",
            "%d-%b-%Y",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d-%m-%Y",
        ):
            try:
                return datetime.strptime(text[:10], date_format).date()
            except ValueError:
                continue
    raise CreditorAgingError(f"{label} is missing or is not a valid date.")


def _decimal(value: Any, label: str) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, bool):
        raise CreditorAgingError(f"{label} is not a valid amount.")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "").replace("$", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise CreditorAgingError(f"{label} is not a valid amount: {value!r}.") from exc


def _open_workbook(path: Path):
    try:
        return openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise CreditorAgingError(f"Cannot open Excel workbook {path.name}: {exc}") from exc


def _find_header_row(
    workbook: openpyxl.Workbook,
    required_headers: Dict[int, str],
    label: str,
) -> Tuple[Any, int]:
    for worksheet in workbook.worksheets:
        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=1, max_row=min(worksheet.max_row, 50), values_only=True),
            start=1,
        ):
            if all(
                column < len(row)
                and _header_token(row[column]) == expected_header
                for column, expected_header in required_headers.items()
            ):
                return worksheet, row_number
    raise CreditorAgingError(
        f"Could not identify the {label} worksheet from its Excel column headers."
    )


def _is_total_row(value: Any) -> bool:
    text = str(value or "").casefold()
    if any(marker in text for marker in ("subtotal", "sub total", "grand total", "natural account total")):
        return True
    return bool(re.fullmatch(r"\s*total\s*:?\s*", text))


def _bucket_index(days_past_due: int) -> int:
    if days_past_due <= 0:
        return 0
    for index, (_, lower, upper) in enumerate(AGING_BUCKETS[1:], start=1):
        if lower is not None and upper is not None and lower <= days_past_due <= upper:
            return index
    return len(AGING_BUCKETS) - 1


def _currency_from_erp(worksheet: Any, rows: Sequence[Tuple[Any, ...]]) -> Optional[str]:
    transaction_currencies = {
        str(row[6]).strip().upper()
        for row in rows
        if len(row) > 6 and row[6] not in (None, "")
    }
    if len(transaction_currencies) > 1:
        raise CreditorAgingError(
            f"Debtor ERP transaction rows contain multiple currencies: {', '.join(sorted(transaction_currencies))}."
        )

    for row in worksheet.iter_rows(min_row=1, max_row=min(worksheet.max_row, 15), values_only=True):
        for index, value in enumerate(row):
            if _header_token(value) == "currency" and index + 1 < len(row) and row[index + 1]:
                report_currency = str(row[index + 1]).strip().upper()
                if transaction_currencies and transaction_currencies != {report_currency}:
                    raise CreditorAgingError(
                        f"Debtor ERP report currency {report_currency} does not match its transaction currency."
                    )
                return report_currency
    if len(transaction_currencies) == 1:
        return transaction_currencies.pop()
    return None


def _read_creditor_transactions(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    workbook = _open_workbook(path)
    try:
        worksheet, header_row = _find_header_row(
            workbook,
            {
                0: "sourcename",
                1: "customersuppliername",
                7: "duedate",
                16: "entereddue remaining".replace(" ", ""),
            },
            "creditor netting",
        )
        transactions = []
        currencies = set()
        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=header_row + 1, values_only=True),
            start=header_row + 1,
        ):
            source = str(row[0] or "").strip().casefold() if len(row) else ""
            if source not in {"paybles", "payables"}:
                continue

            supplier = str(row[1] or "").strip() if len(row) > 1 else ""
            if not supplier:
                raise CreditorAgingError(
                    f"Payable row {row_number} has no supplier name in column B."
                )
            if len(row) <= 16:
                raise CreditorAgingError(
                    f"Payable row {row_number} does not contain column Q."
                )

            due_date = _to_date(row[7] if len(row) > 7 else None, f"Due date at row {row_number}")
            entered_due = _decimal(row[16], f"Entered Due Remaining at row {row_number}")
            creditor_balance = -entered_due
            currency = str(row[12] or "").strip().upper() if len(row) > 12 else ""
            if currency:
                currencies.add(currency)
            transactions.append(
                {
                    "supplier": supplier,
                    "supplier_key": _supplier_key(supplier),
                    "source_name": str(row[0]).strip(),
                    "transaction_number": row[4] if len(row) > 4 else None,
                    "transaction_type": row[8] if len(row) > 8 else None,
                    "due_date": due_date,
                    "currency": currency,
                    "entered_due_remaining": entered_due,
                    "creditor_balance": creditor_balance,
                    "days_past_due": None,
                    "bucket_index": None,
                }
            )
        return transactions, sorted(currencies)
    finally:
        workbook.close()


def _read_erp_debtors(path: Path) -> Tuple[List[Dict[str, Any]], date, Optional[str]]:
    workbook = _open_workbook(path)
    try:
        worksheet, header_row = _find_header_row(
            workbook,
            {
                0: "customername",
                10: "outstandingamount",
                **{11 + index: header for index, header in enumerate(DEBTOR_BUCKET_HEADERS)},
            },
            "debtor ERP aging",
        )
        report_date = _to_date(worksheet["B2"].value, "Debtor ERP report date in B2")
        raw_rows = worksheet.iter_rows(min_row=header_row + 1, values_only=True)
        transaction_rows: List[Tuple[Any, ...]] = []
        debtors = []

        for row_number, row in enumerate(raw_rows, start=header_row + 1):
            customer = str(row[0] or "").strip() if len(row) else ""
            if not customer or _is_total_row(customer):
                continue
            amount_value = row[10] if len(row) > 10 else None
            if amount_value in (None, ""):
                continue
            amount = _decimal(amount_value, f"Outstanding Amount at row {row_number}")
            buckets = [
                _decimal(row[11 + index] if len(row) > 11 + index else None,
                         f"ERP aging bucket at row {row_number}")
                for index in range(len(AGING_BUCKETS))
            ]
            debtors.append(
                {
                    "supplier": customer,
                    "supplier_key": _supplier_key(customer),
                    "debtor_balance": amount,
                    "buckets": buckets,
                }
            )
            transaction_rows.append(row)

        currency = _currency_from_erp(worksheet, transaction_rows)
        return debtors, report_date, currency
    finally:
        workbook.close()


def validate_creditor_netting_file(path: Path) -> Dict[str, Any]:
    transactions, currencies = _read_creditor_transactions(path)
    if not transactions:
        raise CreditorAgingError("The workbook has no payable transactions under Source Name.")
    if len(currencies) > 1:
        raise CreditorAgingError(
            f"The creditor netting workbook contains multiple currencies: {', '.join(currencies)}."
        )
    return {"payables_rows": len(transactions), "currencies": currencies}


def validate_erp_debtor_file(path: Path) -> Dict[str, Any]:
    transactions, report_date, currency = _read_erp_debtors(path)
    if not transactions:
        raise CreditorAgingError("The workbook has no debtor transaction rows.")
    return {
        "report_date": report_date,
        "currency": currency,
        "transaction_rows": len(transactions),
    }


def _add_worksheet(
    workbook: openpyxl.Workbook,
    title: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    date_columns: Sequence[int] = (),
    money_columns: Sequence[int] = (),
) -> Any:
    worksheet = workbook.create_sheet(title)
    worksheet.append(list(headers))
    for cell in worksheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    worksheet.row_dimensions[1].height = 32
    for values in rows:
        worksheet.append(list(values))
    worksheet.freeze_panes = "A2"
    if worksheet.max_row > 1:
        worksheet.auto_filter.ref = worksheet.dimensions
    for column in date_columns:
        for row in range(2, worksheet.max_row + 1):
            worksheet.cell(row, column).number_format = DATE_FORMAT
    for column in money_columns:
        for row in range(2, worksheet.max_row + 1):
            worksheet.cell(row, column).number_format = MONEY_FORMAT
    for column_cells in worksheet.columns:
        column_number = column_cells[0].column
        max_width = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=10,
        )
        worksheet.column_dimensions[get_column_letter(column_number)].width = min(max(max_width + 2, 12), 36)
    return worksheet


def _suggest_supplier_match(name: str, candidates: Sequence[str]) -> Tuple[str, Optional[float]]:
    key = _supplier_key(name)
    if not key or not candidates:
        return "", None
    scores = sorted(
        ((SequenceMatcher(None, key, _supplier_key(candidate)).ratio(), candidate) for candidate in candidates),
        reverse=True,
    )
    if not scores or scores[0][0] < 0.75:
        return "", None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.05:
        return "", None
    return scores[0][1], scores[0][0]


def _unique_fuzzy_matches(
    debtor_suppliers: Dict[str, Dict[str, Any]],
    creditor_suppliers: Dict[str, Dict[str, Any]],
) -> Dict[str, Tuple[str, float]]:
    debtor_only = set(debtor_suppliers) - set(creditor_suppliers)
    creditor_only = set(creditor_suppliers) - set(debtor_suppliers)

    def best_match(key: str, candidates: Iterable[str]) -> Optional[Tuple[str, float]]:
        scores = sorted(
            (
                (SequenceMatcher(None, key, candidate).ratio(), candidate)
                for candidate in candidates
            ),
            reverse=True,
        )
        if not scores or scores[0][0] < 0.92:
            return None
        if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.05:
            return None
        return scores[0][1], scores[0][0]

    matches: Dict[str, Tuple[str, float]] = {}
    for debtor_key in debtor_only:
        candidate = best_match(debtor_key, creditor_only)
        if candidate is None:
            continue
        creditor_key, score = candidate
        reverse_candidate = best_match(creditor_key, debtor_only)
        if reverse_candidate and reverse_candidate[0] == debtor_key:
            matches[debtor_key] = (creditor_key, score)
    return matches


def _validate_reconciliation(
    debtor_total: Decimal,
    debtor_bucket_total: Decimal,
    creditor_total: Decimal,
    creditor_bucket_total: Decimal,
    supplier_debtor_total: Decimal,
    supplier_creditor_total: Decimal,
) -> None:
    checks = {
        "Debtor ERP aging buckets": (debtor_total, debtor_bucket_total),
        "Creditor aging buckets": (creditor_total, creditor_bucket_total),
        "Supplier debtor totals": (debtor_total, supplier_debtor_total),
        "Supplier creditor totals": (creditor_total, supplier_creditor_total),
    }
    for label, (expected, actual) in checks.items():
        if abs(expected - actual) > Decimal("0.01"):
            raise CreditorAgingError(
                f"{label} do not reconcile: source total {expected} versus bucket/supplier total {actual}."
            )


def generate_creditor_aging_report(
    creditor_netting_path: Path,
    erp_debtor_path: Path,
    output_path: Path,
) -> Dict[str, Any]:
    """Generate the creditor detail, supplier net aging, and reconciliation workbook."""
    creditor_rows, creditor_currencies = _read_creditor_transactions(creditor_netting_path)
    debtors, report_date, debtor_currency = _read_erp_debtors(erp_debtor_path)

    if not creditor_rows:
        raise CreditorAgingError("The creditor netting workbook contains no payable transactions.")
    if not debtors:
        raise CreditorAgingError("The debtor ERP workbook contains no transaction rows.")
    if len(creditor_currencies) > 1:
        raise CreditorAgingError(
            f"Creditor netting workbook contains multiple currencies: {', '.join(creditor_currencies)}."
        )
    creditor_currency = creditor_currencies[0] if creditor_currencies else None
    if creditor_currency and debtor_currency and creditor_currency != debtor_currency:
        raise CreditorAgingError(
            f"Workbook currencies do not match ({debtor_currency} versus {creditor_currency})."
        )
    currency = debtor_currency or creditor_currency
    if not currency:
        raise CreditorAgingError("Could not determine a single report currency from the uploaded workbooks.")

    for transaction in creditor_rows:
        transaction["days_past_due"] = (report_date - transaction["due_date"]).days
        transaction["bucket_index"] = _bucket_index(transaction["days_past_due"])
        transaction["buckets"] = [Decimal("0") for _ in AGING_BUCKETS]
        transaction["buckets"][transaction["bucket_index"]] = transaction["creditor_balance"]

    debtor_by_supplier: Dict[str, Dict[str, Any]] = {}
    for transaction in debtors:
        key = transaction["supplier_key"]
        if not key:
            raise CreditorAgingError(f"Could not normalize debtor supplier name {transaction['supplier']!r}.")
        aggregate = debtor_by_supplier.setdefault(
            key,
            {
                "name": transaction["supplier"],
                "balance": Decimal("0"),
                "buckets": [Decimal("0") for _ in AGING_BUCKETS],
            },
        )
        aggregate["balance"] += transaction["debtor_balance"]
        for index, amount in enumerate(transaction["buckets"]):
            aggregate["buckets"][index] += amount

    creditor_by_supplier: Dict[str, Dict[str, Any]] = {}
    for transaction in creditor_rows:
        key = transaction["supplier_key"]
        if not key:
            raise CreditorAgingError(f"Could not normalize creditor supplier name {transaction['supplier']!r}.")
        aggregate = creditor_by_supplier.setdefault(
            key,
            {
                "name": transaction["supplier"],
                "balance": Decimal("0"),
                "buckets": [Decimal("0") for _ in AGING_BUCKETS],
            },
        )
        aggregate["balance"] += transaction["creditor_balance"]
        for index, amount in enumerate(transaction["buckets"]):
            aggregate["buckets"][index] += amount

    debtor_total = sum((row["debtor_balance"] for row in debtors), Decimal("0"))
    debtor_bucket_total = sum(
        (sum(row["buckets"], Decimal("0")) for row in debtors), Decimal("0")
    )
    creditor_total = sum((row["creditor_balance"] for row in creditor_rows), Decimal("0"))
    creditor_bucket_total = sum(
        (sum(row["buckets"], Decimal("0")) for row in creditor_rows), Decimal("0")
    )
    supplier_debtor_total = sum(
        (row["balance"] for row in debtor_by_supplier.values()), Decimal("0")
    )
    supplier_creditor_total = sum(
        (row["balance"] for row in creditor_by_supplier.values()), Decimal("0")
    )
    _validate_reconciliation(
        debtor_total,
        debtor_bucket_total,
        creditor_total,
        creditor_bucket_total,
        supplier_debtor_total,
        supplier_creditor_total,
    )

    fuzzy_matches = _unique_fuzzy_matches(debtor_by_supplier, creditor_by_supplier)
    creditor_groups = {
        creditor_key: debtor_key
        for debtor_key, (creditor_key, _) in fuzzy_matches.items()
    }
    grouped_creditors = {
        creditor_groups.get(key, key): value
        for key, value in creditor_by_supplier.items()
    }
    supplier_keys = sorted(set(debtor_by_supplier) | set(grouped_creditors))
    supplier_rows = []
    mapping_rows = []
    debtor_names = [item["name"] for item in debtor_by_supplier.values()]
    creditor_names = [item["name"] for item in creditor_by_supplier.values()]
    for key in supplier_keys:
        debtor = debtor_by_supplier.get(key)
        creditor = grouped_creditors.get(key)
        fuzzy_match = key in fuzzy_matches
        debtor_name = debtor["name"] if debtor else ""
        creditor_name = creditor["name"] if creditor else ""
        supplier_name = debtor_name or creditor_name
        debtor_balance = debtor["balance"] if debtor else Decimal("0")
        creditor_balance = creditor["balance"] if creditor else Decimal("0")
        net_balance = debtor_balance - creditor_balance
        debtor_buckets = debtor["buckets"] if debtor else [Decimal("0") for _ in AGING_BUCKETS]
        creditor_buckets = creditor["buckets"] if creditor else [Decimal("0") for _ in AGING_BUCKETS]
        net_buckets = [
            debtor_buckets[index] - creditor_buckets[index]
            for index in range(len(AGING_BUCKETS))
        ]
        supplier_rows.append(
            [
                supplier_name,
                report_date,
                debtor_name,
                creditor_name,
                "Matched by high-similarity name - review" if fuzzy_match else (
                    "Matched by normalized name" if debtor and creditor else (
                    "Debtor only - zero creditor" if debtor else "Creditor only - zero debtor"
                    )
                ),
                currency,
                debtor_balance,
                creditor_balance,
                net_balance,
                *debtor_buckets,
                *creditor_buckets,
                *net_buckets,
            ]
        )
        suggested_name = ""
        similarity = None
        if debtor and creditor:
            if fuzzy_match:
                match_method = "Unique high-similarity name"
                match_status = "Matched - review mapping"
                similarity = fuzzy_matches[key][1]
                suggested_name = creditor_name
            else:
                match_method = "Normalized name"
                match_status = "Matched"
        elif debtor:
            match_method = "Unmatched"
            match_status = "Debtor only"
            suggested_name, similarity = _suggest_supplier_match(debtor_name, creditor_names)
        else:
            match_method = "Unmatched"
            match_status = "Creditor only"
            suggested_name, similarity = _suggest_supplier_match(creditor_name, debtor_names)
        mapping_rows.append(
            [
                debtor_name,
                creditor_name,
                key,
                match_method,
                match_status,
                suggested_name,
                similarity,
            ]
        )

    bucket_count = len(AGING_BUCKETS)
    supplier_debtor_check = sum((row[6] for row in supplier_rows), Decimal("0"))
    supplier_creditor_check = sum((row[7] for row in supplier_rows), Decimal("0"))
    supplier_net_total = sum((row[8] for row in supplier_rows), Decimal("0"))
    supplier_net_bucket_total = sum(
        (row[9 + 2 * bucket_count + index] for row in supplier_rows for index in range(bucket_count)),
        Decimal("0"),
    )
    if (
        abs(supplier_debtor_check - debtor_total) > Decimal("0.01")
        or abs(supplier_creditor_check - creditor_total) > Decimal("0.01")
        or abs(supplier_net_total - (debtor_total - creditor_total)) > Decimal("0.01")
        or abs(supplier_net_bucket_total - supplier_net_total) > Decimal("0.01")
    ):
        raise CreditorAgingError("Supplier-wise net balances do not reconcile to the source report totals.")

    detail_headers = [
        "Supplier Name",
        "Report Date",
        "Source Name",
        "Transaction Number",
        "Transaction Type",
        "Due Date",
        "Currency",
        "Entered Due Remaining (Q)",
        "Creditor Balance (-Q)",
        "Days Past Due",
        "Aging Bucket",
        *[name for name, _, _ in AGING_BUCKETS],
    ]
    detail_rows = []
    for transaction in creditor_rows:
        detail_rows.append(
            [
                transaction["supplier"],
                report_date,
                transaction["source_name"],
                transaction["transaction_number"],
                transaction["transaction_type"],
                transaction["due_date"],
                transaction["currency"] or currency,
                transaction["entered_due_remaining"],
                transaction["creditor_balance"],
                transaction["days_past_due"],
                AGING_BUCKETS[transaction["bucket_index"]][0],
                *transaction["buckets"],
            ]
        )
    detail_rows.append(
        [
            "Total",
            report_date,
            "",
            "",
            "",
            "",
            currency,
            sum((row["entered_due_remaining"] for row in creditor_rows), Decimal("0")),
            creditor_total,
            "",
            "",
            *[
                sum((row["buckets"][index] for row in creditor_rows), Decimal("0"))
                for index in range(len(AGING_BUCKETS))
            ],
        ]
    )

    supplier_headers = [
        "Supplier",
        "Report Date",
        "Debtor Supplier Name",
        "Creditor Supplier Name",
        "Match Status",
        "Currency",
        "Debtor Balance",
        "Creditor Balance",
        "Net Balance",
        *[f"Debtor {name}" for name, _, _ in AGING_BUCKETS],
        *[f"Creditor {name}" for name, _, _ in AGING_BUCKETS],
        *[f"Net {name}" for name, _, _ in AGING_BUCKETS],
    ]
    supplier_rows.append(
        [
            "Total",
            report_date,
            "",
            "",
            "",
            currency,
            debtor_total,
            creditor_total,
            debtor_total - creditor_total,
            *[
                sum((row["buckets"][index] for row in debtors), Decimal("0"))
                for index in range(bucket_count)
            ],
            *[
                sum((row["buckets"][index] for row in creditor_rows), Decimal("0"))
                for index in range(bucket_count)
            ],
            *[
                sum((row[9 + index] for row in supplier_rows[:-1]), Decimal("0"))
                - sum((row[9 + bucket_count + index] for row in supplier_rows[:-1]), Decimal("0"))
                for index in range(bucket_count)
            ],
        ]
    )

    reconciliation_rows = [
        ["Report Date", report_date],
        ["Currency", currency],
        ["Debtor Balance", debtor_total],
        ["Debtor ERP Aging Bucket Total", debtor_bucket_total],
        ["Debtor Bucket Difference", debtor_total - debtor_bucket_total],
        ["Creditor Entered Due Remaining (Q)", sum((row["entered_due_remaining"] for row in creditor_rows), Decimal("0"))],
        ["Creditor Balance (-Q)", creditor_total],
        ["Creditor Aging Bucket Total", creditor_bucket_total],
        ["Creditor Bucket Difference", creditor_total - creditor_bucket_total],
        ["Supplier-wise Debtor Total", supplier_debtor_check],
        ["Supplier-wise Creditor Total", supplier_creditor_check],
        ["Net Balance (Debtor - Creditor)", debtor_total - creditor_total],
        ["Supplier-wise Net Total", supplier_net_total],
        ["Net Reconciliation Difference", debtor_total - creditor_total - supplier_net_total],
        [],
        ["Supplier Mapping Review"],
        [
            "Debtor Supplier Name",
            "Creditor Supplier Name",
            "Normalized Supplier Key",
            "Matching Method",
            "Match Status",
            "Suggested Counterpart (review only)",
            "Name Similarity",
        ],
        *mapping_rows,
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    _add_worksheet(
        workbook,
        "Creditor Aging Details",
        detail_headers,
        detail_rows,
        date_columns=(2, 6),
        money_columns=tuple([8, 9, *range(12, 12 + bucket_count)]),
    )
    _add_worksheet(
        workbook,
        "Supplier-wise Net Aging",
        supplier_headers,
        supplier_rows,
        date_columns=(2,),
        money_columns=tuple(range(7, len(supplier_headers) + 1)),
    )
    reconciliation_sheet = workbook.create_sheet("Reconciliation")
    reconciliation_sheet.append(["Reconciliation Item", "Value"])
    for cell in reconciliation_sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    for row in reconciliation_rows:
        reconciliation_sheet.append(row)
    reconciliation_sheet["B2"].number_format = DATE_FORMAT
    for row_number in range(4, 17):
        reconciliation_sheet.cell(row_number, 2).number_format = MONEY_FORMAT
    mapping_header_row = 18
    for cell in reconciliation_sheet[mapping_header_row]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row_number in range(mapping_header_row + 1, reconciliation_sheet.max_row + 1):
        reconciliation_sheet.cell(row_number, 7).number_format = "0.0%"
    reconciliation_sheet.freeze_panes = f"A{mapping_header_row + 1}"
    reconciliation_sheet.auto_filter.ref = (
        f"A{mapping_header_row}:G{reconciliation_sheet.max_row}"
    )
    for column_cells in reconciliation_sheet.columns:
        column_number = column_cells[0].column
        max_width = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=10,
        )
        reconciliation_sheet.column_dimensions[get_column_letter(column_number)].width = min(max(max_width + 2, 14), 40)
    workbook.save(str(output_path))
    workbook.close()

    logger.info(
        "Generated supplier net aging report for %s: debtor=%s creditor=%s net=%s",
        report_date,
        debtor_total,
        creditor_total,
        debtor_total - creditor_total,
    )
    return {
        "report_date": report_date,
        "currency": currency,
        "debtor_total": debtor_total,
        "creditor_total": creditor_total,
        "net_total": debtor_total - creditor_total,
        "supplier_count": len(supplier_keys),
        "output_path": output_path,
    }
