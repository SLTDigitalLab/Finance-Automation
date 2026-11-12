"""Reads the Ratio and Group Balance Sheet tabs for the two-slide board pack."""
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Tuple
from zipfile import BadZipFile

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException


class BoardPackSlidesError(Exception):
    """Raised when the uploaded workbook cannot supply the requested slides."""


@dataclass(frozen=True)
class RatioMetric:
    category: str
    label: str
    value_format: str
    group_current: float
    group_previous: float
    group_variance: float
    company_current: float
    company_previous: float
    company_variance: float
    group_decimals: Tuple[int, int, int]
    company_decimals: Tuple[int, int, int]
    row_height: float = 0.33


@dataclass(frozen=True)
class BalanceSheetRow:
    label: str
    current: float
    previous: float
    is_total: bool = False


@dataclass(frozen=True)
class BoardPackSlidesData:
    period_month: str
    period_year: int
    previous_month: str
    previous_year: int
    current_year: int
    ratio_previous_year: int
    ratios: List[RatioMetric]
    balance_sheet: List[BalanceSheetRow]
    sheets_used: List[str]


_MONTHS: Tuple[str, ...] = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_MONTH_LOOKUP = {
    name.lower(): number
    for number, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"),
            ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
            ("aug", "august"), ("sep", "sept", "september"),
            ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}

_RATIO_SPECS = (
    ("returnonassetsroa", "Profitability Ratios", "Return on Assets (ROA) -%", "percent", 0.30),
    ("returnonequityroe", "Profitability Ratios", "Return on Equity (ROE) -%", "percent", 0.30),
    ("ebitdamargin", "Profitability Ratios", "EBITDA Margin -%", "percent", 0.30),
    (
        "operatingprofitmargin", "Profitability Ratios",
        "Operating Profit Margin - %\n(Dividend received disregarded)", "percent", 0.43,
    ),
    ("netprofitmargin", "Profitability Ratios", "Net Profit Margin - %", "percent", 0.30),
    ("assetturnover", "Efficiency Ratios", "Asset Turnover- No. of times", "number", 0.40),
    ("currentratio", "Liquidity Ratios", "Current Ratio - No. of times", "number", 0.40),
    ("quickratio", "Liquidity Ratios", "Quick Ratio - No. of times", "number", 0.40),
    ("interestcoverageratio", "Coverage Ratios", "Interest Coverage Ratio - No. of times\ninterest", "number", 0.44),
    ("debttoequityratio", "Leverage Ratio", "Debt to Equity Ratio - No. of times", "number", 0.41),
    ("earningspershare", "Market Value Ratios", "Earnings Per Share - (Annualized) Rs", "number", 0.42),
)

_BALANCE_ROWS = (
    ("noncurrentassets", "Non-Current Assets", False),
    ("inventories", "Inventories", False),
    ("receivablesandprepayments", "Receivables and Prepayments", False),
    ("cash", "Short term investment & Cash & Cash Equivalents", False),
    ("totalassets", "Total Assets", True),
    ("totalequity", "Total Equity", True),
    ("borrowings_noncurrent", "Borrowings, Vendor fin.& Lease lia.-Non-Current", False),
    ("contract_noncurrent", "Contract Liability & Deferred income", False),
    ("othernoncurrentliabilities", "Other Non-Current Liabilities", False),
    ("totalnoncurrentliabilities", "Total Non-Current Liabilities", True),
    ("borrowings_current", "Borrowings, Vendor fin.& Lease lia – Current", False),
    ("contract_current", "Contract Liability & Deferred income", False),
    ("tradeotherpayables", "Trade & Other payables", False),
    ("totalcurrentliabilities", "Total Current Liabilities", True),
    ("totalequityliabilities", "Total Equity & Liabilities", True),
)


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _period(value, where: str) -> Tuple[int, int]:
    if isinstance(value, (date, datetime)):
        return value.month, value.year
    text = str(value or "").strip().lower()
    month = None
    for token, number in _MONTH_LOOKUP.items():
        if re.search(rf"\b{re.escape(token)}\b", text):
            month = number
            break
    years = re.findall(r"(?:19|20)\d{2}", text)
    if month is None or not years:
        raise BoardPackSlidesError(f"Could not read the month and year from {where}: {value!r}.")
    return month, int(years[-1])


def _year(value, where: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if 1900 <= value <= 2200:
            return value
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    if match:
        return int(match.group(0))
    raise BoardPackSlidesError(f"Could not read the year from {where}: {value!r}.")


def _numeric(ws, row: int, column: int, context: str) -> float:
    value = ws.cell(row=row, column=column).value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        cell = f"{get_column_letter(column)}{row}"
        raise BoardPackSlidesError(
            f"{context}: expected a calculated number at '{ws.title}'!{cell}, found {value!r}."
        )
    return float(value)


def _decimal_places(ws, row: int, column: int) -> int:
    number_format = ws.cell(row=row, column=column).number_format
    positive_format = number_format.split(";", 1)[0].split("%", 1)[0]
    match = re.search(r"\.([0#?]+)", positive_format)
    return len(match.group(1)) if match else 0


def _ratio_rows(ws) -> Dict[str, int]:
    found = {}
    required = {spec[0] for spec in _RATIO_SPECS}
    for row in range(1, ws.max_row + 1):
        key = _norm(ws.cell(row=row, column=2).value)
        if key in required:
            found.setdefault(key, row)
    missing = sorted(required - set(found))
    if missing:
        raise BoardPackSlidesError(
            f"Missing required ratio row(s) on '{ws.title}': {', '.join(missing)}."
        )
    return found


def _balance_rows(ws) -> Dict[str, int]:
    labels = {}
    contracts = []
    borrowings = []
    for row in range(1, ws.max_row + 1):
        key = _norm(ws.cell(row=row, column=1).value)
        if not key:
            continue
        if key == "contractliabilitydeferredincome":
            contracts.append(row)
        elif key.startswith("borrowingsvendorfinleaselia"):
            borrowings.append((row, "noncurrent" in key))
        else:
            labels.setdefault(key, row)

    required = {
        "noncurrentassets", "inventories", "receivablesandprepayments",
        "totalassets", "totalequity", "othernoncurrentliabilities",
        "totalnoncurrentliabilities", "tradeotherpayables",
        "totalcurrentliabilities", "totalequityliabilities",
    }
    missing = sorted(required - set(labels))
    if missing:
        raise BoardPackSlidesError(
            f"Missing required balance-sheet row(s) on '{ws.title}': {', '.join(missing)}."
        )

    cash_rows = [
        row for row in range(1, ws.max_row + 1)
        if "cashequivalents" in _norm(ws.cell(row=row, column=1).value)
        and (
            "investment" in _norm(ws.cell(row=row, column=1).value)
            or "other" in _norm(ws.cell(row=row, column=1).value)
        )
    ]
    current_borrowings = [row for row, is_noncurrent in borrowings if not is_noncurrent]
    noncurrent_borrowings = [row for row, is_noncurrent in borrowings if is_noncurrent]
    if not cash_rows:
        raise BoardPackSlidesError(f"Could not find the cash and investments row on '{ws.title}'.")
    if len(contracts) < 2:
        raise BoardPackSlidesError(
            f"Expected separate non-current and current contract-liability rows on '{ws.title}'."
        )
    if not current_borrowings or not noncurrent_borrowings:
        raise BoardPackSlidesError(
            f"Could not find both current and non-current borrowings rows on '{ws.title}'."
        )

    labels.update({
        "cash": cash_rows[0],
        "borrowings_noncurrent": noncurrent_borrowings[0],
        "contract_noncurrent": contracts[0],
        "borrowings_current": current_borrowings[0],
        "contract_current": contracts[1],
    })
    return labels


def read_board_pack_slides_workbook(path: str) -> BoardPackSlidesData:
    """Read the first visible Ratio tab and final tab from the supplied workbook."""
    try:
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        raise BoardPackSlidesError(f"Could not open the uploaded Excel workbook: {exc}") from exc

    try:
        visible_sheets = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
        if len(visible_sheets) < 2:
            raise BoardPackSlidesError("The workbook must contain visible Ratio and balance-sheet tabs.")
        ratios_ws = visible_sheets[0]
        balance_ws = visible_sheets[-1]
        if _norm(ratios_ws.cell(row=1, column=1).value) not in {"keyfinancialratios", "ratios"}:
            raise BoardPackSlidesError(
                f"The first visible tab must be the Ratio worksheet; found '{ratios_ws.title}'."
            )
        if _norm(balance_ws.cell(row=1, column=1).value) != "balancesheetgroup":
            raise BoardPackSlidesError(
                f"The last visible tab must be the Group balance-sheet worksheet; found '{balance_ws.title}'."
            )

        group_current_month, group_current_year = _period(
            ratios_ws.cell(row=3, column=5).value, f"{ratios_ws.title}!E3"
        )
        _, group_previous_year = _period(
            ratios_ws.cell(row=3, column=6).value, f"{ratios_ws.title}!F3"
        )
        company_current_year = _year(ratios_ws.cell(row=3, column=9).value, f"{ratios_ws.title}!I3")
        company_previous_year = _year(ratios_ws.cell(row=3, column=10).value, f"{ratios_ws.title}!J3")
        if (group_current_year, group_previous_year) != (company_current_year, company_previous_year):
            raise BoardPackSlidesError(
                "The Group and Company ratio headers do not refer to the same current and prior years."
            )

        balance_current_month, balance_current_year = _period(
            balance_ws.cell(row=2, column=2).value, f"{balance_ws.title}!B2"
        )
        balance_previous_month, balance_previous_year = _period(
            balance_ws.cell(row=2, column=3).value, f"{balance_ws.title}!C2"
        )
        if (balance_current_month, balance_current_year) != (group_current_month, group_current_year):
            raise BoardPackSlidesError(
                "The Ratio and balance-sheet tabs refer to different current reporting periods."
            )

        ratio_rows = _ratio_rows(ratios_ws)
        ratios = [
            RatioMetric(
                category=category,
                label=label,
                value_format=value_format,
                group_current=_numeric(ratios_ws, ratio_rows[key], 5, label),
                group_previous=_numeric(ratios_ws, ratio_rows[key], 6, label),
                group_variance=_numeric(ratios_ws, ratio_rows[key], 7, label),
                company_current=_numeric(ratios_ws, ratio_rows[key], 9, label),
                company_previous=_numeric(ratios_ws, ratio_rows[key], 10, label),
                company_variance=_numeric(ratios_ws, ratio_rows[key], 11, label),
                group_decimals=(
                    _decimal_places(ratios_ws, ratio_rows[key], 5),
                    _decimal_places(ratios_ws, ratio_rows[key], 6),
                    _decimal_places(ratios_ws, ratio_rows[key], 7),
                ),
                company_decimals=(
                    _decimal_places(ratios_ws, ratio_rows[key], 9),
                    _decimal_places(ratios_ws, ratio_rows[key], 10),
                    _decimal_places(ratios_ws, ratio_rows[key], 11),
                ),
                row_height=row_height,
            )
            for key, category, label, value_format, row_height in _RATIO_SPECS
        ]

        balance_row_numbers = _balance_rows(balance_ws)
        balance_sheet = [
            BalanceSheetRow(
                label=label,
                current=_numeric(balance_ws, balance_row_numbers[key], 2, label),
                previous=_numeric(balance_ws, balance_row_numbers[key], 3, label),
                is_total=is_total,
            )
            for key, label, is_total in _BALANCE_ROWS
        ]
        return BoardPackSlidesData(
            period_month=_MONTHS[group_current_month - 1],
            period_year=group_current_year,
            previous_month=_MONTHS[balance_previous_month - 1],
            previous_year=balance_previous_year,
            current_year=company_current_year,
            ratio_previous_year=company_previous_year,
            ratios=ratios,
            balance_sheet=balance_sheet,
            sheets_used=[ratios_ws.title, balance_ws.title],
        )
    finally:
        workbook.close()
