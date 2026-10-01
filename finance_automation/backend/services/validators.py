import os
from pathlib import Path
from typing import List, Optional
from unittest import result
from utils.logger import logger
from config import settings


class ValidationResult:
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.is_valid: bool = True
        self.meta: dict = {}

    def add_error(self, message: str):
        self.errors.append(message)
        self.is_valid = False
        logger.error(f"Validation error: {message}")

    def add_warning(self, message: str):
        self.warnings.append(message)
        logger.warning(f"Validation warning: {message}")


def validate_uploaded_files(
    tb_current_path: Optional[str],
    tb_previous_path: Optional[str],
    budget_path: Optional[str],
    mapping_path: Optional[str],
) -> ValidationResult:
    result = ValidationResult()

    if not tb_current_path or not os.path.exists(tb_current_path):
        result.add_error("Current Year Trial Balance file is missing or not found.")
    elif not _is_valid_tb_extension(tb_current_path):
        result.add_error("Current Year Trial Balance must be a .xlsx, .xls or .txt file.")

    if not tb_previous_path or not os.path.exists(tb_previous_path):
        result.add_error("Previous Year Trial Balance file is missing or not found.")
    elif not _is_valid_tb_extension(tb_previous_path):
        result.add_error("Previous Year Trial Balance must be a .xlsx, .xls or .txt file.")

    if not budget_path or not os.path.exists(budget_path):
        result.add_error("Revenue Budget Workbook is missing or not found.")
    elif not _is_valid_extension(budget_path):
        result.add_error("Revenue Budget Workbook must be an Excel file (.xlsx/.xls).")

    if not mapping_path or not os.path.exists(mapping_path):
        result.add_error("Revenue Mapping Workbook is missing or not found.")
    elif not _is_valid_extension(mapping_path):
        result.add_error("Revenue Mapping Workbook must be an Excel file (.xlsx/.xls).")

    return result


# Row 3 of the 'Code Mapping' sheet, columns A-L. MappingEngine reads these by position.
_MAPPING_HEADERS = [
    "HEADING IN REVENUE SLIDE",
    "DESCRIPTION",
    "COST_CENTRE_FROM",
    "COST_CENTRE_TO",
    "PRODUCT_FROM",
    "PRODUCT_TO",
    "ACCOUNT_FROM",
    "ACCOUNT_TO",
    "TECH_FROM",
    "TECH_TO",
    "BUSINESS_LINE_FROM",
    "BUSINESS_LINE_TO",
]


def _cell_list(cells: List[str], limit: int = 5) -> str:
    shown = ", ".join(cells[:limit])
    return shown + (f" and {len(cells) - limit} more" if len(cells) > limit else "")


def validate_mapping_workbook(mapping_path: str) -> ValidationResult:
    """
    Validates the Revenue Mapping workbook against the layout MappingEngine reads:
    a 'Code Mapping' sheet, the A-L header row (row 3), numeric FROM/TO ranges
    with FROM <= TO, revenue account codes (400000-499999), and rules whose
    'Heading in Revenue Slide' covers every slide category.

    On success result.meta holds {"rule_count", "categories"}.
    """
    import re
    import openpyxl
    from openpyxl.utils import get_column_letter
    from services.mapping_engine import MappingEngine

    result = ValidationResult()

    if Path(mapping_path).suffix.lower() != ".xlsx":
        result.add_error(
            "Revenue Mapping Workbook must be saved as an .xlsx workbook. "
            "Please open it in Excel and use Save As > Excel Workbook (.xlsx)."
        )
        return result

    try:
        wb = openpyxl.load_workbook(mapping_path, read_only=True, data_only=True)
    except Exception as e:
        logger.error(f"Cannot open mapping workbook: {e}")
        result.add_error(
            "Revenue Mapping Workbook could not be opened. It may be corrupted, "
            "password protected, or not a real Excel workbook."
        )
        return result

    try:
        if "Code Mapping" not in wb.sheetnames:
            result.add_error(
                f"Mapping workbook missing 'Code Mapping' sheet. Sheets found: {', '.join(wb.sheetnames)}."
            )
            return result

        ws = wb["Code Mapping"]

        header = next(ws.iter_rows(min_row=3, max_row=3, max_col=12, values_only=True), ())
        header = [re.sub(r"\s+", " ", str(c)).strip().upper() if c is not None else "" for c in header]
        header += [""] * (12 - len(header))
        wrong_cols = [
            f"{get_column_letter(i + 1)} should be '{expected}' (found '{header[i] or 'empty'}')"
            for i, expected in enumerate(_MAPPING_HEADERS)
            if header[i] != expected
        ]
        if wrong_cols:
            result.add_error(
                "The 'Code Mapping' header row (row 3) does not match the expected layout: "
                + _cell_list(wrong_cols, 3) + "."
            )
            return result

        # Range cells on rule rows (numeric code in column A), same rows MappingEngine turns into rules
        bad_cells, reversed_ranges, non_revenue = [], [], []
        for row_idx, row in enumerate(ws.iter_rows(min_row=4, max_col=12, values_only=True), start=4):
            row = list(row) + [None] * (12 - len(row))
            try:
                float(row[0])
            except (TypeError, ValueError):
                continue

            for col in range(2, 12):
                value = row[col]
                if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
                    continue
                if isinstance(value, str) and value.strip().isdigit():
                    continue
                bad_cells.append(f"{get_column_letter(col + 1)}{row_idx} ('{value}')")

            for from_col in range(2, 12, 2):
                low, high = row[from_col], row[from_col + 1]
                if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low > high:
                    reversed_ranges.append(
                        f"row {row_idx} {_MAPPING_HEADERS[from_col].replace('_FROM', '')} {int(low)} > {int(high)}"
                    )

            for col in (6, 7):
                value = row[col]
                if isinstance(value, (int, float)) and not (400000 <= value <= 499999):
                    non_revenue.append(f"{get_column_letter(col + 1)}{row_idx} ({int(value)})")

        if bad_cells:
            result.add_error(
                "The 'Code Mapping' sheet has non-numeric values in the FROM/TO code columns: "
                f"{_cell_list(bad_cells)}. These columns must contain numbers only."
            )
            return result
        if reversed_ranges:
            result.add_error(
                f"The 'Code Mapping' sheet has ranges where FROM is greater than TO: {_cell_list(reversed_ranges)}."
            )
            return result
        if non_revenue:
            result.add_error(
                "The 'Code Mapping' sheet has account codes outside the revenue range (400000-499999): "
                f"{_cell_list(non_revenue)}."
            )
            return result

        engine = MappingEngine()
        engine.load_mapping(mapping_path)
        if not engine.rules:
            result.add_error("The 'Code Mapping' sheet does not contain any mapping rules.")
            return result

        # International sub-headings (3.1, 3.2, ...) are intentionally range-less; MappingEngine
        # limits them to the international business lines. Any other range-less rule matches everything.
        catch_all = [
            r.sub_category or "(no description)"
            for r in engine.rules
            if r.specificity_score() == 0 and r.category != "International"
        ]
        if catch_all:
            result.add_error(
                "Some mapping rules have no code ranges at all and would match every account: "
                f"{_cell_list(catch_all)}. Please add at least one FROM/TO range to each rule."
            )
            return result

        no_heading = [r.sub_category or "(no description)" for r in engine.rules if not r.category]
        if no_heading:
            result.add_error(
                "Some mapping rules appear before any 'Heading in Revenue Slide' section: "
                f"{_cell_list(no_heading)}."
            )
            return result

        rule_categories = {r.category for r in engine.rules}
        unknown = sorted(rule_categories - set(settings.SLIDE_CATEGORIES))
        if unknown:
            result.add_error(
                "The 'Code Mapping' sheet uses headings that are not revenue slide categories: "
                f"{_cell_list(unknown)}. Please use the slide category names (e.g. 'Copper - Voice', 'FTTH - BB')."
            )
            return result

        required = [c for c in settings.SLIDE_CATEGORIES if c not in settings.SUBTOTAL_ROWS]
        missing = [c for c in required if c not in rule_categories]
        if missing:
            result.add_error(
                f"The 'Code Mapping' sheet has no mapping rules for: {_cell_list(missing, 10)}. "
                "Every revenue slide category needs at least one rule."
            )
            return result

        result.meta = {"rule_count": len(engine.rules), "categories": sorted(rule_categories)}
        logger.info(
            f"Mapping workbook validated: {len(engine.rules)} rules across {len(rule_categories)} categories."
        )
        return result
    finally:
        wb.close()


_MONTH_ABBRS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _budget_header_month(value):
    """Return (year, month) for a FRM header cell: a date or text like 'Jan-26' / 'Jan 2026'."""
    import datetime
    import re

    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.year, value.month
    if isinstance(value, str):
        m = re.match(r"^\s*([a-z]{3})[a-z]*[\s\-/']*(\d{2}|\d{4})\s*$", value.lower())
        if m and m.group(1) in _MONTH_ABBRS:
            year = int(m.group(2))
            return (2000 + year if year < 100 else year), _MONTH_ABBRS.index(m.group(1)) + 1
    return None


def validate_budget_workbook(budget_path: str) -> ValidationResult:
    """
    Validates the Revenue Budget workbook against the layout BudgetProcessor reads:
    an 'FRM' sheet, Jan-Dec month header columns (rows 1-10) for a single year,
    coded revenue line rows (e.g. '1-1', '2-1-3') in columns F/G, numeric targets
    without Excel error values, and lines that map to the revenue slide categories.

    On success result.meta holds {"budget_year", "months_with_data", "categories_with_data"}.
    """
    import re
    import openpyxl
    from services.budget_processor import BudgetProcessor

    result = ValidationResult()

    if Path(budget_path).suffix.lower() != ".xlsx":
        result.add_error(
            "Revenue Budget Workbook must be saved as an .xlsx workbook. "
            "Please open it in Excel and use Save As > Excel Workbook (.xlsx)."
        )
        return result

    try:
        wb = openpyxl.load_workbook(budget_path, read_only=True, data_only=True)
    except Exception as e:
        logger.error(f"Cannot open budget workbook: {e}")
        result.add_error(
            "Revenue Budget Workbook could not be opened. It may be corrupted, "
            "password protected, or not a real Excel workbook."
        )
        return result

    try:
        frm_name = next((n for n in wb.sheetnames if n.strip().upper() == "FRM"), None)
        if frm_name is None:
            result.add_error(
                f"Budget workbook missing 'FRM' sheet. Sheets found: {', '.join(wb.sheetnames)}."
            )
            return result

        ws = wb[frm_name]
        header_rows = list(ws.iter_rows(min_row=1, max_row=10, values_only=True))

        header_text = " ".join(
            str(c).lower() for row in header_rows for c in row if isinstance(c, str)
        )
        if "operating revenue" not in header_text:
            result.add_error(
                "The 'FRM' sheet does not look like the Operating Revenue budget "
                "(no 'Operating Revenue' heading found in the first 10 rows)."
            )
            return result

        # Month header: the row with the most month cells (row 6 in the standard template)
        best_row = {}
        for row in header_rows:
            found = {}
            for col_idx, cell in enumerate(row):
                ym = _budget_header_month(cell)
                if ym:
                    found[col_idx] = ym
            if len(found) > len(best_row):
                best_row = found

        if not best_row:
            result.add_error(
                "No month columns found in the 'FRM' sheet. The header row must contain "
                "the months Jan to Dec (e.g. Jan-26 ... Dec-26)."
            )
            return result

        years = sorted({y for y, _ in best_row.values()})
        if len(years) > 1:
            result.add_error(
                f"The 'FRM' month columns cover more than one year ({', '.join(map(str, years))}). "
                "The budget must contain Jan to Dec of a single year."
            )
            return result

        budget_year = years[0]
        months_present = {m for _, m in best_row.values()}
        missing = [_MONTH_ABBRS[m - 1].title() for m in range(1, 13) if m not in months_present]
        if missing:
            result.add_error(
                f"The 'FRM' sheet is missing month columns for {budget_year}: {', '.join(missing)}."
            )
            return result

        month_cols = {col_idx: month for col_idx, (_, month) in best_row.items()}

        code_pattern = re.compile(r"^\d+[-.]\d+")
        code_rows = 0
        numeric_cells = 0
        months_with_data = set()
        error_cells = []
        for row_idx, row in enumerate(ws.iter_rows(min_row=8, values_only=True), start=8):
            col_f = str(row[5]).strip() if len(row) > 5 and row[5] is not None else ""
            col_g = str(row[6]).strip() if len(row) > 6 and row[6] is not None else ""
            if code_pattern.match(col_f) or code_pattern.match(col_g):
                code_rows += 1

            for col_idx, month in month_cols.items():
                value = row[col_idx] if col_idx < len(row) else None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric_cells += 1
                    if value != 0:
                        months_with_data.add(month)
                elif isinstance(value, str) and value.strip().startswith("#"):
                    error_cells.append(f"{openpyxl.utils.get_column_letter(col_idx + 1)}{row_idx} ({value.strip()})")

        if code_rows == 0:
            result.add_error(
                "No revenue line codes found in the 'FRM' sheet (columns F/G should contain codes like '1-1', '2-1-3')."
            )
            return result

        if error_cells:
            shown = ", ".join(error_cells[:5])
            more = f" and {len(error_cells) - 5} more" if len(error_cells) > 5 else ""
            result.add_error(
                f"The 'FRM' sheet contains Excel error values in the budget figures: {shown}{more}. "
                "Please fix the formulas or links and save the workbook again."
            )
            return result

        if numeric_cells == 0:
            result.add_error(
                "The 'FRM' sheet has no budget figures. If the values are formulas, open the "
                "workbook in Excel, let it recalculate, and save it before uploading."
            )
            return result

        # Run the same mapping BudgetProcessor uses to make sure the lines feed the slides
        import calendar

        processor = BudgetProcessor()
        budget_rows = processor._extract_budget_data(
            ws, {calendar.month_name[m]: c + 1 for c, m in month_cols.items()}
        )
        processor._map_to_slide_categories(budget_rows)
        categories_with_data = sorted(
            c for c, months in processor.monthly_budgets.items() if any(v != 0 for v in months.values())
        )
        if not categories_with_data:
            result.add_error(
                "None of the budget lines in the 'FRM' sheet match the revenue categories "
                "(Copper - Voice, FTTH - BB, PEO TV, ...). Please upload the Revenue Budget Segmental workbook."
            )
            return result

        result.meta = {
            "budget_year": budget_year,
            "months_with_data": sorted(months_with_data),
            "categories_with_data": categories_with_data,
        }
        logger.info(
            f"Budget workbook validated: year {budget_year}, {code_rows} coded rows, "
            f"{len(categories_with_data)} categories with data."
        )
        return result
    finally:
        wb.close()


def validate_trial_balance(tb_path: str, label: str) -> ValidationResult:
    import openpyxl
    import re

    result = ValidationResult()

    ext = Path(tb_path).suffix.lower()

    # ---------------- TXT Validation ----------------
    if ext == ".txt":
        try:
            with open(tb_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            lines = [line.strip() for line in content.splitlines() if line.strip()]

            if len(lines) == 0:
                result.add_error(f"{label} Trial Balance TXT file is empty.")
                return result

            # Internal text markers check (case-insensitive):
            # Standard Trial Balance files contain "Year to date as of" or lack "Period to date for"
            content_lower = content.lower()
            is_ytd = "year to date as of" in content_lower
            is_ptd = "period to date for" in content_lower or "period to date" in content_lower

            if is_ytd or not is_ptd:
                error_msg = (
                    "This file is not supported. Standard Trial Balance files cannot be uploaded "
                    "to the system. Please upload the 'PTD - Shared Revenue only' file."
                )
                result.add_error(error_msg)
                return result

            if "\x00" in content:
                result.add_error(f"{label} Trial Balance is not a valid text file.")
                return result

            # Account rows / revenue GL codes, using the same flexfield pattern and
            # 400000-429999 revenue range as read_txt_trial_balance's GL filter
            flex_pattern = re.compile(
                r"\b(\d{2}\.\d{1,5}\.\d{1,4}\.\d{1,4}\.\d{1,5}\.(\d{5,7})\.\d{1,4}\.\d{1,4}\.\d{1,5})\b"
            )
            account_rows = 0
            revenue_rows = 0
            for line in lines:
                line = line.replace("\x0c", "").strip()
                m = flex_pattern.search(line)
                if not m:
                    continue
                account_rows += 1
                tokens = line[:m.start()].split()
                code = tokens[0] if tokens and tokens[0].isdigit() else m.group(2)
                if 400000 <= int(code) <= 429999:
                    revenue_rows += 1

            if account_rows == 0:
                result.add_error(f"{label} Trial Balance does not contain any account rows.")
                return result
            if revenue_rows == 0:
                result.add_error(
                    f"{label} Trial Balance does not contain any revenue GL codes (400000-429999)."
                )
                return result

            periods = {
                p.lower() for p in re.findall(r"period to date for\s+([a-z]{3}-\d{2,4})", content_lower)
            }
            if len(periods) > 1:
                result.add_error(
                    f"{label} Trial Balance contains more than one period ({', '.join(sorted(periods))})."
                )
                return result

            logger.info(
                f"{label} Trial Balance TXT validated successfully "
                f"({account_rows} account rows, {revenue_rows} revenue rows)."
            )
            return result

        except Exception as e:
            result.add_error(f"Cannot open {label} Trial Balance TXT file: {e}")
            return result

    # ---------------- Excel Validation (Existing Logic) ----------------
    try:
        wb = openpyxl.load_workbook(tb_path, read_only=True, data_only=True)
    except Exception as e:
        result.add_error(f"Cannot open {label} Trial Balance: {e}")
        return result

    if len(wb.sheetnames) == 0:
        result.add_error(f"{label} Trial Balance has no sheets.")
        wb.close()
        return result

    ws = wb[wb.sheetnames[0]]

    has_data = False

    for row in ws.iter_rows(min_row=1, max_row=50, values_only=True):
        for cell in row:
            if cell is not None and str(cell).strip():
                has_data = True
                break
        if has_data:
            break

    if not has_data:
        result.add_error(f"{label} Trial Balance appears to be empty.")

    wb.close()

    logger.info(f"{label} Trial Balance Excel validated successfully.")

    return result

def _is_valid_tb_extension(file_path: str) -> bool:
    ext = Path(file_path).suffix.lower()
    return ext in {".xlsx", ".xls", ".txt"}

def _is_valid_extension(file_path: str) -> bool:
    ext = Path(file_path).suffix.lower()
    return ext in settings.ALLOWED_EXTENSIONS
