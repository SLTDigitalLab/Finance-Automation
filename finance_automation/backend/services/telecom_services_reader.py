"""
Reader for Telecom Services (SLTS) financial data.

Sources:
  1. Telecom Services Information Excel (Detailed Information for PPT tab)
  2. SLTS PL Summary Excel (for period detection and validation)
  3. Balance Sheet / Cash Flow PowerPoint (Telecom Services BS CF_ SLTS.pptx)
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import openpyxl
from pptx import Presentation

from services.board_pack_classifier import _extract_period_from_text, _norm
from utils.logger import logger


class TelecomServicesReaderError(Exception):
    """Raised when Telecom Services inputs cannot be read or validated."""


@dataclass
class SLTSLineItem:
    label: str
    act: Optional[float] = None
    bud: Optional[float] = None
    var: Optional[float] = None
    var_pct: Optional[float] = None
    ly_act: Optional[float] = None
    is_total: bool = False


@dataclass
class TelecomServicesData:
    month_label: str       # e.g. "Oct"
    current_year: int      # e.g. 2026
    previous_year: int     # e.g. 2025
    short_year: str        # e.g. "26"
    short_prev_year: str   # e.g. "25"

    revenue_items: List[SLTSLineItem] = field(default_factory=list)
    direct_cost_items: List[SLTSLineItem] = field(default_factory=list)
    sm_items: List[SLTSLineItem] = field(default_factory=list)
    admin_items: List[SLTSLineItem] = field(default_factory=list)
    other_cost_items: List[SLTSLineItem] = field(default_factory=list)

    bscf_pptx_path: Optional[str] = None
    subscribers_data: Dict[str, Tuple[Optional[int], Optional[int]]] = field(default_factory=dict)

    sheets_used: List[str] = field(default_factory=list)
    files_used: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _to_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).strip().replace(",", "")
    if text in ("-", "–", "—", "#DIV/0!", "#VALUE!", "#REF!", "#N/A"):
        return 0.0
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1].strip()
    try:
        return float(text)
    except ValueError:
        return None


def _find_sheet(wb, target_name: str):
    for s in wb.sheetnames:
        if target_name in _norm(s):
            return wb[s]
    return None


def read_telecom_services_inputs(
    info_excel_path: str,
    pl_excel_path: Optional[str] = None,
    bscf_pptx_path: Optional[str] = None,
) -> TelecomServicesData:
    """Reads Telecom Services data from the supplied files."""
    logger.info(f"Reading Telecom Services info workbook: {info_excel_path}")
    files_used = [Path(info_excel_path).name]
    sheets_used = []

    try:
        wb_info = openpyxl.load_workbook(info_excel_path, data_only=True)
    except Exception as exc:
        raise TelecomServicesReaderError(f"Could not open Telecom Services Info workbook: {exc}") from exc

    ws_info = _find_sheet(wb_info, "detailedinformationforppt")
    if not ws_info:
        ws_info = wb_info.active
        if not ws_info:
            raise TelecomServicesReaderError("Missing 'Detailed Information for PPT' sheet in info workbook.")
    sheets_used.append(ws_info.title)

    # 1. Detect period from PL Excel, BS/CF PPTX, or Info Excel
    period: Optional[Tuple[str, int]] = None
    if pl_excel_path and Path(pl_excel_path).exists():
        files_used.append(Path(pl_excel_path).name)
        try:
            wb_pl = openpyxl.load_workbook(pl_excel_path, data_only=True)
            for s in wb_pl.sheetnames:
                ws = wb_pl[s]
                for r in range(1, 6):
                    for c in range(1, 10):
                        val = str(ws.cell(r, c).value or "")
                        p = _extract_period_from_text(val)
                        if p:
                            period = p
                            sheets_used.append(ws.title)
                            break
                    if period:
                        break
                if period:
                    break
            wb_pl.close()
        except Exception as e:
            logger.warning(f"Could not parse period from PL Excel: {e}")

    if not period and bscf_pptx_path and Path(bscf_pptx_path).exists():
        try:
            prs = Presentation(bscf_pptx_path)
            for slide in prs.slides:
                for sh in slide.shapes:
                    if sh.has_table:
                        for row in sh.table.rows:
                            for cell in row.cells:
                                p = _extract_period_from_text(cell.text)
                                if p:
                                    period = p
                                    break
                            if period:
                                break
                    if period:
                        break
                if period:
                    break
        except Exception as e:
            logger.warning(f"Could not parse period from BS/CF PPTX: {e}")

    if not period:
        # Fallback to info excel headers
        for r in range(1, 8):
            for c in range(1, 8):
                val = str(ws_info.cell(r, c).value or "")
                p = _extract_period_from_text(val)
                if p:
                    period = p
                    break
            if period:
                break

    if not period:
        # Default fallback to October 2026 if no date found
        period = ("Oct", 2026)

    month_label = period[0]
    current_year = period[1]
    previous_year = current_year - 1
    short_year = str(current_year)[-2:]
    short_prev_year = str(previous_year)[-2:]

    # 2. Parse Detailed Information for PPT sections dynamically
    # Identify header rows (containing 'Actual' or 'Budgeted' in cols B..F)
    max_r = ws_info.max_row or 80

    sections_data: Dict[str, List[SLTSLineItem]] = {
        "revenue": [],
        "direct_cost": [],
        "sm": [],
        "admin": [],
        "other": [],
    }

    # Find the 5 section blocks
    # We can detect each section's header row
    header_rows = []
    for r in range(1, max_r + 1):
        row_vals = [str(ws_info.cell(r, c).value or "").lower() for c in range(1, 8)]
        if any("actual" in v for v in row_vals) and any("budget" in v for v in row_vals):
            header_rows.append(r)

    # If 5 header rows found, map directly:
    # 0 -> revenue, 1 -> direct_cost, 2 -> sm, 3 -> admin, 4 -> other
    sec_keys = ["revenue", "direct_cost", "sm", "admin", "other"]

    def parse_rows(start_r: int, end_r: int) -> List[SLTSLineItem]:
        items: List[SLTSLineItem] = []
        for r in range(start_r, end_r):
            lbl = ws_info.cell(r, 1).value
            lbl_str = str(lbl or "").strip()
            norm_l = _norm(lbl_str)

            # Check if this row is a total row or data row
            act_val = _to_float(ws_info.cell(r, 2).value)
            bud_val = _to_float(ws_info.cell(r, 3).value)
            var_val = _to_float(ws_info.cell(r, 4).value)
            pct_val = _to_float(ws_info.cell(r, 5).value)
            ly_val = _to_float(ws_info.cell(r, 6).value)

            # If all numeric columns are empty, skip
            if act_val is None and bud_val is None and ly_val is None:
                continue

            # If label is empty but values exist, it's typically a Total row
            if not lbl_str:
                lbl_str = "Total"
                norm_l = "total"

            if var_val is None and act_val is not None and bud_val is not None:
                var_val = act_val - bud_val
            if pct_val is None and var_val is not None and bud_val:
                pct_val = var_val / bud_val

            is_tot = "total" in norm_l or "netimpact" in norm_l or "pbt" in norm_l
            items.append(
                SLTSLineItem(
                    label=lbl_str,
                    act=act_val,
                    bud=bud_val,
                    var=var_val,
                    var_pct=pct_val,
                    ly_act=ly_val,
                    is_total=is_tot,
                )
            )
        return items

    if len(header_rows) >= 5:
        for i, key in enumerate(sec_keys):
            h_row = header_rows[i]
            next_limit = header_rows[i + 1] if i + 1 < len(header_rows) else max_r + 1
            sections_data[key] = parse_rows(h_row + 1, next_limit)
    else:
        # Fallback: scan by section names / labels
        curr_key = "revenue"
        for r in range(1, max_r + 1):
            lbl = str(ws_info.cell(r, 1).value or "").strip()
            norm_l = _norm(lbl)
            if "directcost" in norm_l:
                curr_key = "direct_cost"
            elif "sales" in norm_l and "marketing" in norm_l:
                curr_key = "sm"
            elif "admin" in norm_l:
                curr_key = "admin"
            elif "othercost" in norm_l or "impacttonetprofit" in norm_l:
                curr_key = "other"

            act_val = _to_float(ws_info.cell(r, 2).value)
            if act_val is not None:
                bud_val = _to_float(ws_info.cell(r, 3).value)
                var_val = _to_float(ws_info.cell(r, 4).value)
                pct_val = _to_float(ws_info.cell(r, 5).value)
                ly_val = _to_float(ws_info.cell(r, 6).value)
                is_tot = "total" in norm_l or not lbl
                sections_data[curr_key].append(
                    SLTSLineItem(
                        label=lbl or "Total",
                        act=act_val,
                        bud=bud_val,
                        var=var_val,
                        var_pct=pct_val,
                        ly_act=ly_val,
                        is_total=is_tot,
                    )
                )

    if bscf_pptx_path and Path(bscf_pptx_path).exists():
        files_used.append(Path(bscf_pptx_path).name)

    return TelecomServicesData(
        month_label=month_label,
        current_year=current_year,
        previous_year=previous_year,
        short_year=short_year,
        short_prev_year=short_prev_year,
        revenue_items=sections_data["revenue"],
        direct_cost_items=sections_data["direct_cost"],
        sm_items=sections_data["sm"],
        admin_items=sections_data["admin"],
        other_cost_items=sections_data["other"],
        bscf_pptx_path=bscf_pptx_path,
        subscribers_data={},
        sheets_used=sheets_used,
        files_used=files_used,
        warnings=[],
    )
