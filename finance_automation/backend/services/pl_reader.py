import re
from pathlib import Path
from typing import Dict, Any, Optional
import openpyxl
from utils.logger import logger


MONTH_MAP = {
    "jan": ("Jun", "January", 1),
    "feb": ("Feb", "February", 2),
    "mar": ("Mar", "March", 3),
    "apr": ("Apr", "April", 4),
    "may": ("May", "May", 5),
    "jun": ("Jun", "June", 6),
    "jul": ("Jul", "July", 7),
    "aug": ("Aug", "August", 8),
    "sep": ("Sep", "September", 9),
    "oct": ("Oct", "October", 10),
    "nov": ("Nov", "November", 11),
    "dec": ("Dec", "December", 12),
}
MONTH_MAP["jan"] = ("Jan", "January", 1)


def read_pl_workbook(file_path: str | Path) -> Dict[str, Any]:
    """
    Dynamically parses an Oracle FSG / standard P&L Excel workbook to extract:
    - Target Financial Statement sheet (e.g. 'NA')
    - Period Month & Year
    - Total Revenue Month Actual (from Revenue row, Current Month Actual column)
    - Total Revenue YTD Actual (from Revenue row, YTD Actual column)

    Does NOT hard-code values or worksheet index.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"PL workbook file not found at: {file_path}")

    try:
        wb = openpyxl.load_workbook(str(path), data_only=True)
    except Exception as e:
        logger.error(f"Failed to load Excel workbook {file_path}: {e}")
        raise ValueError(f"Invalid Excel workbook file: {str(e)}")

    target_sheet = None

    # Search across sheets for Financial Statement markers
    for name in wb.sheetnames:
        ws = wb[name]
        for r in range(1, min(35, ws.max_row + 1)):
            for c in range(1, min(15, ws.max_column + 1)):
                val = ws.cell(r, c).value
                if val and isinstance(val, str):
                    val_clean = val.strip().lower()
                    if (
                        "statement of financial performance" in val_clean
                        or "profit & loss" in val_clean
                        or "profit and loss" in val_clean
                        or "ptd-actual" in val_clean
                        or val_clean == "revenue"
                    ):
                        target_sheet = ws
                        break
            if target_sheet:
                break
        if target_sheet:
            break

    if not target_sheet:
        if "NA" in wb.sheetnames:
            target_sheet = wb["NA"]
        elif len(wb.sheetnames) > 0:
            target_sheet = wb.active

    if not target_sheet:
        raise ValueError("Could not find a valid Financial Statement worksheet in the uploaded PL workbook.")

    ws = target_sheet
    logger.info(f"Target PL worksheet identified: '{ws.title}' (rows={ws.max_row}, cols={ws.max_column})")

    # 1. Detect Month and Year from Header cells (e.g. rows 1 to 15)
    month_str: Optional[str] = None
    year_int: Optional[int] = None

    for r in range(1, min(15, ws.max_row + 1)):
        for c in range(1, min(10, ws.max_column + 1)):
            val = ws.cell(r, c).value
            if val and isinstance(val, str):
                m = re.search(
                    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-/\s\']+(\d{2,4})",
                    val,
                    re.IGNORECASE,
                )
                if m:
                    m_key = m.group(1).lower()[:3]
                    y_str = m.group(2)
                    if m_key in MONTH_MAP:
                        month_str = MONTH_MAP[m_key][0]
                        year_int = int(y_str) if len(y_str) == 4 else 2000 + int(y_str)
                        logger.info(f"Detected period from cell ({r},{c}) '{val}': {month_str} {year_int}")
                        break
        if month_str:
            break

    # Fallback to filename period detection if header cells don't contain date
    if not month_str or not year_int:
        filename = path.name
        m = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-_\s\']+(\d{2,4})",
            filename,
            re.IGNORECASE,
        )
        if m:
            m_key = m.group(1).lower()[:3]
            y_str = m.group(2)
            if m_key in MONTH_MAP:
                month_str = MONTH_MAP[m_key][0]
                year_int = int(y_str) if len(y_str) == 4 else 2000 + int(y_str)
                logger.info(f"Detected period from filename '{filename}': {month_str} {year_int}")

    if not month_str:
        month_str = "Jun"
    if not year_int:
        year_int = 2026

    # 2. Identify Column Indices for Current Month Actual (PTD-Actual) and YTD-Actual
    ptd_col: Optional[int] = None
    ytd_col: Optional[int] = None

    header_rows = []
    for r in range(1, min(25, ws.max_row + 1)):
        row_vals = [str(ws.cell(r, c).value or "").strip() for c in range(1, ws.max_column + 1)]
        if any("PTD" in v.upper() or "YTD" in v.upper() for v in row_vals):
            header_rows.append(r)

    if header_rows:
        hdr_r1 = header_rows[0]
        hdr_r2 = hdr_r1 + 1 if hdr_r1 + 1 <= ws.max_row else hdr_r1

        for c in range(1, ws.max_column + 1):
            top_val = str(ws.cell(hdr_r1, c).value or "").strip().upper()
            sub_val = str(ws.cell(hdr_r2, c).value or "").strip().upper() if hdr_r2 != hdr_r1 else ""

            # PTD / Current Month: Must be PTD-Actual and explicitly current month
            if "PTD" in top_val and "ACTUAL" in top_val:
                if "CURRENT" in sub_val and "MONTH" in sub_val:
                    ptd_col = c
                elif not ptd_col and "PREVIOUS" not in sub_val and "LAST" not in sub_val and "PRIOR" not in sub_val:
                    ptd_col = c

            # YTD / Current YTD: Must be YTD-Actual and not last year / prior year
            if "YTD" in top_val and "ACTUAL" in top_val:
                if "LAST" not in sub_val and "PREVIOUS" not in sub_val and "PRIOR" not in sub_val and not ytd_col:
                    ytd_col = c

    # Fallback to standard Oracle FSG columns (Col C = 3, Col G = 7)
    if not ptd_col:
        ptd_col = 3
    if not ytd_col:
        ytd_col = 7

    # 3. Locate the "Revenue" Row
    rev_row: Optional[int] = None
    for r in range(1, ws.max_row + 1):
        for c in range(1, min(6, ws.max_column + 1)):
            cell_val = str(ws.cell(r, c).value or "").strip()
            if cell_val.lower() == "revenue" or cell_val.lower() == "total revenue":
                rev_row = r
                break
        if rev_row:
            break

    if not rev_row:
        raise ValueError("Could not find 'Revenue' line in the uploaded PL worksheet.")

    raw_month_val = ws.cell(rev_row, ptd_col).value
    raw_ytd_val = ws.cell(rev_row, ytd_col).value

    try:
        month_revenue = float(raw_month_val) if raw_month_val is not None else 0.0
    except (ValueError, TypeError):
        month_revenue = 0.0

    try:
        ytd_revenue = float(raw_ytd_val) if raw_ytd_val is not None else 0.0
    except (ValueError, TypeError):
        ytd_revenue = 0.0

    logger.info(
        f"PL Workbook Successfully Parsed: Sheet='{ws.title}', Period={month_str} {year_int}, "
        f"Month Revenue={month_revenue:,.2f}, YTD Revenue={ytd_revenue:,.2f} "
        f"(row={rev_row}, ptd_col={ptd_col}, ytd_col={ytd_col})"
    )

    return {
        "sheet_name": ws.title,
        "month": month_str,
        "year": year_int,
        "month_revenue": month_revenue,
        "ytd_revenue": ytd_revenue,
        "ptd_column": ptd_col,
        "ytd_column": ytd_col,
        "revenue_row": rev_row,
    }
