"""Generate monthly accrual journal workbooks from finance source workbooks."""

from collections import Counter, defaultdict
from copy import copy
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import openpyxl


class AccrualReportInputError(ValueError):
    """Raised when an accrual source workbook is missing required data."""


def _period_date(period: str) -> date:
    match = re.fullmatch(r"([A-Za-z]{3})-(\d{2}|\d{4})", period.strip())
    if not match:
        raise AccrualReportInputError("Period must use the format Mon-YY (for example, Sep-26).")
    try:
        month = datetime.strptime(match.group(1).title(), "%b").month
        year = int(match.group(2))
        if year < 100:
            year += 2000
        return date(year, month, 1)
    except ValueError as exc:
        raise AccrualReportInputError(f"Invalid reporting period '{period}'.") from exc


def _period_token(period: str) -> str:
    value = _period_date(period)
    return value.strftime("%b%y").upper()


def _normalise_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number


def _is_number(value: Any) -> bool:
    return _number(value) is not None


def _sheet_has_header(ws, expected: str) -> bool:
    target = _normalise_text(expected)
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 8), values_only=True):
        if target in {_normalise_text(value) for value in row if value is not None}:
            return True
    return False


def _find_journal_sheet(workbook):
    preferred = workbook["Entry Origain (4)"] if "Entry Origain (4)" in workbook.sheetnames else None
    if preferred is not None:
        return preferred
    for ws in workbook.worksheets:
        if _sheet_has_header(ws, "Natural A/C") and _sheet_has_header(ws, "Description"):
            return ws
    raise AccrualReportInputError("Prior accrual workbook is missing the journal entry worksheet.")


def _account(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text if text.isdigit() else None


def _read_journal_entries(prior_path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    try:
        workbook = openpyxl.load_workbook(prior_path, data_only=True, read_only=True)
    except Exception as exc:
        raise AccrualReportInputError(f"Could not open prior accrual workbook: {exc}") from exc

    try:
        ws = _find_journal_sheet(workbook)
        entries = []
        account_dimensions: Dict[str, List[Tuple[Any, ...]]] = defaultdict(list)
        credit_dimensions: List[Tuple[Any, ...]] = []
        for row in ws.iter_rows(min_row=3, max_col=max(12, ws.max_column), values_only=True):
            values = list(row[:12])
            values += [None] * (12 - len(values))
            account = _account(values[5])
            debit, credit, description = values[9], values[10], values[11]
            if not description or (not _is_number(debit) and not _is_number(credit)):
                continue
            line = {
                "values": values,
                "account": account,
                "debit": _number(debit),
                "credit": _number(credit),
                "description": str(description).strip(),
            }
            entries.append(line)
            dimensions = tuple(values[:9])
            if account == "225511" and _number(credit) is not None:
                credit_dimensions.append(dimensions)
            elif account and account != "225511" and _number(debit) is not None:
                account_dimensions[account].append(dimensions)
        if not entries:
            raise AccrualReportInputError("Prior accrual journal worksheet contains no journal lines.")
        return entries, account_dimensions, {
            "journal_sheet": ws.title,
            "credit_dimensions": credit_dimensions,
        }
    finally:
        workbook.close()


def _read_account_analysis(path: Path) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
    try:
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:
        raise AccrualReportInputError(f"Could not open account analysis workbook: {exc}") from exc

    activity: Dict[str, Dict[str, float]] = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
    rows: List[Dict[str, Any]] = []
    try:
        for ws in workbook.worksheets:
            header_row = None
            columns: Dict[str, int] = {}
            account_dimensions = _read_account_dimensions(ws)
            for row_number, row in enumerate(
                ws.iter_rows(min_row=1, max_row=min(ws.max_row, 35), values_only=True), 1
            ):
                names = {_normalise_text(value): index for index, value in enumerate(row) if value is not None}
                if {"category", "linedescription", "debit", "credit"}.issubset(names):
                    header_row = row_number
                    columns = {
                        "category": names["category"],
                        "line_description": names["linedescription"],
                        "debit": names["debit"],
                        "credit": names["credit"],
                    }
                    break
            if header_row is None:
                continue
            natural_account = _account(ws.title)
            for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
                description = row[columns["line_description"]] if columns["line_description"] < len(row) else None
                category = row[columns["category"]] if columns["category"] < len(row) else None
                if not description:
                    continue
                debit_value = row[columns["debit"]] if columns["debit"] < len(row) else None
                credit_value = row[columns["credit"]] if columns["credit"] < len(row) else None
                debit = _number(debit_value) or 0.0
                credit = _number(credit_value) or 0.0
                category_text = str(category or "").strip()
                record = {
                    "account": natural_account,
                    "dimensions": account_dimensions,
                    "category": category_text,
                    "description": str(description).strip(),
                    "debit": debit,
                    "credit": credit,
                }
                rows.append(record)
                if _normalise_text(category_text) == "accrual":
                    totals = activity[_normalise_text(description)]
                    totals["debit"] += debit
                    totals["credit"] += credit
        return activity, rows
    finally:
        workbook.close()


def _read_account_dimensions(ws) -> Optional[Tuple[Any, ...]]:
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 30), values_only=True):
        for index, value in enumerate(row):
            if _normalise_text(value) != "account" or index + 1 >= len(row):
                continue
            flexfield = row[index + 1]
            if not isinstance(flexfield, str):
                continue
            segments = tuple(part.strip() for part in flexfield.split("."))
            if len(segments) >= 9 and all(part.isdigit() for part in segments[:9]):
                return segments[:9]
    return None


def _get_period_cell(ws, period: str) -> Optional[int]:
    wanted = _normalise_text(period)
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 3), values_only=True):
        for index, value in enumerate(row):
            if value is not None and _normalise_text(value) == wanted:
                return index
    return None


def _cell_by_header(headers: Sequence[Any], name: str, fallback: int) -> int:
    wanted = _normalise_text(name)
    for index, value in enumerate(headers):
        if value is not None and _normalise_text(value) == wanted:
            return index
    return fallback


def _month_range(period: str) -> Tuple[date, date]:
    first = _period_date(period)
    if first.month == 12:
        next_month = date(first.year + 1, 1, 1)
    else:
        next_month = date(first.year, first.month + 1, 1)
    return first, date.fromordinal(next_month.toordinal() - 1)


def _parse_cell_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _format_amount(value: Any, number_format: Optional[str] = None) -> str:
    amount = _number(value)
    if amount is None:
        return str(value)
    if number_format and ("0.00" in number_format or "#,##0.00" in number_format):
        return f"{amount:.2f}"
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def _prefix_from_history(
    account: str,
    vendor: str,
    reference: str,
    prior_entries: Iterable[Dict[str, Any]],
) -> Optional[str]:
    vendor_key = _normalise_text(vendor)
    reference_parts = [
        _normalise_text(part)
        for part in re.split(r"[^A-Za-z0-9]+", reference)
        if part
    ]
    candidates: List[Tuple[float, str]] = []
    for entry in prior_entries:
        if entry["account"] != account or "-$" not in entry["description"]:
            continue
        prefix = entry["description"].split("-$", 1)[0].strip()
        prefix_key = _normalise_text(prefix)
        score = SequenceMatcher(None, vendor_key, prefix_key).ratio()
        if vendor_key and (vendor_key in prefix_key or prefix_key in vendor_key):
            score += 0.4
        if any(
            part in prefix_key and (len(part) >= 4 or (part.isdigit() and len(part) >= 3))
            for part in reference_parts
        ):
            score += 0.8
        candidates.append((score, prefix))
    if not candidates:
        return None
    score, prefix = max(candidates, key=lambda candidate: candidate[0])
    return prefix if score >= 0.7 else None


def _description_amount(description: str, token: str) -> Optional[float]:
    period_match = re.search(re.escape(token), description, flags=re.IGNORECASE)
    if period_match is None:
        return None
    prefix = description[: period_match.start()]
    amounts = re.findall(r"\d[\d,]*(?:\.\d+)?", prefix)
    return _number(amounts[-1]) if amounts else None


def _description_amount_before_date(description: str) -> Optional[float]:
    date_match = re.search(r"\d{1,2}\.\d{1,2}\.\d{2,4}", description)
    if date_match is None:
        return None
    amounts = re.findall(r"\d[\d,]*(?:\.\d+)?", description[: date_match.start()])
    return _number(amounts[-1]) if amounts else None


def _description_label(description: str, token: str) -> str:
    period_match = re.search(re.escape(token), description, flags=re.IGNORECASE)
    if period_match is None:
        period_match = re.search(r"\d{1,2}\.\d{1,2}\.\d{2,4}", description)
    if period_match is None:
        return description
    prefix = description[: period_match.start()]
    amounts = list(re.finditer(r"\d[\d,]*(?:\.\d+)?", prefix))
    if not amounts:
        return prefix.strip(" -$")
    return prefix[: amounts[-1].start()].strip(" -$")


def _vendor_match_score(vendor: str, description: str, token: str) -> float:
    label = _description_label(description, token)
    vendor_key = _normalise_text(vendor)
    label_key = _normalise_text(label)
    if not vendor_key or not label_key:
        return 0.0
    if vendor_key in label_key or label_key in vendor_key:
        return 1.0
    return SequenceMatcher(None, vendor_key, label_key).ratio()


def _is_month_description(description: str, period: str) -> bool:
    if _period_in_description(description, _period_token(period)):
        return True
    expected_month = _period_date(period)
    for date_text in re.findall(r"\d{1,2}\.\d{1,2}\.\d{2,4}", description):
        parsed_date = _parse_cell_date(date_text)
        if parsed_date and parsed_date.year == expected_month.year and parsed_date.month == expected_month.month:
            return True
    return False


def _is_future_period_description(description: str, period: str) -> bool:
    current_period = _period_date(period)
    for date_text in re.findall(r"\d{1,2}\.\d{1,2}\.\d{2,4}", description):
        parsed_date = _parse_cell_date(date_text)
        if parsed_date and (parsed_date.year, parsed_date.month) > (
            current_period.year,
            current_period.month,
        ):
            return True

    month_names = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    for match in re.finditer(r"([A-Za-z]{3,9})[^A-Za-z0-9]{0,4}(\d{2}|\d{4})", description):
        month = month_names.get(match.group(1)[:3].lower())
        if not month:
            continue
        year = int(match.group(2))
        if year < 100:
            year += 2000
        if (year, month) > (current_period.year, current_period.month):
            return True
    return False


def _amount_subset(
    rows: Sequence[Dict[str, Any]],
    target: float,
) -> Optional[List[int]]:
    target_cents = round(target * 100)
    cents = [round(row["amount"] * 100) for row in rows]
    exact_match = next(
        (index for index, amount in enumerate(cents) if amount == target_cents),
        None,
    )
    if exact_match is not None:
        return [exact_match]

    totals: Dict[int, List[int]] = {0: []}
    for index, amount in enumerate(cents):
        for subtotal, selected in list(totals.items()):
            new_total = subtotal + amount
            if new_total <= target_cents and new_total not in totals:
                totals[new_total] = selected + [index]
        if target_cents in totals:
            return totals[target_cents]
    return None


def _current_accrual_entries(
    payment_rows: Sequence[Dict[str, Any]],
    gl_rows: Sequence[Dict[str, Any]],
    period: str,
    account_dimensions: Dict[str, List[Tuple[Any, ...]]],
    credit_dimensions: List[Tuple[Any, ...]],
    account_analysis_dimensions: Dict[str, List[Tuple[Any, ...]]],
) -> Tuple[List[Dict[str, Any]], set]:
    token = _period_token(period)
    templates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in gl_rows:
        if (
            row["account"]
            and _normalise_text(row["category"]) == "accrual"
            and _is_month_description(row["description"], period)
        ):
            templates[row["account"]].append(row)

    generated: List[Dict[str, Any]] = []
    matched_payment_ids = set()
    for account, account_templates in templates.items():
        remaining = [
            row
            for row in payment_rows
            if row["account"] == account
        ]
        for template in account_templates:
            amount = _description_amount(template["description"], token)
            candidates = [
                row
                for row in remaining
                if _vendor_match_score(row["vendor"], template["description"], token) >= 0.5
            ]
            if amount is None:
                amount = _description_amount_before_date(template["description"])
                if amount is None:
                    continue
                partial_candidates = [
                    row
                    for row in candidates
                    if row["period_is_numeric"]
                    and _number(row["original_amount"]) is not None
                    and abs(_number(row["original_amount"]) - amount) < 0.01
                ]
                if not partial_candidates:
                    continue
                matched_rows = [partial_candidates[0]]
                entry_amount = round(matched_rows[0]["amount"], 2)
            else:
                numeric_candidates = [
                    row for row in candidates if row["period_is_numeric"]
                ]
                selected = _amount_subset(numeric_candidates, amount)
                if selected is not None:
                    matched_rows = [numeric_candidates[index] for index in selected]
                    entry_amount = amount
                else:
                    non_actual_candidates = [
                        row
                        for row in candidates
                        if not row["period_is_numeric"]
                        and _normalise_text(row["period_status"]) != "actual"
                    ]
                    if not non_actual_candidates:
                        continue
                    matched_rows = [non_actual_candidates[0]]
                    entry_amount = amount
            matched_ids = {id(row) for row in matched_rows}
            matched_payment_ids.update(matched_ids)
            remaining = [row for row in remaining if id(row) not in matched_ids]
            debit_dimensions, credit_dims = _entry_dimensions(
                account,
                account_dimensions,
                credit_dimensions,
                account_analysis_dimensions,
            )
            generated.append(
                _make_journal_pair(
                    debit_dimensions,
                    credit_dims,
                    account,
                    entry_amount,
                    template["description"],
                )
            )
    return generated, matched_payment_ids


def _entry_dimensions(
    account: str,
    account_dimensions: Dict[str, List[Tuple[Any, ...]]],
    credit_dimensions: List[Tuple[Any, ...]],
    account_analysis_dimensions: Optional[Dict[str, List[Tuple[Any, ...]]]] = None,
) -> Tuple[Tuple[Any, ...], Tuple[Any, ...]]:
    debit_candidates = account_dimensions.get(account, [])
    if not debit_candidates and account_analysis_dimensions:
        debit_candidates = account_analysis_dimensions.get(account, [])
    if not debit_candidates:
        raise AccrualReportInputError(
            f"No prior journal dimensions are available for natural account {account}."
        )
    credit_candidates = credit_dimensions
    if not credit_candidates:
        raise AccrualReportInputError("Prior accrual workbook has no 225511 liability dimensions.")
    debit_dims = Counter(debit_candidates).most_common(1)[0][0]
    credit_dims = Counter(credit_candidates).most_common(1)[0][0]
    return debit_dims, credit_dims


def _make_journal_pair(
    debit_dimensions: Sequence[Any],
    credit_dimensions: Sequence[Any],
    account: str,
    amount: float,
    description: str,
) -> Dict[str, Any]:
    debit = list(debit_dimensions[:9])
    credit = list(credit_dimensions[:9])
    debit[5] = int(account) if account.isdigit() else account
    credit[5] = 225511
    debit += [None] * (9 - len(debit))
    credit += [None] * (9 - len(credit))
    debit.extend([amount, None, description])
    credit.extend([None, amount, description])
    return {"lines": [debit, credit], "description": description, "account": account}


def _make_reversal_pair(
    account_dimensions: Sequence[Any],
    credit_dimensions: Sequence[Any],
    account: str,
    amount: float,
    description: str,
) -> Dict[str, Any]:
    debit = list(credit_dimensions[:9])
    credit = list(account_dimensions[:9])
    debit[5] = 225511
    credit[5] = int(account) if account.isdigit() else account
    debit.extend([amount, None, description])
    credit.extend([None, amount, description])
    return {"lines": [debit, credit], "description": description, "account": "225511"}


def _is_current_period_description(description: str, account: Optional[str], period: str) -> bool:
    token = _period_token(period)
    if _period_in_description(description, token):
        return True
    if account != "225511":
        return False

    current_month = _period_date(period)
    normalized = _normalise_text(description)
    month = current_month.strftime("%b").lower()
    year = current_month.strftime("%y")
    quarter = (current_month.month - 1) // 3 + 1
    if f"{quarter}q{year}" in normalized and month in normalized:
        return True
    for date_text in re.findall(r"\d{1,2}\.\d{1,2}\.\d{2,4}", description):
        parsed_date = _parse_cell_date(date_text)
        if parsed_date and parsed_date.year == current_month.year and parsed_date.month == current_month.month:
            return True
    return False


def _current_payment_entries(
    payment_path: Path,
    period: str,
    prior_entries: List[Dict[str, Any]],
    account_dimensions: Dict[str, List[Tuple[Any, ...]]],
    credit_dimensions: List[Tuple[Any, ...]],
    gl_rows: List[Dict[str, Any]],
    account_analysis_dimensions: Dict[str, List[Tuple[Any, ...]]],
) -> List[Dict[str, Any]]:
    try:
        workbook = openpyxl.load_workbook(payment_path, data_only=True, read_only=True)
    except Exception as exc:
        raise AccrualReportInputError(f"Could not open payment details workbook: {exc}") from exc

    first_day, last_day = _month_range(period)
    payment_rows = []
    try:
        for ws in workbook.worksheets:
            account = _account(ws.title)
            if not account:
                continue
            period_column = _get_period_cell(ws, period)
            if period_column is None:
                continue
            headers = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
            vendor_column = _cell_by_header(headers, "Country", 3)
            reference_column = 4
            amount_column = _cell_by_header(headers, "MRC", 7)
            start_column = _cell_by_header(headers, "DSP/Rene", 0)
            end_column = _cell_by_header(headers, "DST", 1)
            for row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
                month_amount = row[period_column] if period_column < len(row) else None
                amount = _number(month_amount)
                period_is_numeric = amount is not None
                if amount is None and not str(month_amount or "").strip():
                    continue
                vendor = str(row[vendor_column] if vendor_column < len(row) else "").strip()
                if not vendor:
                    continue
                reference = str(row[reference_column] if reference_column < len(row) else "").strip()
                original_amount = row[amount_column] if amount_column < len(row) else month_amount
                if amount is None:
                    amount = _number(original_amount)
                if amount is None and not period_is_numeric:
                    amount = 0.0
                if amount is None or (amount == 0 and period_is_numeric):
                    continue
                number_format = ws.cell(row_number, amount_column + 1).number_format
                payment_rows.append(
                    {
                        "account": account,
                        "vendor": vendor,
                        "reference": reference,
                        "amount": amount,
                        "original_amount": original_amount,
                        "number_format": number_format,
                        "period_is_numeric": period_is_numeric,
                        "period_status": str(month_amount or "").strip(),
                        "start": _parse_cell_date(
                            row[start_column] if start_column < len(row) else None
                        ),
                        "end": _parse_cell_date(
                            row[end_column] if end_column < len(row) else None
                        ),
                    }
                )

        entries, matched_payment_ids = _current_accrual_entries(
            payment_rows,
            gl_rows,
            period,
            account_dimensions,
            credit_dimensions,
            account_analysis_dimensions,
        )
        for payment_row in payment_rows:
            if id(payment_row) in matched_payment_ids or not payment_row["period_is_numeric"]:
                continue
            account = payment_row["account"]
            vendor = payment_row["vendor"]
            reference = payment_row["reference"]
            amount = payment_row["amount"]
            original_amount = payment_row["original_amount"]
            display_prefix = _prefix_from_history(account, vendor, reference, prior_entries)
            if not display_prefix:
                display_prefix = vendor
            display_amount = _format_amount(original_amount, payment_row["number_format"])
            description = f"{display_prefix}-${display_amount}-{_period_token(period)}"

            active_start = max(payment_row["start"], first_day) if payment_row["start"] else None
            active_end = min(payment_row["end"], last_day) if payment_row["end"] else None
            if active_start and active_end and active_start <= active_end:
                original = _number(original_amount)
                if original and abs(amount - original) > 0.01:
                    amount = round(amount, 2)
                    description = (
                        f"{display_prefix}-${display_amount}-"
                        f"{active_start:%d.%m.%y} to {active_end:%d.%m.%y}"
                    )

            debit_dims, credit_dims = _entry_dimensions(
                account,
                account_dimensions,
                credit_dimensions,
                account_analysis_dimensions,
            )
            entries.append(
                _make_journal_pair(
                    debit_dims,
                    credit_dims,
                    account,
                    amount,
                    description,
                )
            )
        return entries
    finally:
        workbook.close()


def _period_in_description(description: str, token: str) -> bool:
    normalised = _normalise_text(description)
    return token.lower() in normalised


def _quarterly_current_entries(
    prior_entries: List[Dict[str, Any]],
    current_period: str,
    account_dimensions: Dict[str, List[Tuple[Any, ...]]],
    credit_dimensions: List[Tuple[Any, ...]],
    activity: Dict[str, Dict[str, float]],
) -> List[Dict[str, Any]]:
    current_token = _period_token(current_period)
    current_date = _period_date(current_period)
    previous_date = date(current_date.year - (1 if current_date.month == 1 else 0), 12 if current_date.month == 1 else current_date.month - 1, 1)
    previous_token = previous_date.strftime("%b%y").upper()
    by_description: Dict[str, Dict[str, Any]] = {}
    for entry in prior_entries:
        by_description.setdefault(entry["description"], entry)

    generated = []
    for entry in by_description.values():
        description = entry["description"]
        if entry["account"] != "521302" or "based on 2q" not in description.lower():
            continue
        if not _period_in_description(description, previous_token):
            continue
        balances = activity.get(_normalise_text(description), {})
        if balances.get("credit", 0) > 0 and balances.get("debit", 0) == 0:
            continue
        refreshed_description = re.sub(
            re.escape(previous_token),
            current_token,
            description,
            flags=re.IGNORECASE,
        )
        amount = entry["debit"]
        if amount is None:
            continue
        debit_dims, credit_dims = _entry_dimensions(
            "521302", account_dimensions, credit_dimensions
        )
        generated.append(
            _make_journal_pair(
                debit_dims,
                credit_dims,
                "521302",
                amount,
                refreshed_description,
            )
        )
    return generated


def _prior_support_provisions(
    prior_accrual_path: Path,
    period: str,
    prior_entries: List[Dict[str, Any]],
    account_dimensions: Dict[str, List[Tuple[Any, ...]]],
    credit_dimensions: List[Tuple[Any, ...]],
) -> List[Dict[str, Any]]:
    current_date = _period_date(period)
    previous_date = date(
        current_date.year - (1 if current_date.month == 1 else 0),
        12 if current_date.month == 1 else current_date.month - 1,
        1,
    )
    prev_month_label = previous_date.strftime("%b %Y")
    target_desc = f"NTRA Prov {prev_month_label}"

    prior_descriptions = {_normalise_text(e["description"]) for e in prior_entries}
    if _normalise_text(target_desc) in prior_descriptions:
        return []

    found_amount = None
    found_cost_centre = None
    try:
        workbook = openpyxl.load_workbook(prior_accrual_path, data_only=True, read_only=True)
    except Exception:
        workbook = None

    if workbook is not None:
        try:
            candidate_sheets = []
            if "Entry Origain (7)" in workbook.sheetnames:
                candidate_sheets.append("Entry Origain (7)")
            candidate_sheets.extend(
                [s for s in reversed(workbook.sheetnames) if s != "Entry Origain (4)" and s not in candidate_sheets]
            )
            for sheet_name in candidate_sheets:
                ws = workbook[sheet_name]
                for row in ws.iter_rows(min_row=1, max_col=12, values_only=True):
                    for idx, val in enumerate(row):
                        if _account(val) == "521282":
                            for v in row[idx + 1:]:
                                num = _number(v)
                                if num is not None and num > 0:
                                    if num == 100000 or (num < 500000 and num != 6186200):
                                        found_amount = num
                                        if idx > 0 and str(row[1]).isdigit():
                                            found_cost_centre = str(row[1])
                                        break
                            if found_amount is not None:
                                break
                    if found_amount is not None:
                        break
                if found_amount is not None:
                    break
        finally:
            workbook.close()

    if found_amount is None:
        found_amount = 100000.0

    debit_dims, credit_dims = _entry_dimensions(
        "521282", account_dimensions, credit_dimensions
    )
    if found_cost_centre:
        debit_dims = list(debit_dims)
        debit_dims[1] = found_cost_centre
        debit_dims = tuple(debit_dims)

    return [
        _make_journal_pair(
            debit_dims,
            credit_dims,
            "521282",
            found_amount,
            target_desc,
        )
    ]


def _copy_template_styles(ws, source_rows: int, required_rows: int):
    for row_number in range(3, required_rows + 1):
        template_row = 3 if row_number % 2 else 4
        if row_number <= source_rows:
            template_row = row_number if row_number <= 4 else (3 if row_number % 2 else 4)
        for column in range(1, 13):
            source = ws.cell(template_row, column)
            target = ws.cell(row_number, column)
            if source.has_style:
                target._style = copy(source._style)
            if source.number_format:
                target.number_format = source.number_format
            if source.alignment:
                target.alignment = copy(source.alignment)
            if source.font:
                target.font = copy(source.font)
            if source.fill:
                target.fill = copy(source.fill)
            if source.border:
                target.border = copy(source.border)


def generate_accrual_entry_report(
    payment_path: Path,
    prior_accrual_path: Path,
    account_analysis_path: Path,
    period: str,
    output_path: Path,
) -> Dict[str, Any]:
    """Generate an accrual workbook using the selected period and all three source files."""
    token = _period_token(period)
    prior_entries, account_dimensions, journal_info = _read_journal_entries(prior_accrual_path)
    activity, gl_rows = _read_account_analysis(account_analysis_path)
    account_analysis_dimensions: Dict[str, List[Tuple[Any, ...]]] = defaultdict(list)
    for row in gl_rows:
        if row["account"] and row["dimensions"]:
            account_analysis_dimensions[row["account"]].append(row["dimensions"])

    quarterly_descriptions = {
        entry["description"]
        for entry in prior_entries
        if entry["account"] == "521302" and "based on 2q" in entry["description"].lower()
    }
    historic: List[Dict[str, Any]] = []
    for entry in prior_entries:
        description = entry["description"]
        if _is_current_period_description(description, entry["account"], period):
            continue
        if "based on 2q" in description.lower() and description not in quarterly_descriptions:
            continue
        balances = activity.get(_normalise_text(description), {})
        if balances.get("credit", 0) > 0 and balances.get("debit", 0) == 0:
            continue
        historic.append(entry)

    current = _current_payment_entries(
        payment_path,
        period,
        prior_entries,
        account_dimensions,
        journal_info["credit_dimensions"],
        gl_rows,
        account_analysis_dimensions,
    )
    current.extend(
        _quarterly_current_entries(
            prior_entries,
            period,
            account_dimensions,
            journal_info["credit_dimensions"],
            activity,
        )
    )
    existing_current_descriptions = {entry["description"] for entry in current}
    for row in gl_rows:
        if (
            not row["account"]
            or _normalise_text(row["category"]) != "accrual"
            or row["credit"] <= 0
            or not _is_future_period_description(row["description"], period)
            or row["description"] in existing_current_descriptions
        ):
            continue
        debit_dimensions = row["dimensions"]
        if not debit_dimensions:
            candidates = account_dimensions.get(row["account"], [])
            debit_dimensions = candidates[0] if candidates else None
        if not debit_dimensions:
            raise AccrualReportInputError(
                f"Account analysis is missing journal dimensions for natural account {row['account']}."
            )
        if not journal_info["credit_dimensions"]:
            raise AccrualReportInputError("Prior accrual workbook has no 225511 liability dimensions.")
        current.append(
            _make_reversal_pair(
                debit_dimensions,
                journal_info["credit_dimensions"][0],
                row["account"],
                row["credit"],
                row["description"],
            )
        )
        existing_current_descriptions.add(row["description"])

    # Inject provision entries sourced from prior-workbook support sheets
    # (e.g. NTRA Prov Aug 2026 from Entry Origain (7) of the prior file).
    current.extend(
        _prior_support_provisions(
            prior_accrual_path,
            period,
            prior_entries,
            account_dimensions,
            journal_info["credit_dimensions"],
        )
    )

    entry_groups: List[Dict[str, Any]] = []
    by_description: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for line in historic:
        by_description[line["description"]].append(line)
    for description, lines in by_description.items():
        debit_line = next((line for line in lines if line["debit"] is not None), None)
        credit_line = next((line for line in lines if line["credit"] is not None), None)
        if debit_line and credit_line:
            entry_groups.append(
                {
                    "lines": [debit_line["values"], credit_line["values"]],
                    "description": description,
                    "account": debit_line["account"],
                }
            )
    existing_descriptions = {group["description"] for group in entry_groups}
    current_added = 0
    for entry in current:
        if entry["description"] not in existing_descriptions:
            entry_groups.append(entry)
            existing_descriptions.add(entry["description"])
            current_added += 1

    try:
        workbook = openpyxl.load_workbook(prior_accrual_path)
    except Exception as exc:
        raise AccrualReportInputError(f"Could not prepare output from prior workbook: {exc}") from exc
    try:
        keep_names = {"Entry Origain (6)", "Entry Origain (7)", journal_info["journal_sheet"]}
        for ws in list(workbook.worksheets):
            if ws.title not in keep_names:
                workbook.remove(ws)
        journal = workbook[journal_info["journal_sheet"]]
        source_row_count = journal.max_row
        for row in journal.iter_rows(min_row=3, max_row=journal.max_row, max_col=max(journal.max_column, 12)):
            for cell in row:
                cell.value = None
        journal.cell(1, 12).value = token.title()
        _copy_template_styles(journal, source_row_count, 2 + len(entry_groups) * 2)

        output_row = 3
        for entry in entry_groups:
            for line in entry["lines"]:
                for column, value in enumerate(line[:12], 1):
                    journal.cell(output_row, column).value = value
                output_row += 1
        required_rows = output_row - 1
        if journal.max_row > required_rows:
            journal.delete_rows(required_rows + 1, journal.max_row - required_rows)
        # Ensure the journal sheet opens as the active/selected tab in Excel.
        workbook.active = journal
        for ws in workbook.worksheets:
            ws.sheet_view.tabSelected = (ws.title == journal.title)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output_path)
    finally:
        workbook.close()

    return {
        "period": period,
        "filename": output_path.name,
        "journal_entries": len(entry_groups),
        "carried_forward_entries": len(entry_groups) - current_added,
        "current_period_entries": current_added,
        "support_sheets": [name for name in ("Entry Origain (6)", "Entry Origain (7)") if name in keep_names],
    }
