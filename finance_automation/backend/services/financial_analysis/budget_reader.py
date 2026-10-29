"""
Reads a Financial Analysis budget workbook.

Supports two formats:
1. Month-wise "Notes to the Statement of Financial Performance" workbook
   (e.g. YTD June 26.xlsx, YTD March 26.xlsx) with columns like 'YTD-Budget', 'PTD-Budget'.
   Identifies the period from the filename (or preamble cells like 'LKR Jun-26'),
   and extracts line items (e.g. Total Operating Cost, Staff Costs, etc.).
2. Annual / multi-month budget workbook
   with a 6-digit natural account column and month columns (Jan..Dec).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import openpyxl
import pandas as pd

from services.financial_analysis.periods import Period, parse_period
from utils.logger import logger

HEADER_SEARCH_ROWS = 20
MONTH_ABBREVS = ["jan", "feb", "mar", "apr", "may", "jun",
                 "jul", "aug", "sep", "oct", "nov", "dec"]
MONTH_FULL = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november", "december"]


class BudgetFormatError(ValueError):
    """The file is not a budget workbook in an expected layout."""


@dataclass
class BudgetBalance:
    """YTD budget rupees for one natural account, keyed by month index 1-12."""
    account: int
    name: str
    ytd: Dict[int, float] = field(default_factory=dict)   # month_index -> rupees YTD


@dataclass
class FABudget:
    """In-memory budget loaded from a workbook."""
    source_filename: str
    year: int                                              # budget year
    period: Optional[Period] = None                        # specific month-end if single-period
    accounts: Dict[int, BudgetBalance] = field(default_factory=dict)
    months_loaded: List[int] = field(default_factory=list) # 1-based month indices with data
    lines: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)  # line name -> {'ptd': ..., 'ytd': ...}
    summary: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    total_operating_cost: Dict[str, Optional[float]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def ytd_for(self, account: int, month: int) -> Optional[float]:
        """YTD rupees for `account` at `month` (1-12), or None if not in the budget."""
        bal = self.accounts.get(account)
        return bal.ytd.get(month) if bal else None


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v).lower()) if v is not None else ""


def _month_index(header_text: str) -> Optional[int]:
    """Return 1-based month index for a column header, or None."""
    h = _norm(header_text)
    for i, abbr in enumerate(MONTH_ABBREVS, start=1):
        if h.startswith(abbr):
            return i
    for i, full in enumerate(MONTH_FULL, start=1):
        if h.startswith(full):
            return i
    return None


def _detect_year(headers: List[object]) -> Optional[int]:
    """Best-effort: find a 4-digit year in header values."""
    for h in headers:
        m = re.search(r"\b(20\d{2})\b", str(h))
        if m:
            return int(m.group(1))
    return None


def _read_notes_budget(path: Path) -> Optional[FABudget]:
    """
    Attempt to read workbook as 'Notes to Statement of Financial Performance'
    with columns like YTD-Budget, PTD-Budget, YTD-Actual, Last Year.
    Returns FABudget if format matches, otherwise None.
    """
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb.active
    except Exception as exc:
        raise BudgetFormatError(f"Could not open {path.name}: {exc}") from exc

    try:
        # 1. Detect period
        period = parse_period(path.name)
        if not period:
            for r in range(1, 15):
                for c in range(1, 15):
                    val = str(ws.cell(r, c).value or "")
                    p = parse_period(val)
                    if p:
                        period = p
                        break
                if period:
                    break

        # 2. Look for YTD-Budget column in first 20 rows
        header_row = ytd_col = ptd_col = None
        for r in range(1, 20):
            for c in range(1, 20):
                val = str(ws.cell(r, c).value or "").lower()
                if "ytd-budget" in val or "ytd budget" in val:
                    header_row = r
                    ytd_col = c
                if "ptd-budget" in val or "ptd budget" in val:
                    ptd_col = c
            if ytd_col:
                break

        if not header_row or not ytd_col:
            return None

        if not period:
            raise BudgetFormatError(
                f"{path.name}: could not detect the month/year for this budget file "
                "(expected 'LKR Jun-26' or 'YTD June 26' in header or filename)."
            )

        # Detect columns in header rows
        ytd_budget_col = ytd_col
        ytd_actual_col = None
        ytd_ly_actual_col = None
        ptd_budget_col = ptd_col
        ptd_actual_col = None
        ptd_ly_actual_col = None

        for c in range(1, 15):
            h1 = str(ws.cell(header_row, c).value or "")
            h2 = str(ws.cell(header_row + 1, c).value or "")
            val = f"{h1} {h2}".lower().strip()
            if not val:
                continue
            if "ytd" in val and "actual" in val and "last" not in val and "ly" not in val:
                ytd_actual_col = c
            elif "ytd" in val and ("last" in val or "ly" in val):
                ytd_ly_actual_col = c
            elif "ptd" in val and "actual" in val and "last" not in val and "prev" not in val:
                ptd_actual_col = c
            elif "ptd" in val and ("last" in val or "ly" in val):
                ptd_ly_actual_col = c
            elif "ptd" in val and "budget" in val:
                ptd_budget_col = c
            elif "ytd" in val and "budget" in val:
                ytd_budget_col = c

        if not ytd_actual_col and ytd_budget_col:
            ytd_actual_col = ytd_budget_col - 1
        if not ytd_ly_actual_col and ytd_budget_col:
            ytd_ly_actual_col = ytd_budget_col + 1
        if not ptd_actual_col and ptd_budget_col:
            ptd_actual_col = ptd_budget_col - 1
        if not ptd_ly_actual_col and ptd_budget_col:
            ptd_ly_actual_col = ptd_budget_col + 1

        def _to_float(v) -> Optional[float]:
            try:
                return float(v) if v is not None else None
            except (ValueError, TypeError):
                return None

        # 3. Extract line items and categorize sections
        lines: Dict[str, Dict[str, Optional[float]]] = {}
        total_opex: Dict[str, Optional[float]] = {}
        curr_section = "General"
        section_items: List[Dict] = []

        for r in range(header_row + 1, ws.max_row + 1):
            desc = ws.cell(r, 2).value
            if desc is not None and str(desc).strip():
                name = str(desc).strip()
                if "1. Direct Expenses" in name:
                    curr_section = "Direct"
                    continue
                elif "2. Sales Expenses" in name:
                    curr_section = "Sales"
                    continue
                elif "3. Marketing Expenses" in name:
                    curr_section = "Marketing"
                    continue
                elif "4. General & Admin Costs" in name:
                    curr_section = "G&A"
                    continue

                if set(name) <= {"-", ".", " ", "_"}:
                    continue

                ytd_b = _to_float(ws.cell(r, ytd_budget_col).value) if ytd_budget_col else None
                ytd_a = _to_float(ws.cell(r, ytd_actual_col).value) if ytd_actual_col else None
                ytd_ly = _to_float(ws.cell(r, ytd_ly_actual_col).value) if ytd_ly_actual_col else None
                ptd_b = _to_float(ws.cell(r, ptd_budget_col).value) if ptd_budget_col else None
                ptd_a = _to_float(ws.cell(r, ptd_actual_col).value) if ptd_actual_col else None
                ptd_ly = _to_float(ws.cell(r, ptd_ly_actual_col).value) if ptd_ly_actual_col else None

                row_dict = {
                    "ptd": ptd_b,
                    "ytd": ytd_b,
                    "ytd_budget": ytd_b,
                    "ytd_actual": ytd_a,
                    "ytd_ly_actual": ytd_ly,
                    "ptd_budget": ptd_b,
                    "ptd_actual": ptd_a,
                    "ptd_ly_actual": ptd_ly,
                    "section": curr_section,
                }
                lines[name] = row_dict
                section_items.append({"section": curr_section, "name": name, **row_dict})

                if "total operating cost" in name.lower():
                    total_opex = {
                        "ptd": ptd_b,
                        "ytd": ytd_b,
                        "ytd_budget": ytd_b,
                        "ytd_actual": ytd_a,
                        "ytd_ly_actual": ytd_ly,
                        "ptd_budget": ptd_b,
                        "ptd_actual": ptd_a,
                    }

        # 4. Compute summaries
        def _get_line_summary(line_key: str) -> Dict[str, Optional[float]]:
            d = lines.get(line_key, {})
            return {
                "ytd_budget": d.get("ytd_budget"),
                "ytd_actual": d.get("ytd_actual"),
                "ytd_ly_actual": d.get("ytd_ly_actual"),
                "ptd_budget": d.get("ptd_budget"),
                "ptd_actual": d.get("ptd_actual"),
            }

        dir_exp = _get_line_summary("Total Direct Expenses")
        sales_exp = _get_line_summary("Total Sales Expenses")
        mktg_exp = _get_line_summary("Total Marketing Expenses")
        ga_costs = _get_line_summary("Total General & Admin Costs")

        # Sales & Marketing combined
        def _add_opt(a, b):
            if a is not None and b is not None:
                return a + b
            return a if a is not None else b

        sm_exp = {
            "ytd_budget": _add_opt(sales_exp.get("ytd_budget"), mktg_exp.get("ytd_budget")),
            "ytd_actual": _add_opt(sales_exp.get("ytd_actual"), mktg_exp.get("ytd_actual")),
            "ytd_ly_actual": _add_opt(sales_exp.get("ytd_ly_actual"), mktg_exp.get("ytd_ly_actual")),
            "ptd_budget": _add_opt(sales_exp.get("ptd_budget"), mktg_exp.get("ptd_budget")),
            "ptd_actual": _add_opt(sales_exp.get("ptd_actual"), mktg_exp.get("ptd_actual")),
        }

        # Staff costs (sum of all 4 staff items across sections)
        staff_items = [it for it in section_items if "staff" in it["name"].lower()]
        staff_costs = {
            "ytd_budget": sum(it["ytd_budget"] or 0.0 for it in staff_items) if staff_items else None,
            "ytd_actual": sum(it["ytd_actual"] or 0.0 for it in staff_items) if staff_items else None,
            "ytd_ly_actual": sum(it["ytd_ly_actual"] or 0.0 for it in staff_items) if staff_items else None,
            "ptd_budget": sum(it["ptd_budget"] or 0.0 for it in staff_items) if staff_items else None,
            "ptd_actual": sum(it["ptd_actual"] or 0.0 for it in staff_items) if staff_items else None,
        }

        summary = {
            "operating_cost": total_opex,
            "direct_expenses": dir_exp,
            "sales_expenses": sales_exp,
            "marketing_expenses": mktg_exp,
            "sales_marketing": sm_exp,
            "ga_costs": ga_costs,
            "staff_costs": staff_costs,
        }

        logger.info(
            f"Read Notes budget {path.name}: period={period.label}, "
            f"{len(lines)} lines, Total Opex YTD Bud={total_opex.get('ytd_budget')}, "
            f"Act={total_opex.get('ytd_actual')}, Staff YTD Act={staff_costs.get('ytd_actual')}"
        )
        return FABudget(
            source_filename=path.name,
            year=period.year,
            period=period,
            months_loaded=[period.month],
            lines=lines,
            summary=summary,
            total_operating_cost=total_opex,
        )
    finally:
        wb.close()


def read_fa_budget(path: Union[str, Path],
                   sheet_name: Union[int, str] = 0,
                   ytd_cumulate: bool = False) -> FABudget:
    """
    Read a budget workbook and return a FABudget.
    Supports Notes to Statement of Financial Performance (month-wise)
    or multi-month GL account workbook.
    """
    path = Path(path)

    # First attempt: Notes to Statement of Financial Performance format
    notes_budget = _read_notes_budget(path)
    if notes_budget is not None:
        return notes_budget

    # Second attempt: Multi-month GL account format
    try:
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object)
    except Exception as exc:
        raise BudgetFormatError(
            f"Could not open {path.name} as an Excel workbook: {exc}"
        ) from exc

    header_row_idx = None
    account_col = name_col = None
    month_cols: Dict[int, int] = {}

    for row_idx in range(min(HEADER_SEARCH_ROWS, len(raw))):
        row = list(raw.iloc[row_idx])
        found_months: Dict[int, int] = {}
        acc_col = name_col_cand = None

        for col_idx, cell in enumerate(row):
            n = _norm(cell)
            m = _month_index(cell)
            if m is not None:
                found_months[m] = col_idx
            if n in ("ac", "account", "accountno", "naturalaccount", "glaccount"):
                acc_col = col_idx
            if n in ("acname", "accountname", "description", "name", "glname"):
                name_col_cand = col_idx

        if len(found_months) >= 3:
            header_row_idx = row_idx
            account_col = acc_col
            name_col = name_col_cand
            month_cols = found_months
            break

    if header_row_idx is None:
        raise BudgetFormatError(
            f"{path.name}: could not recognize budget layout. "
            "Expected either a Notes budget export with 'YTD-Budget' columns, "
            "or a workbook with monthly columns ('Jan', 'Feb', … 'Dec')."
        )

    year = _detect_year(list(raw.iloc[header_row_idx])) or 0
    warnings: List[str] = []

    if account_col is None:
        raise BudgetFormatError(
            f"{path.name}: could not identify the account number column "
            "(expected a header like 'A/c', 'Account', 'Natural Account')."
        )

    data = raw.iloc[header_row_idx + 1:].reset_index(drop=True)

    def amounts(col_idx: int) -> pd.Series:
        return pd.to_numeric(data.iloc[:, col_idx], errors="coerce").fillna(0.0)

    accs = pd.to_numeric(data.iloc[:, account_col], errors="coerce")
    names = (
        data.iloc[:, name_col].astype(str).str.strip()
        if name_col is not None
        else pd.Series("", index=data.index)
    )
    valid = accs.notna() & (accs >= 100_000) & (accs <= 999_999)

    if not valid.any():
        raise BudgetFormatError(
            f"{path.name}: no valid 6-digit natural account numbers found in account column."
        )

    monthly_data: Dict[int, pd.Series] = {
        m: amounts(col_idx) for m, col_idx in month_cols.items()
    }

    accounts: Dict[int, BudgetBalance] = {}
    for i in data[valid].index:
        acc_int = int(accs[i])
        name = names[i] if name_col is not None else ""
        ytd_map: Dict[int, float] = {}

        if ytd_cumulate:
            running = 0.0
            for m in range(1, 13):
                if m in monthly_data:
                    running += float(monthly_data[m][i])
                    ytd_map[m] = running
        else:
            for m, series in monthly_data.items():
                ytd_map[m] = float(series[i])

        accounts[acc_int] = BudgetBalance(acc_int, name, ytd_map)

    months_loaded = sorted(month_cols.keys())
    single_period = Period(year, months_loaded[0]) if len(months_loaded) == 1 and year else None

    logger.info(
        f"Read budget {path.name}: year={year or 'unknown'}, "
        f"{len(accounts)} accounts, months {months_loaded}"
    )
    return FABudget(
        source_filename=path.name,
        year=year,
        period=single_period,
        accounts=accounts,
        months_loaded=months_loaded,
        warnings=warnings,
    )
