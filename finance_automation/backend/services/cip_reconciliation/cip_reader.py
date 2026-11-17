"""
CIP Data Reader
Parses and consolidates the 4 categories of source files:
1. Project Details & Codes (Project Master)
2. Project Subledger Details (Additions)
3. Interfaced CIP / RWIP Amounts (Capitalization / Interface)
4. Journal Details (General Ledger Journals)
"""
from collections import defaultdict
from datetime import datetime
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import openpyxl
import pandas as pd

logger = logging.getLogger(__name__)

class CIPInputError(ValueError):
    """Raised when a source workbook does not contain the expected data."""


def _normalized_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def normalize_source(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def normalize_project_code(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    code = str(value).strip()
    if not code or code.casefold() in {"nan", "none", "0", "#n/a", "n/a"}:
        return ""
    return code.casefold()


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none"} else text


def _account_code(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        return str(int(value))
    match = re.match(r"^\s*(\d{6})\b", str(value))
    return match.group(1) if match else None


def _account_code_from_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", str(value))
    return match.group(1) if match else None


def _account_groups(values: List[Any]) -> List[Tuple[int, List[str]]]:
    groups: List[Tuple[int, List[str]]] = []
    index = 0
    while index < len(values):
        account = _account_code(values[index])
        if account is None:
            index += 1
            continue
        start = index
        accounts = []
        while index < len(values):
            account = _account_code(values[index])
            if account is None:
                break
            accounts.append(account)
            index += 1
        groups.append((start, accounts))
    return groups


def _account_group_at(values: List[Any], start: int) -> List[str]:
    accounts = []
    for value in values[start:]:
        account = _account_code(value)
        if account is None:
            break
        accounts.append(account)
    return accounts


def _period_date(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    match = re.search(
        r"\b([A-Za-z]{3,9})[\s\-']*(\d{2,4})\b",
        text,
    )
    if not match:
        return None
    month_text, year_text = match.groups()
    for month_format in ("%b", "%B"):
        try:
            month = datetime.strptime(month_text[:3], month_format).month
            year = int(year_text)
            if year < 100:
                year += 2000 if year < 50 else 1900
            return datetime(year, month, 1)
        except ValueError:
            continue
    return None


def previous_period(period: str) -> str:
    current = _period_date(period)
    if current is None:
        raise CIPInputError(f"Invalid reconciliation period '{period}'. Use a month and year, e.g. Jan-26.")
    if current.month == 1:
        prior = datetime(current.year - 1, 12, 1)
    else:
        prior = datetime(current.year, current.month - 1, 1)
    return prior.strftime("%b-%y")


def clean_project_num(val: Any) -> Optional[str]:
    """Normalizes project number into a clean string (e.g. 190106.0 -> '190106')."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if not s or s.casefold() in {"#n/a", "#value!", "#ref!", "#div/0!", "n/a"} or any(
        k in s.lower()
        for k in ("nan", "none", "total", "project number", "end of report", "reconciliation")
    ):
        return None
    try:
        f = float(s)
        i = int(f)
        if f == i:
            return str(i)
        return str(f)
    except ValueError:
        return s


def parse_numeric(val: Any) -> float:
    """Safely parses float numeric amount."""
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").replace(" ", "").strip()
    if s in {"", "-", "—"}:
        return 0.0
    if s.startswith("(") and s.endswith(")"):
        s = f"-{s[1:-1]}"
    try:
        return float(s)
    except ValueError as exc:
        raise CIPInputError(f"Invalid numeric amount '{val}'.") from exc


def build_project_code_lookup(
    project_master: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    candidates: Dict[str, set] = defaultdict(set)
    for project_number, info in project_master.items():
        code = normalize_project_code(info.get("project_code"))
        if code:
            candidates[code].add(project_number)
    unique = {code: next(iter(numbers)) for code, numbers in candidates.items() if len(numbers) == 1}
    ambiguous = {code: sorted(numbers) for code, numbers in candidates.items() if len(numbers) > 1}
    return unique, ambiguous


class CIPReader:
    """Reads and validates CIP data from source files."""

    @staticmethod
    def read_project_master(file_path: Union[str, Path]) -> Dict[str, Dict[str, Any]]:
        """
        Reads Project_Details_Codes.xlsx.
        Returns mapping: { project_num: { 'name': ..., 'code': ..., 'pm': ..., 'type': ... } }
        """
        path = Path(file_path)
        xf = pd.ExcelFile(path)
        sheets = []
        for sheet in xf.sheet_names:
            frame = pd.read_excel(path, sheet_name=sheet)
            columns = {_normalized_header(name): name for name in frame.columns}
            project_column = columns.get("projectnumber")
            if project_column:
                score = sum(
                    1
                    for column in ("projectname", "projectcode", "projectmanager", "projecttype")
                    if columns.get(column)
                )
                sheets.append((score, frame, columns))

        if not sheets:
            raise CIPInputError(f"{path.name}: no worksheet contains a Project Number column.")

        sheets.sort(key=lambda item: item[0], reverse=True)
        master: Dict[str, Dict[str, Any]] = {}
        for _, frame, columns in sheets:
            p_col = columns.get("projectnumber")
            name_col = columns.get("projectname")
            code_col = columns.get("projectcode")
            pm_col = columns.get("projectmanager") or columns.get("pm")
            type_col = columns.get("projecttype")
            start_date_col = columns.get("startdate")

            for _, row in frame.iterrows():
                p_key = clean_project_num(row.get(p_col))
                if not p_key:
                    continue
                existing = master.get(p_key, {})
                name_value = row.get(name_col) if name_col else None
                code_value = row.get(code_col) if code_col else None
                pm_value = row.get(pm_col) if pm_col else None
                type_value = row.get(type_col) if type_col else None
                start_date_value = row.get(start_date_col) if start_date_col else None
                start_date = pd.to_datetime(start_date_value, errors="coerce")
                if pd.isna(start_date) and isinstance(start_date_value, str):
                    start_date_text = start_date_value.strip().split(maxsplit=1)[0]
                    start_date = pd.to_datetime(start_date_text, errors="coerce")
                project_year = int(start_date.year) if pd.notna(start_date) else existing.get("project_year")
                master[p_key] = {
                    "project_number": p_key,
                    "project_name": _clean_text(name_value) or existing.get("project_name", ""),
                    "project_code": _clean_text(code_value) or existing.get("project_code", ""),
                    "project_manager": _clean_text(pm_value) or existing.get("project_manager", ""),
                    "project_type": _clean_text(type_value) or existing.get("project_type", ""),
                    "project_year": project_year,
                }

        logger.info(f"Loaded {len(master)} projects from master {path.name}")
        return master

    @staticmethod
    def read_subledger_detail(
        file_path: Union[str, Path]
    ) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
        """
        Reads SLT_Project_Subledger__Detail files (Additions).
        Returns:
            project_additions: { project_num: { account: total_cost, ... } }
            detailed_records: list of line items
        """
        path = Path(file_path)
        xf = pd.ExcelFile(path)
        project_additions: Dict[str, Dict[str, float]] = {}
        detailed_records: List[Dict[str, Any]] = []

        for sheet in xf.sheet_names:
            acct_matched = _account_code_from_text(sheet)
            if not acct_matched:
                continue

            # Read raw to find header row
            df_raw = pd.read_excel(path, sheet_name=sheet, header=None)
            header_idx = None
            for idx, row in df_raw.iterrows():
                vals = [str(v).strip().lower() for v in row.values if pd.notna(v)]
                if "project number" in vals or ("task num" in vals and "total cost" in vals):
                    header_idx = idx
                    break

            if header_idx is None:
                continue

            df = pd.read_excel(path, sheet_name=sheet, header=header_idx)
            # Find relevant column indices/names
            p_col = next((c for c in df.columns if "project" in str(c).lower() and "number" in str(c).lower()), None)
            p_name_col = next((c for c in df.columns if "project" in str(c).lower() and "name" in str(c).lower()), None)
            task_col = next((c for c in df.columns if "task" in str(c).lower() and "name" in str(c).lower()), None)
            exp_col = next((c for c in df.columns if "expenditure" in str(c).lower() and "type" in str(c).lower()), None)
            cost_col = next((c for c in df.columns if "total cost" in str(c).lower()), None)
            if not cost_col:
                cost_col = next((c for c in df.columns if "raw cost" in str(c).lower()), None)

            if not p_col or not cost_col:
                continue

            for _, row in df.iterrows():
                p_raw = row.get(p_col)
                p_num = clean_project_num(p_raw)
                # Ignore total / header repeat rows / non-project codes
                if not p_num or not re.match(r"^\d{6}$", p_num):
                    continue

                cost = parse_numeric(row.get(cost_col))
                project_additions.setdefault(p_num, {}).setdefault(acct_matched, 0.0)
                project_additions[p_num][acct_matched] += cost

                detailed_records.append({
                    "account": acct_matched,
                    "project_number": p_num,
                    "project_name": str(row.get(p_name_col) or "").strip() if p_name_col else "",
                    "task_name": str(row.get(task_col) or "").strip() if task_col else "",
                    "expenditure_type": str(row.get(exp_col) or "").strip() if exp_col else "",
                    "cost": cost,
                    "source_file": path.name,
                    "sheet": sheet,
                })

        logger.info(
            f"Parsed subledger additions from {path.name}: {len(project_additions)} unique projects, {len(detailed_records)} rows"
        )
        return project_additions, detailed_records

    @staticmethod
    def read_interfaced_cip(
        file_path: Union[str, Path]
    ) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
        """
        Reads SLT_Interfaced_CIP_RWIP_Amount files (Interface).
        Returns:
            project_interfaces: { project_num: { account: total_interfaced, ... } }
            detailed_records: list of line items
        """
        path = Path(file_path)
        is_xls = path.suffix.lower() == ".xls"
        engine = "xlrd" if is_xls else None
        xf = pd.ExcelFile(path, engine=engine)
        project_interfaces: Dict[str, Dict[str, float]] = {}
        detailed_records: List[Dict[str, Any]] = []

        for sheet in xf.sheet_names:
            acct_matched = _account_code_from_text(sheet)
            if not acct_matched:
                continue

            df_raw = pd.read_excel(path, sheet_name=sheet, header=None, engine=engine)
            header_idx = None
            for idx, row in df_raw.iterrows():
                vals = [str(v).strip().lower() for v in row.values if pd.notna(v)]
                if "project number" in vals or "current asset amount" in vals:
                    header_idx = idx
                    break

            if header_idx is None:
                continue

            df = pd.read_excel(path, sheet_name=sheet, header=header_idx, engine=engine)
            p_col = next((c for c in df.columns if "project" in str(c).lower() and "number" in str(c).lower()), None)
            amt_col = next((c for c in df.columns if "current asset amount" in str(c).lower()), None)
            if not amt_col:
                amt_col = next((c for c in df.columns if "amount" in str(c).lower()), None)

            p_name_col = next((c for c in df.columns if "project" in str(c).lower() and "name" in str(c).lower()), None)
            asset_cat_col = next((c for c in df.columns if "asset category" in str(c).lower()), None)

            if not p_col or not amt_col:
                continue

            for _, row in df.iterrows():
                p_raw = row.get(p_col)
                p_num = clean_project_num(p_raw)
                cat_val = str(row.get(asset_cat_col) or "").strip() if asset_cat_col else ""
                cat_match = re.match(r"^(\d{6})", cat_val)
                if cat_match:
                    p_num = cat_match.group(1)
                if not p_num or not p_num.isdigit():
                    continue

                amt = parse_numeric(row.get(amt_col))
                project_interfaces.setdefault(p_num, {}).setdefault(acct_matched, 0.0)
                project_interfaces[p_num][acct_matched] += amt

                detailed_records.append({
                    "account": acct_matched,
                    "project_number": p_num,
                    "project_name": _clean_text(row.get(p_name_col)) if p_name_col else "",
                    "asset_category": cat_val,
                    "amount": amt,
                    "source_file": path.name,
                    "sheet": sheet,
                })

        logger.info(
            f"Parsed interfaced CIP from {path.name}: {len(project_interfaces)} unique projects, {len(detailed_records)} rows"
        )
        return project_interfaces, detailed_records

    @staticmethod
    def read_journal_details(
        file_path: Union[str, Path],
        project_master: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
        """
        Reads detailed journal rows and summarizes them by account and source.
        Returns:
            account_gl_summary: account totals with per-source debit, credit, and net balances
            journal_rows: list of journal line items
        """
        path = Path(file_path)
        project_lookup, ambiguous_codes = build_project_code_lookup(project_master or {})
        account_gl_summary: Dict[str, Dict[str, Any]] = {}
        journal_rows: List[Dict[str, Any]] = []

        def append_rows(sheet: str, values: List[List[Any]], formula_rows: Optional[List[List[bool]]] = None):
            acct_matched = _account_code_from_text(sheet)
            if not acct_matched:
                return

            header_index = None
            header_map: Dict[str, int] = {}
            for idx, row in enumerate(values):
                mapped = {_normalized_header(value): col for col, value in enumerate(row) if value is not None}
                if "dr" in mapped and "cr" in mapped:
                    header_index = idx
                    header_map = mapped
                    break
            if header_index is None:
                return

            dr_col = header_map["dr"]
            cr_col = header_map["cr"]
            optional_columns = {
                "category": header_map.get("category"),
                "source": header_map.get("source"),
                "journal_name": next((col for name, col in header_map.items() if "journalname" in name), None),
                "future": header_map.get("future"),
                "project": header_map.get("project", header_map.get("projectnumber")),
                "period": header_map.get("period"),
            }

            for idx in range(header_index + 1, len(values)):
                row = values[idx]
                formulas = formula_rows[idx] if formula_rows and idx < len(formula_rows) else []
                dr_raw = row[dr_col] if dr_col < len(row) else None
                cr_raw = row[cr_col] if cr_col < len(row) else None
                if (dr_col < len(formulas) and formulas[dr_col]) or (cr_col < len(formulas) and formulas[cr_col]):
                    continue
                if isinstance(dr_raw, str) and dr_raw.strip().startswith("="):
                    continue
                if isinstance(cr_raw, str) and cr_raw.strip().startswith("="):
                    continue
                dr = parse_numeric(dr_raw)
                cr = parse_numeric(cr_raw)
                if dr == 0.0 and cr == 0.0:
                    continue

                def value_for(key: str) -> Any:
                    col = optional_columns[key]
                    return row[col] if col is not None and col < len(row) else None

                source = _clean_text(value_for("source"))
                source_key = normalize_source(source) or "unclassified"
                source_label = source or "Unclassified"
                category = _clean_text(value_for("category"))
                if normalize_source(category) in {"total", "subtotal", "subtotals", "grandtotal"}:
                    continue
                if source_key in {"total", "subtotal", "subtotals", "grandtotal"}:
                    continue
                journal_name = _clean_text(value_for("journal_name"))
                future_value = value_for("future")
                future = _clean_text(future_value)
                original_project = clean_project_num(value_for("project"))
                code_key = normalize_project_code(future_value)
                direct_project = clean_project_num(future_value)
                mapped_project = (
                    direct_project
                    if direct_project in (project_master or {})
                    else project_lookup.get(code_key)
                )
                project = mapped_project or original_project
                if code_key in ambiguous_codes and direct_project not in (project_master or {}):
                    mapping_status = "ambiguous_code"
                elif code_key and mapped_project:
                    mapping_status = "mapped"
                elif code_key:
                    mapping_status = "unmatched_code"
                else:
                    mapping_status = "existing_project" if original_project else "no_project_key"

                net = dr - cr
                acct_summary = account_gl_summary.setdefault(
                    acct_matched,
                    {"dr": 0.0, "cr": 0.0, "net": 0.0, "sources": {}},
                )
                acct_summary["dr"] += dr
                acct_summary["cr"] += cr
                acct_summary["net"] += net
                source_summary = acct_summary["sources"].setdefault(
                    source_key,
                    {"source": source_label, "dr": 0.0, "cr": 0.0, "net": 0.0, "transactions": 0},
                )
                source_summary["dr"] += dr
                source_summary["cr"] += cr
                source_summary["net"] += net
                source_summary["transactions"] += 1

                journal_rows.append({
                    "account": acct_matched,
                    "dr": dr,
                    "cr": cr,
                    "net": net,
                    "category": category,
                    "source": source_label,
                    "source_key": source_key,
                    "journal_name": journal_name,
                    "future": future,
                    "project": project,
                    "original_project": original_project,
                    "project_mapping_status": mapping_status,
                    "period": _clean_text(value_for("period")),
                    "sheet": sheet,
                    "row_number": idx + 1,
                })

        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            formula_wb = openpyxl.load_workbook(path, data_only=False, read_only=False)
            value_wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
            try:
                for sheet in formula_wb.sheetnames:
                    values_ws = value_wb[sheet]
                    formula_ws = formula_wb[sheet]
                    values = [[cell.value for cell in row] for row in values_ws.iter_rows()]
                    formulas = [[cell.data_type == "f" for cell in row] for row in formula_ws.iter_rows()]
                    append_rows(sheet, values, formulas)
            finally:
                formula_wb.close()
                value_wb.close()
        else:
            xf = pd.ExcelFile(path, engine="xlrd")
            for sheet in xf.sheet_names:
                frame = pd.read_excel(path, sheet_name=sheet, header=None, engine="xlrd")
                append_rows(sheet, frame.values.tolist())

        logger.info(
            f"Parsed journal details from {path.name}: {len(journal_rows)} journal entries"
        )
        return account_gl_summary, journal_rows

    @staticmethod
    def read_opening_balances(
        file_path: Union[str, Path],
        expected_period: Optional[str] = None,
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """
        Reads opening balances from an existing reference output or prior period file.
        Returns: { project_num: { account: balance, ... } }
        """
        path = Path(file_path)
        value_wb = openpyxl.load_workbook(path, data_only=True, keep_links=False)
        formula_wb = openpyxl.load_workbook(path, data_only=False, keep_links=False)
        try:
            selected = None
            for ws in value_wb.worksheets:
                for row_index, row in enumerate(ws.iter_rows(values_only=True), start=1):
                    values = list(row)
                    project_col = next(
                        (idx for idx, value in enumerate(values) if _normalized_header(value) in {"projectno", "projectnumber"}),
                        None,
                    )
                    if project_col is None:
                        continue
                    title_values = (
                        list(ws.iter_rows(min_row=row_index - 1, max_row=row_index - 1, values_only=True))[0]
                        if row_index > 1
                        else []
                    )
                    closing_starts = [
                        column
                        for column, title in enumerate(title_values)
                        if re.search(r"balance|closing", _clean_text(title), re.I)
                        and not re.search(r"opening", _clean_text(title), re.I)
                    ]
                    groups = []
                    if closing_starts:
                        start = closing_starts[-1]
                        accounts = _account_group_at(values, start)
                        if accounts:
                            groups.append((start, accounts, _clean_text(title_values[start])))
                    if not groups:
                        groups = [
                            (start, accounts, _clean_text(title_values[start]) if start < len(title_values) else "")
                            for start, accounts in _account_groups(values)
                        ]
                    if groups:
                        closing_groups = [
                            group for group in groups if re.search(r"balance|closing", group[2], re.I)
                        ]
                        start, accounts, title = (closing_groups or groups)[-1]
                        selected = (ws, row_index, project_col, start, accounts, title)
                        break
                if selected:
                    break

            if not selected:
                raise CIPInputError(f"{path.name}: could not find a project/account balance header.")

            ws, header_row, project_col, start_col, accounts, title = selected
            formula_ws = formula_wb[ws.title]
            report_period = _period_date(title)
            if report_period is None:
                for row in ws.iter_rows(min_row=1, max_row=header_row, values_only=True):
                    report_period = next(
                        (_period_date(value) for value in row if _period_date(value) is not None),
                        None,
                    )
                    if report_period:
                        break
            if expected_period:
                expected_date = _period_date(expected_period)
                if report_period is None:
                    raise CIPInputError(f"{path.name}: could not determine the period of the opening-balance report.")
                if expected_date is None or (report_period.year, report_period.month) != (expected_date.year, expected_date.month):
                    raise CIPInputError(
                        f"{path.name}: expected closing balances for {expected_period}, "
                        f"found {report_period.strftime('%b-%y')}. Select a reconciliation period "
                        f"after {report_period.strftime('%b-%y')} or upload a report that closes in {expected_period}."
                    )

            opening: Dict[str, Dict[str, Optional[float]]] = {}
            for row_index, row in enumerate(
                ws.iter_rows(min_row=header_row + 1, values_only=True),
                start=header_row + 1,
            ):
                raw_project = row[project_col] if project_col < len(row) else None
                p_val = clean_project_num(raw_project)
                if not p_val or not re.fullmatch(r"\d{6}", p_val):
                    if opening:
                        break
                    continue
                p_balances = opening.setdefault(p_val, {})
                for offset, account in enumerate(accounts):
                    col = start_col + offset
                    value = row[col] if col < len(row) else None
                    if value is None:
                        formula = formula_ws.cell(row_index, col + 1).value
                        if isinstance(formula, str) and formula.startswith("="):
                            references = re.findall(r"(?<![A-Z0-9_])\$?([A-Z]{1,3}\$?\d+)", formula.upper())
                            if references:
                                value = sum(
                                    parse_numeric(ws[reference.replace("$", "")].value)
                                    for reference in references
                                )
                    amount = parse_numeric(value) if value is not None else None
                    if account not in p_balances:
                        p_balances[account] = amount
                    elif amount is not None:
                        p_balances[account] = (p_balances[account] or 0.0) + amount

            if not opening:
                raise CIPInputError(f"{path.name}: no project opening balances were found.")
            logger.info(f"Loaded opening balances for {len(opening)} projects from {path.name}")
            return opening
        finally:
            value_wb.close()
            formula_wb.close()

    @staticmethod
    def read_trial_balance(
        file_path: Union[str, Path],
        period: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reads current YTD balances from column E and the report period from the workbook."""
        path = Path(file_path)
        wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
        try:
            reported_period = None
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    reported_period = next(
                        (
                            _period_date(value)
                            for value in row
                            if "currentperiod" in _normalized_header(value)
                            and _period_date(value) is not None
                        ),
                        None,
                    )
                    if reported_period is not None:
                        break
                if reported_period is not None:
                    break

            requested_period = _period_date(period) if period else None
            if period and requested_period is None:
                raise CIPInputError(f"Invalid reconciliation period '{period}'.")
            if reported_period is not None and requested_period is not None and (
                reported_period.year,
                reported_period.month,
            ) != (requested_period.year, requested_period.month):
                raise CIPInputError(
                    f"{path.name}: Trial Balance current period is {reported_period.strftime('%b-%y')}, "
                    f"but the selected reconciliation period is {requested_period.strftime('%b-%y')}."
                )
            target_period = reported_period or requested_period

            for ws in wb.worksheets:
                for header_row in range(1, ws.max_row):
                    header_values = [ws.cell(header_row, col).value for col in range(1, ws.max_column + 1)]
                    if not header_values or _normalized_header(header_values[0]) not in {
                        "account",
                        "accountcode",
                        "accountnumber",
                    }:
                        continue

                    period_values = [ws.cell(header_row + 1, col).value for col in range(1, ws.max_column + 1)]
                    ytd_columns = [
                        col
                        for col, value in enumerate(header_values, start=1)
                        if _normalized_header(value) == "ytdactual"
                    ]
                    if 5 not in ytd_columns:
                        continue
                    column_e_period = _period_date(period_values[4])
                    if target_period is None:
                        target_period = column_e_period
                    if target_period is None or column_e_period is None or (
                        column_e_period.year,
                        column_e_period.month,
                    ) != (target_period.year, target_period.month):
                        continue

                    previous = _period_date(previous_period(target_period.strftime("%b-%y")))
                    opening_col = next(
                        (
                            col
                            for col in ytd_columns
                            if previous is not None
                            and (date := _period_date(period_values[col - 1])) is not None
                            and (date.year, date.month) == (previous.year, previous.month)
                        ),
                        None,
                    )

                    balances: Dict[str, float] = {}
                    opening_balances: Dict[str, float] = {}
                    for row_index in range(header_row + 2, ws.max_row + 1):
                        account = _account_code(ws.cell(row_index, 1).value)
                        if account is None:
                            continue
                        balances[account] = parse_numeric(ws.cell(row_index, 5).value)
                        if opening_col is not None:
                            opening_balances[account] = parse_numeric(ws.cell(row_index, opening_col).value)
                    if not balances:
                        continue
                    return {
                        "period": target_period.strftime("%b-%y"),
                        "balances": balances,
                        "opening_period": previous.strftime("%b-%y") if previous is not None and opening_col is not None else None,
                        "opening_balances": opening_balances,
                    }
            if target_period is None:
                raise CIPInputError(f"{path.name}: could not determine the current reporting period.")
            raise CIPInputError(
                f"{path.name}: could not locate current-period YTD-Actual balances in column E "
                f"for {target_period.strftime('%b-%y')}."
            )
        finally:
            wb.close()

