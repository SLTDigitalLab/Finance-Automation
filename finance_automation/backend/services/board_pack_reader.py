"""
Reads the monthly "Sub workings" workbook for the Finance Board Pack.

Data sources (visible tabs only — hidden legacy tabs are skipped):
  Tab 1  INCOME Amalg YTD <Mon> <Year>  -> Group Financials slides (actual vs last year)
  Tab 2  BD Slides-SLT-Mobtel-Grp       -> Executive Summary slides (actual vs budget)
  SLTSL                                 -> Executive Summary – SLTS YTD budget

SLTS Executive Summary uses three sources:
  - YTD Actuals & Last Year: INCOME Amalg tab, SLTS Amalgamated column, Board Pack Slides section
  - Month Actuals: INCOME Amalg tab, SLTS Amalgamated column, Month block
  - YTD Budget: SLTSL tab, "For the Period of ..." column; month budget is that less
    last month's YTD budget, taken from the snapshot saved by last month's run

Rows are located by their labels in column A (column B for SLTSL) and entity
columns by their header text, so the reader keeps working when rows or
columns move between months.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

import openpyxl

from utils.logger import logger

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Normalised label -> canonical metric key. Normalising strips everything but
# letters, so "Dep'n & Amortization" and "Dep’n & Amortization" both match.
LABEL_KEYS = {
    "revenue": "revenue",
    "operatingcost": "operating_cost",
    "directcost": "direct_cost",
    "grossprofit": "gross_profit",
    "sellingadmincost": "selling_admin",
    "ebitda": "ebitda",
    "depnamortization": "dep_amort",
    "depreciationamortization": "dep_amort",
    "operatingprofit": "operating_profit",
    "ebit": "ebit",
    "netfinancecost": "net_finance_cost",
    "netinterest": "net_finance_cost",      # INCOME Amalg SLTS block label
    "exchangegainloss": "exchange_gain",
    "foreignexchangegainloss": "exchange_gain",  # INCOME Amalg main P&L label
    "otherincome": "other_income",
    "nonoperatingincome": "other_income",   # SLTSL label
    "taxation": "taxation",
    "incometax": "taxation",                # SLTSL label
    "npat": "npat",
    "pat": "npat",
    "gpmargin": "gp_margin",
    "ebitdamargin": "ebitda_margin",
    "ebitmargin": "ebit_margin",
    "operatingmargin": "operating_margin",
    "operatingprofitmargin": "operating_margin",
    "npatmargin": "npat_margin",
    "patmargin": "npat_margin",
}

EXEC_METRICS = [
    "revenue", "operating_cost", "ebitda", "dep_amort", "ebit", "net_finance_cost",
    "other_income", "taxation", "npat",
    "ebitda_margin", "ebit_margin", "npat_margin",
]
FIN_AMOUNT_METRICS = [
    "revenue", "direct_cost", "gross_profit", "selling_admin", "ebitda",
    "dep_amort", "operating_profit", "ebit", "npat",
]
FIN_MARGIN_METRICS = ["gp_margin", "ebitda_margin", "operating_margin", "npat_margin"]

# SLTS Executive Summary also shows Exchange Gain/(Loss) as its own row
SLTS_EXEC_METRICS = [
    "revenue", "operating_cost", "ebitda", "dep_amort", "ebit", "net_finance_cost",
    "exchange_gain", "other_income", "taxation", "npat",
]
EXEC_MARGINS = {"ebitda_margin": "ebitda", "ebit_margin": "ebit", "npat_margin": "npat"}
# Rows whose variance is the change in the size of the cost when both figures
# are negative, so (422) against a budget of (503) is a variance of (81), not 81.
COST_METRICS = {"operating_cost", "dep_amort", "net_finance_cost", "taxation", "exchange_gain"}

# Column offsets from an entity's "Actual" column on the BD Slides tab
EXEC_OFFSETS = {"act": 0, "ly": 1, "var_ly": 2, "pct_ly": 3, "bud": 4, "var_bud": 5, "pct_bud": 6}
# Column offsets from an entity's current-year column on the INCOME tab
FIN_OFFSETS = {"cur": 0, "prev": 1, "var": 2, "pct": 3}


class BoardPackError(Exception):
    """Raised when the workbook cannot be used to build the board pack."""


@dataclass
class Period:
    month: int
    year: int

    @property
    def label(self) -> str:
        return f"{MONTH_LABELS[self.month - 1]}'{self.year % 100:02d}"

    @property
    def month_name(self) -> str:
        return MONTH_LABELS[self.month - 1]

    @property
    def previous_month(self) -> "Period":
        return Period(12, self.year - 1) if self.month == 1 else Period(self.month - 1, self.year)

    @property
    def previous_year(self) -> "Period":
        return Period(self.month, self.year - 1)


@dataclass
class BoardPackData:
    period: Period
    # exec[entity]["month" | "ytd"][metric][field]
    exec: Dict[str, Dict[str, Dict[str, Dict[str, object]]]]
    # fin["ytd" | "month"][entity][metric][field]
    fin: Dict[str, Dict[str, Dict[str, Dict[str, object]]]]
    # slts[metric] -> YTD actual
    slts: Dict[str, Optional[float]]
    sheets_used: List[str]
    warnings: List[str] = field(default_factory=list)
    # YTD figures saved after each run so next month can work out its month values
    snapshot: Dict[str, object] = field(default_factory=dict)


def _norm(value) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").lower())


def _cell(ws, row: int, col: int):
    value = ws.cell(row=row, column=col).value
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _find_row(ws, predicate, start: int = 1, end: Optional[int] = None, col: int = 1) -> Optional[int]:
    end = end or ws.max_row
    for r in range(start, end + 1):
        if predicate(_cell(ws, r, col)):
            return r
    return None


def _label_rows(ws, start: int, end: int, col: int = 1) -> Dict[str, int]:
    """First row for each canonical metric label between start and end (inclusive)."""
    rows: Dict[str, int] = {}
    for r in range(start, end + 1):
        key = LABEL_KEYS.get(_norm(_cell(ws, r, col)))
        if key and key not in rows:
            rows[key] = r
    return rows


def _entity_columns(ws, start: int, end: int) -> tuple:
    """Finds the header row (the first one naming 'Telecom') and maps entity -> column."""
    for r in range(start, end + 1):
        cols: Dict[str, int] = {}
        for c in range(1, ws.max_column + 1):
            text = _norm(_cell(ws, r, c))
            if text == "telecom":
                cols.setdefault("SLT", c)
            elif text == "mobitel":
                cols.setdefault("Mobitel", c)
            elif text == "group":
                cols.setdefault("Group", c)
            elif "sltsamalgamated" in text:
                cols.setdefault("SLTS", c)
        if "SLT" in cols:
            return r, cols
    raise BoardPackError(f"Could not find the entity header row (Telecom / Mobitel / Group) on '{ws.title}'.")


def _block_end(ws, start: int, last_label: str) -> int:
    end = _find_row(ws, lambda v: _norm(v) == last_label, start)
    if end is None:
        raise BoardPackError(f"Could not find the '{last_label}' row below row {start} on '{ws.title}'.")
    return end


def _read_values(ws, rows: Dict[str, int], col: int, offsets: Dict[str, int], metrics: List[str],
                 where: str, warnings: List[str]) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    missing = [m for m in metrics if m not in rows]
    if missing:
        raise BoardPackError(f"{where}: missing row(s) {', '.join(missing)} on '{ws.title}'.")
    for metric in metrics:
        result[metric] = {}
        for field_name, offset in offsets.items():
            value = _cell(ws, rows[metric], col + offset)
            if isinstance(value, str) and value.startswith("#") and value != "#DIV/0!":
                warnings.append(
                    f"{ws.title}!{openpyxl.utils.get_column_letter(col + offset)}{rows[metric]} "
                    f"({where}, {metric}) contains {value}"
                )
            result[metric][field_name] = value
    return result


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _variance(metric: str, act, base) -> tuple:
    """(variance, % of base) the way the board pack shows them. A zero base gives 0%."""
    act, base = _num(act), _num(base)
    if act is None or base is None:
        return None, None
    if metric in COST_METRICS and act < 0 and base < 0:
        var = abs(act) - abs(base)
    else:
        var = act - base
    return var, (var / abs(base) if base else 0.0)


def _margin(value, revenue) -> Optional[float]:
    value, revenue = _num(value), _num(revenue)
    if value is None or not revenue:
        return None
    return value / revenue


def _margin_change(act, base) -> Optional[float]:
    act, base = _num(act), _num(base)
    return act - base if act is not None and base is not None else None


def _apply_variances(block: Dict[str, Dict[str, object]], pairs: Dict[str, tuple]):
    """Fills var/pct fields from the actual and comparison fields, e.g. {"bud": ("var_bud", "pct_bud")}."""
    for metric, values in block.items():
        for base_field, (var_field, pct_field) in pairs.items():
            if base_field not in values:
                continue
            if metric.endswith("_margin"):
                values[var_field] = None
                values[pct_field] = _margin_change(values.get("act"), values.get(base_field))
            else:
                values[var_field], values[pct_field] = _variance(metric, values.get("act"), values.get(base_field))


def _parse_period(value) -> Optional[Period]:
    if isinstance(value, (datetime, date)):
        return Period(value.month, value.year)
    match = re.match(r"^\s*([A-Za-z]+)\s*['’`]?\s*(\d{2,4})\s*$", str(value or ""))
    if not match:
        return None
    prefix = match.group(1)[:3].lower()
    months = [m[:3].lower() for m in MONTH_LABELS]
    if prefix not in months:
        return None
    year = int(match.group(2))
    return Period(months.index(prefix) + 1, year + 2000 if year < 100 else year)


def _visible_sheets(wb) -> list:
    return [ws for ws in wb.worksheets if ws.sheet_state == "visible"]


def _read_exec_tab(ws, warnings: List[str]) -> Dict[str, Dict[str, Dict[str, Dict[str, object]]]]:
    anchor = _find_row(ws, lambda v: _norm(v) == "boardpackslides")
    if anchor is None:
        raise BoardPackError(f"Could not find the 'Board Pack Slides' section on '{ws.title}'.")

    ytd_end = _block_end(ws, anchor, "npatmargin")
    month_start = _find_row(ws, lambda v: _norm(v).startswith("month"), ytd_end)
    if month_start is None:
        raise BoardPackError(f"Could not find the 'Month' section below the YTD block on '{ws.title}'.")
    month_end = _block_end(ws, month_start, "npatmargin")

    ytd_rows = _label_rows(ws, anchor, ytd_end)
    month_rows = _label_rows(ws, month_start, month_end)
    _, ytd_cols = _entity_columns(ws, anchor, ytd_end)
    _, month_cols = _entity_columns(ws, month_start, month_end)

    data = {}
    for entity in ("Group", "SLT", "Mobitel"):
        if entity not in ytd_cols or entity not in month_cols:
            raise BoardPackError(f"Could not find the '{entity}' columns on '{ws.title}'.")
        ytd = _read_values(ws, ytd_rows, ytd_cols[entity], EXEC_OFFSETS, EXEC_METRICS,
                           f"{entity} YTD", warnings)
        month = _read_values(ws, month_rows, month_cols[entity], EXEC_OFFSETS, EXEC_METRICS,
                             f"{entity} month", warnings)
        _apply_variances(ytd, {"ly": ("var_ly", "pct_ly"), "bud": ("var_bud", "pct_bud")})
        _apply_variances(month, {"bud": ("var_bud", "pct_bud")})
        data[entity] = {"ytd": ytd, "month": month}
    return data


def _read_fin_tab(ws, warnings: List[str]) -> Dict[str, Dict[str, Dict[str, Dict[str, object]]]]:
    anchor = _find_row(ws, lambda v: _norm(v) == "boardpackslides")
    if anchor is None:
        raise BoardPackError(f"Could not find the 'Board Pack Slides' section on '{ws.title}'.")
    mom_anchor = _find_row(ws, lambda v: _norm(v).startswith("mononmon"), anchor)
    if mom_anchor is None:
        raise BoardPackError(f"Could not find the 'Mon - on - Mon' section on '{ws.title}'.")

    # YTD amounts: the Board Pack Slides block. YTD margins: the main P&L above it.
    ytd_end = _block_end(ws, anchor, "pat")
    ytd_rows = _label_rows(ws, anchor, ytd_end)
    _, ytd_cols = _entity_columns(ws, anchor, ytd_end)
    margin_rows = _label_rows(ws, 1, anchor - 1)
    _, margin_cols = _entity_columns(ws, 1, anchor - 1)

    mom_end = _block_end(ws, mom_anchor, "patmargin")
    mom_rows = _label_rows(ws, mom_anchor, mom_end)
    _, mom_cols = _entity_columns(ws, mom_anchor, mom_end)

    ytd: Dict[str, Dict[str, Dict[str, object]]] = {}
    for entity in ("SLT", "Mobitel", "Group", "SLTS"):
        if entity not in ytd_cols or entity not in margin_cols:
            raise BoardPackError(f"Could not find the '{entity}' YTD columns on '{ws.title}'.")
        ytd[entity] = {
            **_read_values(ws, ytd_rows, ytd_cols[entity], FIN_OFFSETS, FIN_AMOUNT_METRICS,
                           f"{entity} YTD", warnings),
            **_read_values(ws, margin_rows, margin_cols[entity], FIN_OFFSETS, FIN_MARGIN_METRICS,
                           f"{entity} YTD margins", warnings),
        }

    month: Dict[str, Dict[str, Dict[str, object]]] = {}
    for entity in ("SLT", "Mobitel", "Group"):
        if entity not in mom_cols:
            raise BoardPackError(f"Could not find the '{entity}' month-on-month columns on '{ws.title}'.")
        month[entity] = _read_values(ws, mom_rows, mom_cols[entity], FIN_OFFSETS,
                                     FIN_AMOUNT_METRICS + FIN_MARGIN_METRICS,
                                     f"{entity} month-on-month", warnings)
    return {"ytd": ytd, "month": month}


# ─── SLTS Executive Summary ──────────────────────────────────────────────────
#
# SLTS has no columns on the BD Slides tab, so its slide is assembled from:
#   - INCOME Amalg, SLTS Amalgamated column: YTD actuals (column) and last year (next column)
#     from the Board Pack Slides block, month actuals from the "Month <Mon>" block, and
#     Other Income / Exchange Gain from the main P&L above the Board Pack Slides block
#   - SLTSL tab, "For the Period of <Mon Year>" column: YTD budget
# The workbook has no SLTS month budget, and it does not split the month's Other Income
# from its Exchange Gain, so both come from this YTD less last month's YTD (saved in the
# previous run's snapshot).

def _find_slts_col(ws) -> Optional[int]:
    """Column of the SLTS Amalgamated current-year figures in INCOME Amalg."""
    for r in range(1, min(ws.max_row, 15) + 1):
        for c in range(1, ws.max_column + 1):
            if "sltsamalgamated" in _norm(_cell(ws, r, c)):
                return c
    return None


def _read_sltsl_budget(wb, period: Period, warnings: List[str]) -> Dict[str, Optional[float]]:
    """SLTS YTD budget by metric, from the SLTSL tab."""
    budget: Dict[str, Optional[float]] = dict.fromkeys(SLTS_EXEC_METRICS)
    ws = next((s for s in wb.worksheets if _norm(s.title) == "sltsl"), None)
    if ws is None:
        warnings.append("SLTSL tab not found – SLTS budget left blank.")
        return budget

    bud_col = bud_hdr = bud_hdr_row = None
    for r in range(1, min(ws.max_row, 12) + 1):
        for c in range(1, ws.max_column + 1):
            text = str(_cell(ws, r, c) or "")
            if _norm(text).startswith("fortheperiodof"):
                bud_col, bud_hdr, bud_hdr_row = c, text, r
                break
        if bud_col:
            break
    if bud_col is None:
        warnings.append("SLTSL: 'For the Period of ...' column not found – SLTS budget left blank.")
        return budget

    stated = _parse_period(re.sub(r"(?i)^\s*for the period of\s*", "", bud_hdr))
    if stated and (stated.month, stated.year) != (period.month, period.year):
        warnings.append(f"SLTSL: column is '{bud_hdr}' but the board pack period is {period.label}.")

    # SLTSL labels are in column B; costs are already negative
    rows: Dict[str, int] = {}
    for r in range(bud_hdr_row + 1, ws.max_row + 1):
        label = _norm(_cell(ws, r, 2))
        if label and label not in rows:
            rows[label] = r

    def value(label: str) -> Optional[float]:
        return _num(_cell(ws, rows[label], bud_col)) if label in rows else None

    direct, opex = value("directcosts"), value("opex")
    budget.update({
        "revenue": value("revenue"),
        "operating_cost": (direct or 0) + (opex or 0) if direct is not None or opex is not None else None,
        "ebitda": value("ebitda"),
        "dep_amort": value("depreciationamortization"),
        "ebit": value("operatingprofit"),
        "net_finance_cost": value("interestincomecost"),
        "exchange_gain": value("exchangegainloss"),
        "other_income": value("nonoperatingincome"),
        "taxation": value("incometax"),
        "npat": value("pat"),
    })
    return budget


def _slts_amounts(ws, rows: Dict[str, int], col: int) -> Dict[str, Optional[float]]:
    """SLTS amounts from a Board Pack Slides style block, where costs are shown positive."""
    def value(metric: str) -> Optional[float]:
        return _num(_cell(ws, rows[metric], col)) if metric in rows else None

    def negate(v: Optional[float]) -> Optional[float]:
        return -v if v is not None else None

    direct, selling = value("direct_cost"), value("selling_admin")
    return {
        "revenue": value("revenue"),
        "operating_cost": negate(direct + selling) if direct is not None and selling is not None else None,
        "ebitda": value("ebitda"),
        "dep_amort": negate(value("dep_amort")),
        # The SLTS slide's EBIT line is Operating Profit (EBITDA less Dep'n)
        "ebit": value("operating_profit"),
        "net_finance_cost": value("net_finance_cost"),
        "taxation": value("taxation"),
        "npat": value("npat"),
    }


def _subtract(current: Dict[str, Optional[float]], previous: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
    result = {}
    for metric, value in current.items():
        prev = _num(previous.get(metric))
        result[metric] = value - prev if value is not None and prev is not None else None
    return result


def _with_margins(block: Dict[str, Dict[str, object]], fields: List[str]):
    revenue = block["revenue"]
    for margin, metric in EXEC_MARGINS.items():
        block[margin] = {f: _margin(block[metric].get(f), revenue.get(f)) for f in fields}


def _read_slts_exec(wb, fin_ws, period: Period, previous: Optional[Dict[str, object]],
                    warnings: List[str]) -> tuple:
    """Returns (SLTS exec data in the same shape as the BD Slides entities, snapshot to save)."""
    col = _find_slts_col(fin_ws)
    if col is None:
        raise BoardPackError(f"Could not find the 'SLTS Amalgamated' column on '{fin_ws.title}'.")

    anchor = _find_row(fin_ws, lambda v: _norm(v) == "boardpackslides")
    if anchor is None:
        raise BoardPackError(f"Could not find the 'Board Pack Slides' section on '{fin_ws.title}'.")
    ytd_end = _block_end(fin_ws, anchor, "pat")
    ytd_rows = _label_rows(fin_ws, anchor, ytd_end)
    main_rows = _label_rows(fin_ws, 1, anchor - 1)

    month_start = _find_row(fin_ws, lambda v: _norm(v).startswith("month"), ytd_end)
    if month_start is None:
        raise BoardPackError(f"Could not find the 'Month {period.month_name}' block on '{fin_ws.title}'.")
    month_rows = _label_rows(fin_ws, month_start, _block_end(fin_ws, month_start, "pat"))

    def main_value(metric: str, offset: int) -> Optional[float]:
        return _num(_cell(fin_ws, main_rows[metric], col + offset)) if metric in main_rows else None

    ytd_act = _slts_amounts(fin_ws, ytd_rows, col)
    ytd_ly = _slts_amounts(fin_ws, ytd_rows, col + 1)
    for metric in ("exchange_gain", "other_income"):
        ytd_act[metric] = main_value(metric, 0)
        ytd_ly[metric] = main_value(metric, 1)

    month_act = _slts_amounts(fin_ws, month_rows, col)
    ytd_bud = _read_sltsl_budget(wb, period, warnings)

    # Month values that the workbook cannot give: this YTD less last month's YTD
    if period.month == 1:
        prev_act = prev_bud = dict.fromkeys(SLTS_EXEC_METRICS, 0.0)
    elif previous:
        prev_act, prev_bud = previous.get("ytd_act", {}), previous.get("ytd_bud", {})
    else:
        # No saved previous month: month budget is the YTD budget averaged over the months so far
        prev_act = prev_bud = None

    if prev_bud is not None:
        month_bud = _subtract(ytd_bud, prev_bud)
    else:
        month_bud = {m: (v / period.month if v is not None else None) for m, v in ytd_bud.items()}

    # The month block's EBIT row less Operating Profit is the month's Other Income + Exchange Gain
    month_ebit_row = _num(_cell(fin_ws, month_rows["ebit"], col)) if "ebit" in month_rows else None
    non_operating = (month_ebit_row - month_act["ebit"]
                     if month_ebit_row is not None and month_act["ebit"] is not None else None)
    if prev_act is not None:
        month_other = _subtract({"other_income": ytd_act["other_income"]}, prev_act)["other_income"]
    else:
        month_other = 0.0
    month_act["other_income"] = month_other
    month_act["exchange_gain"] = (non_operating - month_other
                                  if non_operating is not None and month_other is not None else None)

    ytd = {m: {"act": ytd_act.get(m), "ly": ytd_ly.get(m), "bud": ytd_bud.get(m)} for m in SLTS_EXEC_METRICS}
    month = {m: {"act": month_act.get(m), "bud": month_bud.get(m)} for m in SLTS_EXEC_METRICS}
    _with_margins(ytd, ["act", "ly", "bud"])
    _with_margins(month, ["act", "bud"])
    _apply_variances(ytd, {"ly": ("var_ly", "pct_ly"), "bud": ("var_bud", "pct_bud")})
    _apply_variances(month, {"bud": ("var_bud", "pct_bud")})

    snapshot = {"ytd_act": ytd_act, "ytd_bud": ytd_bud}
    return {"ytd": ytd, "month": month}, snapshot


def read_board_pack_workbook(
    file_path: str,
    load_snapshot: Optional[Callable[[Period], Optional[Dict[str, object]]]] = None,
) -> BoardPackData:
    """Reads the workbook. `load_snapshot(period)` returns the snapshot saved for that period, if any."""
    logger.info(f"Reading board pack workbook: {file_path}")
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
    except Exception as exc:
        raise BoardPackError(f"Could not open the workbook: {exc}") from exc

    visible = _visible_sheets(wb)
    if len(visible) < 2:
        raise BoardPackError("The workbook must have at least two visible tabs.")
    fin_ws, exec_ws = visible[0], visible[1]

    if not _norm(fin_ws.title).startswith("income"):
        raise BoardPackError(
            f"The first tab should be the 'INCOME Amalg YTD ...' sheet, found '{fin_ws.title}'."
        )
    if not _norm(exec_ws.title).startswith("bdslides"):
        raise BoardPackError(
            f"The second tab should be the 'BD Slides-SLT-Mobtel-Grp' sheet, found '{exec_ws.title}'."
        )

    period = _parse_period(_cell(exec_ws, 4, 1)) or _parse_period(_cell(fin_ws, 4, 1))
    if period is None:
        raise BoardPackError("Could not read the report period (e.g. Aug'26) from cell A4.")

    # A workbook saved by something other than Excel has formulas but no cached values.
    if _cell(exec_ws, _find_row(exec_ws, lambda v: _norm(v) == "revenue") or 1, 2) is None:
        raise BoardPackError(
            "The workbook has no calculated values. Open it in Excel, save it, and upload again."
        )

    warnings: List[str] = []
    exec_data = _read_exec_tab(exec_ws, warnings)
    previous = load_snapshot(period.previous_month) if load_snapshot and period.month > 1 else None
    exec_data["SLTS"], slts_snapshot = _read_slts_exec(wb, fin_ws, period, previous, warnings)

    return BoardPackData(
        period=period,
        exec=exec_data,
        fin=_read_fin_tab(fin_ws, warnings),
        slts={},  # kept for backward compatibility; SLTS data now lives in exec["SLTS"]
        sheets_used=[fin_ws.title, exec_ws.title, "SLTSL"],
        warnings=warnings,
        snapshot={"period": f"{period.year}-{period.month:02d}", **slts_snapshot},
    )
