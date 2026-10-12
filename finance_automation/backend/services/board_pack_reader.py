"""
Reads the monthly "Sub workings" workbook for the Finance Board Pack.

Data sources (visible tabs only — hidden legacy tabs are skipped):
  Tab 1  INCOME Amalg YTD <Mon> <Year>  -> Group Financials slides (actual vs last year)
  Tab 2  BD Slides-SLT-Mobtel-Grp       -> Executive Summary slides (actual vs budget)
  SLTSL                                 -> Executive Summary - SLTS (YTD actual only)

Rows are located by their labels in column A (column B for SLTSL) and entity
columns by their header text, so the reader keeps working when rows or
columns move between months.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

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
    "exchangegainloss": "exchange_gain",
    "otherincome": "other_income",
    "taxation": "taxation",
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
    "other_income", "taxation", "npat", "ebitda_margin", "ebit_margin", "npat_margin",
]
FIN_AMOUNT_METRICS = [
    "revenue", "direct_cost", "gross_profit", "selling_admin", "ebitda",
    "dep_amort", "operating_profit", "ebit", "npat",
]
FIN_MARGIN_METRICS = ["gp_margin", "ebitda_margin", "operating_margin", "npat_margin"]

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
        data[entity] = {
            "ytd": _read_values(ws, ytd_rows, ytd_cols[entity], EXEC_OFFSETS, EXEC_METRICS,
                                f"{entity} YTD", warnings),
            "month": _read_values(ws, month_rows, month_cols[entity], EXEC_OFFSETS, EXEC_METRICS,
                                  f"{entity} month", warnings),
        }
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


def _read_slts_tab(wb, period: Period, warnings: List[str]) -> Dict[str, Optional[float]]:
    """
    SLTS YTD actuals from the 'For the Period of <Mon> <Year>' column of the SLTSL tab,
    restated into the Executive Summary layout.
    """
    empty = {m: None for m in EXEC_METRICS + ["exchange_gain"]}
    ws = next((s for s in wb.worksheets if _norm(s.title) == "sltsl"), None)
    if ws is None:
        warnings.append("SLTSL tab not found - the SLTS slide was left blank.")
        return empty

    header_row = col = None
    header_text = ""
    for r in range(1, min(ws.max_row, 15) + 1):
        for c in range(1, ws.max_column + 1):
            text = str(_cell(ws, r, c) or "")
            if _norm(text).startswith("fortheperiodof"):
                header_row, col, header_text = r, c, text
                break
        if col:
            break
    if col is None:
        warnings.append("SLTSL: 'For the Period of ...' column not found - the SLTS slide was left blank.")
        return empty

    stated = _parse_period(re.sub(r"(?i)^\s*for the period of\s*", "", header_text))
    if stated and (stated.month, stated.year) != (period.month, period.year):
        warnings.append(f"SLTSL: column is '{header_text}' but the board pack period is {period.label}.")

    rows: Dict[str, int] = {}
    for r in range(header_row + 1, ws.max_row + 1):
        label = _norm(_cell(ws, r, 2))
        if label and label not in rows:
            rows[label] = r

    def val(label: str) -> float:
        r = rows.get(label)
        v = _cell(ws, r, col) if r else None
        if r is None or not isinstance(v, (int, float)):
            raise BoardPackError(f"SLTSL: '{label}' has no numeric value in column {header_text!r}.")
        return float(v)

    try:
        revenue = val("revenue")
        opex = val("directcosts") + val("opex")
        ebitda = val("ebitda")
        dep = val("depreciationamortization")
        interest = val("interestincomecost")
        exchange = val("exchangegainloss")
        other = val("nonoperatingincome")
        tax = val("incometax")
        pbt = val("pbt")
        pat = val("pat")
    except BoardPackError as exc:
        warnings.append(f"{exc} The SLTS slide was left blank.")
        return empty

    ebit = pbt - interest

    def margin(x: float):
        return x / revenue if revenue else "#DIV/0!"

    return {
        "revenue": revenue,
        "operating_cost": -opex,
        "ebitda": ebitda,
        "dep_amort": -dep,
        "ebit": ebit,
        "net_finance_cost": interest,
        "exchange_gain": exchange,
        "other_income": other,
        "taxation": tax,
        "npat": pat,
        "ebitda_margin": margin(ebitda),
        "ebit_margin": margin(ebit),
        "npat_margin": margin(pat),
    }


def read_board_pack_workbook(file_path: str) -> BoardPackData:
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
    data = BoardPackData(
        period=period,
        exec=_read_exec_tab(exec_ws, warnings),
        fin=_read_fin_tab(fin_ws, warnings),
        slts={},
        sheets_used=[fin_ws.title, exec_ws.title],
        warnings=warnings,
    )
    data.slts = _read_slts_tab(wb, period, warnings)
    if data.slts.get("revenue") is not None:
        data.sheets_used.append("SLTSL")
    return data
