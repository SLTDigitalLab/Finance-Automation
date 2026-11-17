"""
Reader for Mobitel Mobile Business financial data.

Extracts data from:
  - SLT Presentation
  - BS
  - CF
  - Subscriber
Excludes:
  - SLT Income Stat.
  - Network cost
(Regardless of tab colors)
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Any

import openpyxl

from services.board_pack_classifier import _extract_period_from_text, _norm
from utils.logger import logger


class MobitelReaderError(Exception):
    """Raised when the uploaded workbook cannot supply Mobitel slides."""


@dataclass
class FinancialLineItem:
    label: str
    month_act: Optional[float] = None
    month_ly: Optional[float] = None
    month_var: Optional[float] = None
    month_pct: Optional[float] = None
    ytd_act: Optional[float] = None
    ytd_ly: Optional[float] = None
    ytd_var: Optional[float] = None
    ytd_pct: Optional[float] = None
    is_total: bool = False
    month_act_fmt: str = ""
    month_ly_fmt: str = ""
    month_var_fmt: str = ""
    ytd_act_fmt: str = ""
    ytd_ly_fmt: str = ""
    ytd_var_fmt: str = ""


@dataclass
class BalanceSheetItem:
    label: str
    current: Optional[float] = None
    previous: Optional[float] = None
    is_total: bool = False


@dataclass
class CashFlowItem:
    label: str
    current: Optional[float] = None
    previous: Optional[float] = None


@dataclass
class MobitelData:
    month_label: str  # e.g. "Oct"
    month_full: str   # e.g. "October"
    current_year: int # e.g. 2026
    previous_year: int # e.g. 2025
    short_year: str    # e.g. "26"
    short_prev_year: str # e.g. "25"

    revenue_items: List[FinancialLineItem] = field(default_factory=list)
    direct_cost_items: List[FinancialLineItem] = field(default_factory=list)
    sm_items: List[FinancialLineItem] = field(default_factory=list)
    admin_items: List[FinancialLineItem] = field(default_factory=list)
    other_cost_items: List[FinancialLineItem] = field(default_factory=list)

    balance_sheet_items: List[BalanceSheetItem] = field(default_factory=list)
    bs_current_header: str = ""
    bs_prev_header: str = ""

    cash_flow_items: List[CashFlowItem] = field(default_factory=list)
    cf_current_header: str = ""
    cf_prev_header: str = ""

    subscribers: Dict[str, Tuple[Optional[int], Optional[int]]] = field(default_factory=dict)
    arpu: Dict[str, Tuple[Optional[float], Optional[float]]] = field(default_factory=dict)

    sheets_used: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _to_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip().replace(",", "")
    if text in ("-", "–", "—", "#DIV/0!", "#VALUE!", "#REF!", "#N/A"):
        return 0.0
    # Handle parentheses for negatives e.g. (123.45)
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1].strip()
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(val: Any) -> Optional[int]:
    f = _to_float(val)
    return int(round(f)) if f is not None else None


def read_mobitel_workbook(file_path: str) -> MobitelData:
    """Reads Mobitel data from the supplied workbook."""
    logger.info(f"Reading Mobitel workbook: {file_path}")
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
    except Exception as exc:
        raise MobitelReaderError(f"Could not open Mobitel workbook: {exc}") from exc

    sheet_map: Dict[str, Any] = {}
    for s in wb.sheetnames:
        norm_s = _norm(s)
        # Strictly ignore excluded sheets
        if "sltincomestat" in norm_s or "networkcost" in norm_s:
            continue
        if "sltpresentation" in norm_s:
            sheet_map["presentation"] = wb[s]
        elif norm_s == "bs":
            sheet_map["bs"] = wb[s]
        elif norm_s == "cf":
            sheet_map["cf"] = wb[s]
        elif "subscriber" in norm_s:
            sheet_map["subscriber"] = wb[s]

    if "presentation" not in sheet_map:
        raise MobitelReaderError("Workbook is missing required sheet: 'SLT Presentation'.")
    if "bs" not in sheet_map:
        raise MobitelReaderError("Workbook is missing required sheet: 'BS'.")
    if "cf" not in sheet_map:
        raise MobitelReaderError("Workbook is missing required sheet: 'CF'.")

    ws_pres = sheet_map["presentation"]
    ws_bs = sheet_map["bs"]
    ws_cf = sheet_map["cf"]
    ws_sub = sheet_map.get("subscriber")

    sheets_used = [ws_pres.title, ws_bs.title, ws_cf.title]
    if ws_sub:
        sheets_used.append(ws_sub.title)

    # 1. Detect period
    c1 = str(ws_pres.cell(1, 3).value or "")
    c3 = str(ws_pres.cell(3, 3).value or "")
    period = _extract_period_from_text(f"{c1} {c3}")
    if not period and ws_bs:
        bs_date = str(ws_bs.cell(3, 3).value or "")
        period = _extract_period_from_text(bs_date)

    if not period:
        raise MobitelReaderError("Could not determine reporting month and year from SLT Presentation or BS.")

    month_full = {
        "Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
        "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
        "Sep": "September", "Oct": "October", "Nov": "November", "Dec": "December",
    }.get(period[0], period[0])

    month_label = period[0]
    current_year = period[1]
    previous_year = current_year - 1
    short_year = str(current_year)[-2:]
    short_prev_year = str(previous_year)[-2:]

    # 2. Extract sections from SLT Presentation
    # Find section row ranges
    max_r = ws_pres.max_row or 100

    def parse_section(start_row: int, end_row: int) -> List[FinancialLineItem]:
        items: List[FinancialLineItem] = []
        for r in range(start_row, end_row + 1):
            label = ws_pres.cell(r, 1).value
            if not label or not str(label).strip():
                continue
            label_str = str(label).strip()
            norm_lbl = _norm(label_str)
            # Skip empty or spacer rows
            if not norm_lbl or norm_lbl in ("0", "none"):
                continue

            m_act_c = ws_pres.cell(r, 3)
            m_ly_c = ws_pres.cell(r, 4)
            m_var_c = ws_pres.cell(r, 6)
            m_pct_c = ws_pres.cell(r, 7)

            y_act_c = ws_pres.cell(r, 9)
            y_ly_c = ws_pres.cell(r, 10)
            y_var_c = ws_pres.cell(r, 12)
            y_pct_c = ws_pres.cell(r, 13)

            m_act = _to_float(m_act_c.value)
            m_ly = _to_float(m_ly_c.value)
            m_var = _to_float(m_var_c.value)
            m_pct = _to_float(m_pct_c.value)

            y_act = _to_float(y_act_c.value)
            y_ly = _to_float(y_ly_c.value)
            y_var = _to_float(y_var_c.value)
            y_pct = _to_float(y_pct_c.value)

            # Re-calculate variances dynamically if missing or verify
            if m_act is not None and m_ly is not None and m_var is None:
                m_var = m_act - m_ly
            if m_var is not None and m_ly:
                if m_pct is None:
                    m_pct = m_var / abs(m_ly)
                elif m_ly < 0 and m_var < 0 and m_pct > 0:
                    # In arithmetic (-var) / (-ly) = +pct, but in financial presentation
                    # an adverse cost overrun is adverse e.g. Bad Debt (828%), not +828%
                    m_pct = -m_pct

            if y_act is not None and y_ly is not None and y_var is None:
                y_var = y_act - y_ly
            if y_var is not None and y_ly:
                if y_pct is None:
                    y_pct = y_var / abs(y_ly)
                elif y_ly < 0 and y_var < 0 and y_pct > 0:
                    y_pct = -y_pct

            m_act_fmt = str(m_act_c.number_format or "")
            m_ly_fmt = str(m_ly_c.number_format or "")
            m_var_fmt = str(m_var_c.number_format or "")
            y_act_fmt = str(y_act_c.number_format or "")
            y_ly_fmt = str(y_ly_c.number_format or "")
            y_var_fmt = str(y_var_c.number_format or "")

            is_tot = "total" in norm_lbl or "impacttonetprofit" in norm_lbl
            items.append(
                FinancialLineItem(
                    label=label_str,
                    month_act=m_act,
                    month_ly=m_ly,
                    month_var=m_var,
                    month_pct=m_pct,
                    ytd_act=y_act,
                    ytd_ly=y_ly,
                    ytd_var=y_var,
                    ytd_pct=y_pct,
                    is_total=is_tot,
                    month_act_fmt=m_act_fmt,
                    month_ly_fmt=m_ly_fmt,
                    month_var_fmt=m_var_fmt,
                    ytd_act_fmt=y_act_fmt,
                    ytd_ly_fmt=y_ly_fmt,
                    ytd_var_fmt=y_var_fmt,
                )
            )
        return items

    # Locate section boundary rows dynamically
    rev_start, rev_end = 4, 14
    dc_start, dc_end = 20, 46
    sm_start, sm_end = 51, 59
    admin_start, admin_end = 65, 79
    other_start, other_end = 84, 92

    for r in range(1, max_r + 1):
        lbl = _norm(ws_pres.cell(r, 1).value)
        if "rentalincome" in lbl:
            rev_start = r
        elif "totalrevenue" in lbl:
            rev_end = r
        elif "outgoinghubbing" in lbl:
            dc_start = r
        elif "totaldirectcost" in lbl:
            dc_end = r
        elif "advertisingcosts" in lbl:
            sm_start = r
        elif "totalsellingexpenditure" in lbl:
            sm_end = r
        elif "staffcostotherthandirect" in lbl:
            admin_start = r
        elif "totaladministrativeexpenditure" in lbl:
            admin_end = r
        elif "depreciationandamortization" in lbl and r > 80:
            other_start = r
        elif "impacttonetprofit" in lbl:
            other_end = r

    revenue_items = parse_section(rev_start, rev_end)
    direct_cost_items = parse_section(dc_start, dc_end)
    sm_items = parse_section(sm_start, sm_end)
    admin_items = parse_section(admin_start, admin_end)
    other_cost_items = parse_section(other_start, other_end)

    # 3. Extract Balance Sheet
    bs_items: List[BalanceSheetItem] = []
    bs_current_header = f"{month_label}-{short_year}"
    bs_prev_header = f"Dec-{short_prev_year}"

    # Check date headers in row 3
    if ws_bs.cell(3, 3).value:
        p_c = _extract_period_from_text(str(ws_bs.cell(3, 3).value))
        if p_c:
            bs_current_header = f"{p_c[0]}-{str(p_c[1])[-2:]}"
    if ws_bs.cell(3, 4).value:
        p_p = _extract_period_from_text(str(ws_bs.cell(3, 4).value))
        if p_p:
            bs_prev_header = f"{p_p[0]}-{str(p_p[1])[-2:]}"

    bs_max_r = ws_bs.max_row or 30
    for r in range(4, bs_max_r + 1):
        lbl = ws_bs.cell(r, 2).value
        if not lbl or not str(lbl).strip():
            continue
        lbl_str = str(lbl).strip()
        norm_l = _norm(lbl_str)
        if not norm_l:
            continue
        c_val = _to_float(ws_bs.cell(r, 3).value)
        p_val = _to_float(ws_bs.cell(r, 4).value)
        is_tot = "total" in norm_l
        bs_items.append(
            BalanceSheetItem(
                label=lbl_str,
                current=c_val,
                previous=p_val,
                is_total=is_tot,
            )
        )

    # 4. Extract Cash Flow Statement
    cf_items: List[CashFlowItem] = []
    cf_current_header = f"{month_label}-{short_year}"
    cf_prev_header = f"{month_label}-{short_prev_year}"

    if ws_cf.cell(3, 3).value:
        p_c = _extract_period_from_text(str(ws_cf.cell(3, 3).value))
        if p_c:
            cf_current_header = f"{p_c[0]}-{str(p_c[1])[-2:]}"
    if ws_cf.cell(3, 4).value:
        p_p = _extract_period_from_text(str(ws_cf.cell(3, 4).value))
        if p_p:
            cf_prev_header = f"{p_p[0]}-{str(p_p[1])[-2:]}"

    cf_max_r = ws_cf.max_row or 25
    for r in range(4, cf_max_r + 1):
        lbl = ws_cf.cell(r, 2).value
        if not lbl or not str(lbl).strip():
            continue
        lbl_str = str(lbl).strip()
        if not _norm(lbl_str):
            continue
        c_val = _to_float(ws_cf.cell(r, 3).value)
        p_val = _to_float(ws_cf.cell(r, 4).value)
        cf_items.append(
            CashFlowItem(
                label=lbl_str,
                current=c_val,
                previous=p_val,
            )
        )

    # 5. Extract Subscribers and ARPU
    subscribers: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
    arpu: Dict[str, Tuple[Optional[float], Optional[float]]] = {}

    if ws_sub:
        col_curr = 3
        col_prev = 5
        max_c = ws_sub.max_column or 8
        # Dynamically detect year/month columns from header rows before data rows
        # Also track month-specific columns (e.g. 'Oct-26', 'Oct 26', '10' for month 10)
        month_num = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }.get(month_label, 0)
        month_col_candidates: Dict[int, int] = {}  # col -> candidate score

        for hr in range(1, (ws_sub.max_row or 10) + 1):
            row_text = "".join(str(ws_sub.cell(hr, c).value or "") for c in range(1, max_c + 1)).lower()
            if "prepaid" in row_text or "postpaid" in row_text:
                break
            for hc in range(1, max_c + 1):
                v = ws_sub.cell(hr, hc).value
                if v is None:
                    continue
                s = str(v).strip()
                s_norm = _norm(s)
                if s == str(current_year):
                    col_curr = hc
                elif s == str(previous_year):
                    col_prev = hc
                # Also check month+year combinations like 'Oct-26', 'Oct 26', 'Oct2026'
                elif month_label.lower() in s.lower() and str(current_year)[-2:] in s:
                    month_col_candidates[hc] = month_col_candidates.get(hc, 0) + 2
                elif month_label.lower() in s.lower() and str(current_year) in s:
                    month_col_candidates[hc] = month_col_candidates.get(hc, 0) + 3
                elif month_num > 0 and s_norm == str(month_num):
                    month_col_candidates[hc] = month_col_candidates.get(hc, 0) + 1

        # If we found stronger month-specific column candidates, prefer them
        if month_col_candidates:
            best_col = max(month_col_candidates, key=lambda c: month_col_candidates[c])
            col_curr = best_col

        for r in range(1, (ws_sub.max_row or 25) + 1):
            lbl = ws_sub.cell(r, 1).value
            if not lbl:
                lbl = ws_sub.cell(r, 2).value
            if not lbl:
                continue
            lbl_norm = _norm(str(lbl))
            if "prepaid" in lbl_norm:
                c_val = _to_int(ws_sub.cell(r, col_curr).value)
                p_val = _to_int(ws_sub.cell(r, col_prev).value)
                # Scan nearby columns if the detected column is None/zero (may be stale)
                if (c_val is None or c_val == 0) and max_c > col_curr:
                    for alt_c in range(col_curr + 1, min(col_curr + 4, max_c + 1)):
                        alt_v = _to_int(ws_sub.cell(r, alt_c).value)
                        if alt_v and alt_v > 0:
                            c_val = alt_v
                            break
                subscribers["prepaid"] = (c_val, p_val)
            elif "postpaid" in lbl_norm:
                c_val = _to_int(ws_sub.cell(r, col_curr).value)
                p_val = _to_int(ws_sub.cell(r, col_prev).value)
                if (c_val is None or c_val == 0) and max_c > col_curr:
                    for alt_c in range(col_curr + 1, min(col_curr + 4, max_c + 1)):
                        alt_v = _to_int(ws_sub.cell(r, alt_c).value)
                        if alt_v and alt_v > 0:
                            c_val = alt_v
                            break
                subscribers["postpaid"] = (c_val, p_val)
            elif "blended" in lbl_norm or "arpu" in lbl_norm:
                c_val = _to_float(ws_sub.cell(r, col_curr).value)
                p_val = _to_float(ws_sub.cell(r, col_prev).value)
                arpu["blended"] = (c_val, p_val)

    return MobitelData(
        month_label=month_label,
        month_full=month_full,
        current_year=current_year,
        previous_year=previous_year,
        short_year=short_year,
        short_prev_year=short_prev_year,
        revenue_items=revenue_items,
        direct_cost_items=direct_cost_items,
        sm_items=sm_items,
        admin_items=admin_items,
        other_cost_items=other_cost_items,
        balance_sheet_items=bs_items,
        bs_current_header=bs_current_header,
        bs_prev_header=bs_prev_header,
        cash_flow_items=cf_items,
        cf_current_header=cf_current_header,
        cf_prev_header=cf_prev_header,
        subscribers=subscribers,
        arpu=arpu,
        sheets_used=sheets_used,
        warnings=[],
    )
