"""
Reads the GL code mapping workbook ("GL code mapping.xlsx", sheet "6.PL-EBITDA").

Layout: P&L line labels in one column and, under the "Natural ac codes" header,
"From" / "To" account columns followed by an "and" column for single accounts.
A line may continue on following rows that have accounts but no label
(Operating costs spans three rows). Subtotal rows (EBITDA, Operating profit,
...) have no accounts and are ignored; the engine computes them.

Labels are matched by text, so rows may move and Finance can edit the ranges
without code changes. Some labels in the sheet are formulas, so the workbook is
read with cached values.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import openpyxl

from utils.logger import logger

HEADER_SEARCH_ROWS = 15
MIN_ACCOUNT, MAX_ACCOUNT = 100000, 999999

# (line key, test on the label with everything but letters stripped)
LINE_RULES: List[Tuple[str, callable]] = [
    ("revenue", lambda s: s == "revenue"),
    ("operating_costs", lambda s: s.startswith("operatingcost")),
    ("depreciation", lambda s: s == "depreciation"),
    ("amortisation", lambda s: s.startswith("amortisation") or s.startswith("amortization")),
    ("other_income", lambda s: s == "otherincome"),
    ("interest_expenses", lambda s: s.startswith("interestexpense")),
    ("fx_gain_loss", lambda s: s.startswith("foreignexchange") or s.startswith("exchangegain")),
    ("interest_income", lambda s: s == "interestincome"),
    ("share_of_associate", lambda s: s.startswith("shareofprofit")),
    ("taxation", lambda s: s == "taxation"),
    ("oci_cash_flow_hedges", lambda s: s.startswith("netmovementoncashflowhedge")),
    ("oci_fair_value", lambda s: s.startswith("netchangeinfairvalue")),
    ("oci_actuarial", lambda s: s.startswith("definedbenefitplan")),
    ("oci_tax", lambda s: s.startswith("taxoncomprehensiveincome")),
]

# Lines the report cannot be produced without.
REQUIRED_LINES = ["revenue", "operating_costs", "depreciation", "taxation"]


class MappingFormatError(ValueError):
    """The mapping workbook is not in the expected layout."""


@dataclass(frozen=True)
class AccountRange:
    start: int
    end: int

    def __contains__(self, account: int) -> bool:
        return self.start <= account <= self.end

    def __str__(self) -> str:
        return str(self.start) if self.start == self.end else f"{self.start}–{self.end}"


@dataclass
class MappedLine:
    key: str
    label: str
    ranges: List[AccountRange] = field(default_factory=list)


@dataclass
class GLMapping:
    lines: Dict[str, MappedLine]
    warnings: List[str] = field(default_factory=list)

    def line_for(self, account: int) -> Optional[str]:
        for line in self.lines.values():
            if any(account in r for r in line.ranges):
                return line.key
        return None


def _norm(value) -> str:
    return re.sub(r"[^a-z]", "", str(value).lower()) if value is not None else ""


def _line_key(label) -> Optional[str]:
    text = _norm(label)
    for key, rule in LINE_RULES:
        if rule(text):
            return key
    return None


def _account(value) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer() and MIN_ACCOUNT <= number <= MAX_ACCOUNT:
        return int(number)
    return None


def _find_layout(ws) -> Tuple[int, int, int]:
    """Returns (header row, "From" column, "To" column)."""
    for row in ws.iter_rows(min_row=1, max_row=HEADER_SEARCH_ROWS):
        from_col = to_col = None
        for cell in row:
            key = _norm(cell.value)
            if key == "from":
                from_col = cell.column
            elif key == "to":
                to_col = cell.column
        if from_col and to_col:
            return row[0].row, from_col, to_col
    raise MappingFormatError("Could not find the 'From' / 'To' account code header in the mapping sheet")


def _label_column(ws, header_row: int, from_col: int) -> int:
    """The column, left of the account codes, that holds the most recognised P&L labels."""
    best, best_hits = 1, -1
    for col in range(1, from_col):
        hits = sum(
            1 for r in range(header_row + 1, ws.max_row + 1)
            if _line_key(ws.cell(r, col).value)
        )
        if hits > best_hits:
            best, best_hits = col, hits
    return best


def _row_ranges(ws, row: int, from_col: int, to_col: int) -> List[AccountRange]:
    ranges = []
    start, end = _account(ws.cell(row, from_col).value), _account(ws.cell(row, to_col).value)
    if start and end:
        if end < start:
            raise MappingFormatError(f"Row {row}: 'From' {start} is after 'To' {end}")
        ranges.append(AccountRange(start, end))
    elif start or end:
        ranges.append(AccountRange(start or end, start or end))
    # Columns after "To" ("and") hold single extra accounts.
    for col in range(to_col + 1, ws.max_column + 1):
        single = _account(ws.cell(row, col).value)
        if single:
            ranges.append(AccountRange(single, single))
    return ranges


def read_gl_mapping(path: Union[str, Path], sheet_name: Optional[str] = None) -> GLMapping:
    path = Path(path)
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception as exc:
        raise MappingFormatError(f"Could not open {path.name} as an Excel workbook: {exc}") from exc

    ws = wb[sheet_name] if sheet_name else wb.worksheets[0]
    header_row, from_col, to_col = _find_layout(ws)
    label_col = _label_column(ws, header_row, from_col)

    lines: Dict[str, MappedLine] = {}
    current: Optional[MappedLine] = None
    for row in range(header_row + 1, ws.max_row + 1):
        label = ws.cell(row, label_col).value
        ranges = _row_ranges(ws, row, from_col, to_col)
        if label is not None and str(label).strip():
            key = _line_key(label)
            if key is None:
                if ranges:
                    raise MappingFormatError(f"Row {row}: unrecognised P&L line '{label}' has account codes")
                current = None  # subtotal or note row
                continue
            if key in lines:
                raise MappingFormatError(f"Row {row}: P&L line '{label}' appears more than once")
            current = lines[key] = MappedLine(key, str(label).strip(), ranges)
        elif ranges:
            if current is None:
                raise MappingFormatError(f"Row {row}: account codes without a P&L line above them")
            current.ranges.extend(ranges)

    missing = [k for k in REQUIRED_LINES if k not in lines or not lines[k].ranges]
    if missing:
        raise MappingFormatError(f"Mapping is missing account codes for: {', '.join(missing)}")

    _check_overlaps(lines)

    warnings = [f"'{line.label}' has no account codes and will be zero"
                for line in lines.values() if not line.ranges]
    for w in warnings:
        logger.warning(f"{path.name}: {w}")
    logger.info(f"Read GL mapping {path.name}: {len(lines)} P&L lines")
    return GLMapping(lines=lines, warnings=warnings)


def _check_overlaps(lines: Dict[str, MappedLine]):
    spans = sorted((r.start, r.end, line.label) for line in lines.values() for r in line.ranges)
    for (s1, e1, l1), (s2, e2, l2) in zip(spans, spans[1:]):
        if s2 <= e1:
            raise MappingFormatError(
                f"Account codes {s2}–{min(e1, e2)} are mapped to both '{l1}' and '{l2}'"
            )
