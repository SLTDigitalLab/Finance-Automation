"""
Reads the monthly "Sub workings" workbook for the Finance Board Pack.

Data sources (visible tabs only — hidden legacy tabs are skipped):
  Tab 1  INCOME Amalg YTD <Mon> <Year>  -> Group Financials slides (actual vs last year)
  Tab 2  BD Slides-SLT-Mobtel-Grp       -> Executive Summary slides (actual vs budget)
  SLTSL                                 -> Executive Summary – SLTS YTD budget

SLTS Executive Summary uses three sources:
  - YTD Actuals & Last Year: INCOME Amalg tab, SLTS Amalgamated column, Board Pack Slides section
  - Month Actuals & Last Year: INCOME Amalg tab, SLTS Amalgamated column, Month block
  - YTD & Month Budget: SLTSL tab, "For the Period of ..." column

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


# ---------------------------------------------------------------------------
# SLTS column offset mapping for INCOME Amalg Board Pack Slides block
# Col 36 = SLTS Amalgamated (2026 Actual), col 37 = 2025 LY
# ---------------------------------------------------------------------------
_SLTS_AMALG_ACT_OFFSET = 0   # col 36 relative to first SLTS col
_SLTS_AMALG_LY_OFFSET  = 1   # col 37 relative to first SLTS col


def _find_slts_col(ws) -> Optional[int]:
    """Return the column index of the SLTS Amalgamated (2026 actual) in INCOME Amalg."""
    for r in range(1, min(ws.max_row, 15) + 1):
        for c in range(1, ws.max_column + 1):
            text = _norm(str(_cell(ws, r, c) or ""))
            if "sltsamalgamated" in text or ("donotenter" in text and "sltsamalgamated" in text):
                return c
    return None


def _read_slts_exec(
    wb,
    fin_ws,
    period: Period,
    warnings: List[str],
) -> Dict[str, Dict[str, Dict[str, object]]]:
    """
    Build the full Executive Summary data structure for SLTS (equivalent to what
    _read_exec_tab produces for Group / SLT / Mobitel), drawing from three sources:

      • INCOME Amalg YTD tab  – YTD and Month actuals (col 36) and last-year (col 37)
      • SLTSL tab             – YTD budget ('For the Period of ...' column)

    The Month Budget is derived as SLTSL YTD budget ÷ period.month so that it is
    consistent with the annual budget pro-rated to the number of months elapsed.
    """
    def _empty_block(fields):
        return {m: {f: None for f in fields} for m in EXEC_METRICS}

    empty_ytd   = _empty_block(["act", "ly", "var_ly", "pct_ly", "bud", "var_bud", "pct_bud"])
    empty_month = _empty_block(["act", "bud", "var_bud", "pct_bud"])
    empty_result = {"ytd": empty_ytd, "month": empty_month}

    # ── Step 1: locate SLTS Amalgamated column in INCOME Amalg tab ──────────
    slts_act_col = _find_slts_col(fin_ws)
    if slts_act_col is None:
        warnings.append(
            "INCOME Amalg: SLTS Amalgamated column not found – SLTS slide left blank."
        )
        return empty_result
    slts_ly_col = slts_act_col + 1  # col 37 = 2025 LY

    # ── Step 2: locate the Board Pack Slides block and Month block ───────────
    bp_anchor = _find_row(fin_ws, lambda v: _norm(v) == "boardpackslides")
    if bp_anchor is None:
        warnings.append("INCOME Amalg: 'Board Pack Slides' row not found – SLTS slide left blank.")
        return empty_result

    ytd_end   = _block_end(fin_ws, bp_anchor, "pat")
    ytd_rows  = _label_rows(fin_ws, bp_anchor, ytd_end)

    # Also scan main P&L section (above Board Pack Slides) for exchange_gain / other_income
    # These rows are not repeated in the Board Pack Slides block for SLTS.
    main_rows = _label_rows(fin_ws, 1, bp_anchor - 1)

    month_anchor = _find_row(
        fin_ws, lambda v: _norm(str(v or "")).startswith("month"), ytd_end
    )
    if month_anchor is None:
        warnings.append("INCOME Amalg: 'Month ...' block not found – SLTS month data left blank.")
        month_rows = {}
    else:
        month_end  = _find_row(fin_ws, lambda v: _norm(v) == "pat", month_anchor)
        month_end  = month_end or (month_anchor + 30)
        month_rows = _label_rows(fin_ws, month_anchor, month_end)

    # ── Step 3: read YTD Budget from SLTSL tab ──────────────────────────────
    ws_sltsl = next((s for s in wb.worksheets if _norm(s.title) == "sltsl"), None)
    ytd_bud: Dict[str, Optional[float]] = {m: None for m in EXEC_METRICS}
    if ws_sltsl is None:
        warnings.append("SLTSL tab not found – SLTS YTD budget left blank.")
    else:
        # Locate 'For the Period of ...' column header (usually row 6, some col)
        bud_col = bud_hdr = bud_hdr_row = None
        for r in range(1, min(ws_sltsl.max_row, 12) + 1):
            for c in range(1, ws_sltsl.max_column + 1):
                text = str(_cell(ws_sltsl, r, c) or "")
                if _norm(text).startswith("fortheperiodof"):
                    bud_col, bud_hdr, bud_hdr_row = c, text, r
                    break
            if bud_col:
                break

        if bud_col is None:
            warnings.append("SLTSL: 'For the Period of ...' column not found – SLTS YTD budget left blank.")
        else:
            stated = _parse_period(re.sub(r"(?i)^\s*for the period of\s*", "", bud_hdr))
            if stated and (stated.month, stated.year) != (period.month, period.year):
                warnings.append(
                    f"SLTSL: column is '{bud_hdr}' but the board pack period is {period.label}."
                )

            # Build row-label map from column B (SLTSL uses col B for labels)
            sltsl_rows: Dict[str, int] = {}
            for r in range(bud_hdr_row + 1, ws_sltsl.max_row + 1):
                lbl = _norm(_cell(ws_sltsl, r, 2))
                if lbl and lbl not in sltsl_rows:
                    sltsl_rows[lbl] = r

            def _sltsl_val(label: str) -> Optional[float]:
                r = sltsl_rows.get(label)
                if r is None:
                    return None
                v = _cell(ws_sltsl, r, bud_col)
                return float(v) if isinstance(v, (int, float)) else None

            try:
                bud_rev  = _sltsl_val("revenue")
                bud_dc   = _sltsl_val("directcosts")
                bud_opex = _sltsl_val("opex")
                bud_ebitda = _sltsl_val("ebitda")
                bud_dep  = _sltsl_val("depreciationamortization")
                bud_ebit = _sltsl_val("operatingprofit")  # 'Operating Profit' in SLTSL
                bud_nfc  = _sltsl_val("interestincomecost")
                bud_exch = _sltsl_val("exchangegainloss")
                bud_other = _sltsl_val("nonoperatingincome")
                bud_tax  = _sltsl_val("incometax")
                bud_pat  = _sltsl_val("pat")

                # SLTSL uses Direct Costs + OPEX = total operating cost
                bud_opex_total = None
                if bud_dc is not None and bud_opex is not None:
                    bud_opex_total = bud_dc + bud_opex
                elif bud_dc is not None:
                    bud_opex_total = bud_dc

                def _marg(num, denom):
                    if num is None or denom is None or denom == 0:
                        return "#DIV/0!"
                    return num / denom

                # SLTSL costs (direct_cost, opex, dep, tax) are already stored as negative
                # values in the SLTSL sheet, so use them directly without additional negation.
                ytd_bud["revenue"]          = bud_rev
                ytd_bud["operating_cost"]   = bud_opex_total  # already negative
                ytd_bud["ebitda"]           = bud_ebitda
                ytd_bud["dep_amort"]        = bud_dep         # already negative
                ytd_bud["ebit"]             = bud_ebit
                ytd_bud["net_finance_cost"]  = bud_nfc
                ytd_bud["exchange_gain"]    = bud_exch
                ytd_bud["other_income"]     = bud_other
                ytd_bud["taxation"]         = bud_tax
                ytd_bud["npat"]             = bud_pat
                ytd_bud["ebitda_margin"]   = _marg(bud_ebitda, bud_rev)
                ytd_bud["ebit_margin"]     = _marg(bud_ebit, bud_rev)
                ytd_bud["npat_margin"]     = _marg(bud_pat, bud_rev)
            except Exception as exc:  # pragma: no cover
                warnings.append(f"SLTSL budget read error: {exc} – SLTS YTD budget left blank.")

    # ── Step 4: assemble the exec data structure ─────────────────────────────
    months_elapsed = period.month  # e.g. 8 for August

    def _amalg_val(rows_map, metric, col_offset):
        """Read a single metric from INCOME Amalg using the SLTS col + offset."""
        r = rows_map.get(metric)
        if r is None:
            return None
        col = slts_act_col + col_offset
        v = _cell(fin_ws, r, col)
        return float(v) if isinstance(v, (int, float)) else None

    def _build_ytd():
        result: Dict[str, Dict[str, object]] = {}

        # Metrics read directly from INCOME Amalg SLTS column
        direct_metrics = [
            "revenue", "ebitda", "dep_amort", "ebit",
            "net_finance_cost", "taxation", "npat",
        ]

        for metric in EXEC_METRICS:
            if metric.endswith("_margin"):
                result.setdefault(metric, {"act": None, "ly": None, "var_ly": None,
                                           "pct_ly": None, "bud": None, "var_bud": None,
                                           "pct_bud": None})
                continue

            if metric == "operating_cost":
                # INCOME Amalg SLTS uses positive cost rows; negate to match sign convention
                dc_act  = _amalg_val(ytd_rows, "direct_cost",  _SLTS_AMALG_ACT_OFFSET)
                sa_act  = _amalg_val(ytd_rows, "selling_admin", _SLTS_AMALG_ACT_OFFSET)
                dc_ly   = _amalg_val(ytd_rows, "direct_cost",  _SLTS_AMALG_LY_OFFSET)
                sa_ly   = _amalg_val(ytd_rows, "selling_admin", _SLTS_AMALG_LY_OFFSET)
                # Store as negative (costs shown as (x) in the slide)
                raw_act = (dc_act + sa_act) if dc_act is not None and sa_act is not None else None
                raw_ly  = (dc_ly  + sa_ly)  if dc_ly  is not None and sa_ly  is not None else None
                act = (-raw_act) if raw_act is not None else None
                ly  = (-raw_ly)  if raw_ly  is not None else None
            elif metric == "dep_amort":
                # Dep & Amort is positive in INCOME Amalg SLTS; negate to show as (x)
                raw_act = _amalg_val(ytd_rows, "dep_amort", _SLTS_AMALG_ACT_OFFSET)
                raw_ly  = _amalg_val(ytd_rows, "dep_amort", _SLTS_AMALG_LY_OFFSET)
                act = (-raw_act) if raw_act is not None else None
                ly  = (-raw_ly)  if raw_ly  is not None else None
            elif metric == "ebit":
                # SLTS Executive Summary slide maps 'EBIT' to Operating Profit (EBITDA - Dep)
                # not to the actual EBIT row (which includes other adjustments).
                # Row 67 in INCOME Amalg SLTS = 'Operating profit' = EBITDA - Dep & Amort
                act = _amalg_val(ytd_rows, "operating_profit", _SLTS_AMALG_ACT_OFFSET)
                ly  = _amalg_val(ytd_rows, "operating_profit", _SLTS_AMALG_LY_OFFSET)
            elif metric == "other_income":
                # INCOME Amalg Board Pack Slides SLTS block doesn't have Other Income;
                # read from the main P&L section above the Board Pack Slides anchor.
                act = _amalg_val(main_rows, "other_income", _SLTS_AMALG_ACT_OFFSET)
                ly  = _amalg_val(main_rows, "other_income", _SLTS_AMALG_LY_OFFSET)
            elif metric == "exchange_gain":
                # Same: exchange gain is only in the main P&L section.
                act = _amalg_val(main_rows, "exchange_gain", _SLTS_AMALG_ACT_OFFSET)
                ly  = _amalg_val(main_rows, "exchange_gain", _SLTS_AMALG_LY_OFFSET)
            elif metric in direct_metrics:
                act = _amalg_val(ytd_rows, metric, _SLTS_AMALG_ACT_OFFSET)
                ly  = _amalg_val(ytd_rows, metric, _SLTS_AMALG_LY_OFFSET)
            else:
                act = ly = None

            bud = ytd_bud.get(metric)
            var_ly  = (act - ly)  if act is not None and ly  is not None else None
            pct_ly  = (var_ly / abs(ly)) if var_ly is not None and ly  not in (None, 0) else (
                "#DIV/0!" if ly == 0 else None
            )
            var_bud = (act - bud) if act is not None and bud is not None else None
            pct_bud = (var_bud / abs(bud)) if var_bud is not None and bud not in (None, 0) else (
                "#DIV/0!" if bud == 0 else None
            )
            result[metric] = {
                "act": act, "ly": ly, "var_ly": var_ly, "pct_ly": pct_ly,
                "bud": bud, "var_bud": var_bud, "pct_bud": pct_bud,
            }

        # Compute margin rows from assembled amounts
        rev_d = result.get("revenue", {})
        for marg_key, num_key in (
            ("ebitda_margin", "ebitda"), ("ebit_margin", "ebit"), ("npat_margin", "npat")
        ):
            nd = result.get(num_key, {})

            def _m(n, d, _nd=nd, _rev=rev_d):
                if n is None or d is None or d == 0:
                    return "#DIV/0!" if d == 0 else None
                return n / d

            act_m  = _m(nd.get("act"),  rev_d.get("act"))
            ly_m   = _m(nd.get("ly"),   rev_d.get("ly"))
            bud_m  = ytd_bud.get(marg_key)
            var_ly_m  = (act_m  - ly_m)  if isinstance(act_m,  float) and isinstance(ly_m,  float) else None
            var_bud_m = (act_m  - bud_m) if isinstance(act_m,  float) and isinstance(bud_m, float) else None
            result[marg_key] = {
                "act": act_m, "ly": ly_m, "var_ly": None, "pct_ly": var_ly_m,
                "bud": bud_m, "var_bud": None, "pct_bud": var_bud_m,
            }
        # exchange_gain is SLTS-only (not in EXEC_METRICS). Add it separately.
        eg_act = _amalg_val(main_rows, "exchange_gain", _SLTS_AMALG_ACT_OFFSET)
        eg_ly  = _amalg_val(main_rows, "exchange_gain", _SLTS_AMALG_LY_OFFSET)
        eg_bud = ytd_bud.get("exchange_gain")
        eg_var_ly  = (eg_act - eg_ly)  if eg_act is not None and eg_ly  is not None else None
        eg_pct_ly  = (eg_var_ly / abs(eg_ly)) if eg_var_ly is not None and eg_ly not in (None, 0) else None
        eg_var_bud = (eg_act - eg_bud) if eg_act is not None and eg_bud is not None else None
        eg_pct_bud = (eg_var_bud / abs(eg_bud)) if eg_var_bud is not None and eg_bud not in (None, 0) else None
        result["exchange_gain"] = {
            "act": eg_act, "ly": eg_ly, "var_ly": eg_var_ly, "pct_ly": eg_pct_ly,
            "bud": eg_bud, "var_bud": eg_var_bud, "pct_bud": eg_pct_bud,
        }
        return result

    def _build_month():
        result: Dict[str, Dict[str, object]] = {}

        direct_metrics = [
            "revenue", "ebitda", "dep_amort", "ebit",
            "net_finance_cost", "taxation", "npat",
        ]

        for metric in EXEC_METRICS:
            if metric.endswith("_margin"):
                result.setdefault(metric, {"act": None, "bud": None, "var_bud": None, "pct_bud": None})
                continue

            if metric == "operating_cost":
                dc_act = _amalg_val(month_rows, "direct_cost",  _SLTS_AMALG_ACT_OFFSET)
                sa_act = _amalg_val(month_rows, "selling_admin", _SLTS_AMALG_ACT_OFFSET)
                raw_act = (dc_act + sa_act) if dc_act is not None and sa_act is not None else None
                act = (-raw_act) if raw_act is not None else None
            elif metric == "dep_amort":
                raw_act = _amalg_val(month_rows, "dep_amort", _SLTS_AMALG_ACT_OFFSET)
                act = (-raw_act) if raw_act is not None else None
            elif metric == "ebit":
                # Map to operating_profit row, same as YTD
                act = _amalg_val(month_rows, "operating_profit", _SLTS_AMALG_ACT_OFFSET)
            elif metric in ("other_income", "exchange_gain"):
                # Read from main P&L section, not from Board Pack Slides SLTS block
                act = _amalg_val(main_rows, metric, _SLTS_AMALG_ACT_OFFSET)
            elif metric in direct_metrics:
                act = _amalg_val(month_rows, metric, _SLTS_AMALG_ACT_OFFSET)
            else:
                act = None

            # Month budget = YTD budget / months elapsed (pro-rated)
            ytd_b = ytd_bud.get(metric)
            bud = (ytd_b / months_elapsed) if ytd_b is not None and months_elapsed else None

            var_bud = (act - bud) if act is not None and bud is not None else None
            pct_bud = (var_bud / abs(bud)) if var_bud is not None and bud not in (None, 0) else (
                "#DIV/0!" if bud == 0 else None
            )
            result[metric] = {"act": act, "bud": bud, "var_bud": var_bud, "pct_bud": pct_bud}

        # Compute margin rows for month block
        rev_d = result.get("revenue", {})
        for marg_key, num_key in (
            ("ebitda_margin", "ebitda"), ("ebit_margin", "ebit"), ("npat_margin", "npat")
        ):
            nd = result.get(num_key, {})

            def _m(n, d, _nd=nd, _rev=rev_d):
                if n is None or d is None or d == 0:
                    return "#DIV/0!" if d == 0 else None
                return n / d

            act_m = _m(nd.get("act"), rev_d.get("act"))
            bud_m = _m(nd.get("bud"), rev_d.get("bud"))
            var_m = (act_m - bud_m) if isinstance(act_m, float) and isinstance(bud_m, float) else None
            result[marg_key] = {"act": act_m, "bud": bud_m, "var_bud": None, "pct_bud": var_m}
        # exchange_gain: no monthly block row in INCOME Amalg SLTS; leave act as None
        eg_act = None
        eg_bud_ytd = ytd_bud.get("exchange_gain")
        eg_bud_m = (eg_bud_ytd / months_elapsed) if eg_bud_ytd is not None and months_elapsed else None
        eg_var = (eg_act - eg_bud_m) if eg_act is not None and eg_bud_m is not None else None
        eg_pct = (eg_var / abs(eg_bud_m)) if eg_var is not None and eg_bud_m not in (None, 0) else None
        result["exchange_gain"] = {"act": eg_act, "bud": eg_bud_m, "var_bud": eg_var, "pct_bud": eg_pct}
        return result

    try:
        return {"ytd": _build_ytd(), "month": _build_month()}
    except BoardPackError as exc:
        warnings.append(f"{exc} SLTS slide left blank.")
        return empty_result


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
    exec_data = _read_exec_tab(exec_ws, warnings)

    # Read SLTS full exec data and merge into exec dict
    slts_exec = _read_slts_exec(wb, fin_ws, period, warnings)
    exec_data["SLTS"] = slts_exec

    data = BoardPackData(
        period=period,
        exec=exec_data,
        fin=_read_fin_tab(fin_ws, warnings),
        slts={},  # kept for backward compatibility; SLTS data now lives in exec["SLTS"]
        sheets_used=[fin_ws.title, exec_ws.title],
        warnings=warnings,
    )
    # Mark SLTSL as used if we got at least revenue YTD actuals
    slts_rev = slts_exec.get("ytd", {}).get("revenue", {}).get("act")
    if slts_rev is not None:
        data.sheets_used.append("SLTSL")
    return data
