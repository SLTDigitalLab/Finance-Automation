"""
CIP Data Reader
Parses and consolidates the 4 categories of source files:
1. Project Details & Codes (Project Master)
2. Project Subledger Details (Additions)
3. Interfaced CIP / RWIP Amounts (Capitalization / Interface)
4. Journal Details (General Ledger Journals)
"""
from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import openpyxl
import pandas as pd

logger = logging.getLogger(__name__)

ACCOUNTS = ["111401", "111402", "111403", "111404", "111405", "111406"]


def clean_project_num(val: Any) -> Optional[str]:
    """Normalizes project number into a clean string (e.g. 190106.0 -> '190106')."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if not s or any(k in s.lower() for k in ("nan", "none", "total", "project number", "end of report", "reconciliation")):
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
    try:
        return float(s)
    except ValueError:
        return 0.0


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
        master = {}

        # Sheet with full details is usually 'Export Worksheet' or first sheet
        target_sheet = "Export Worksheet" if "Export Worksheet" in xf.sheet_names else xf.sheet_names[0]
        df = pd.read_excel(path, sheet_name=target_sheet)

        # Standardize col names
        col_map = {str(c).strip().upper(): c for c in df.columns}
        p_col = col_map.get("PROJECT_NUMBER") or col_map.get("PROJECT NUMBER")
        name_col = col_map.get("PROJECT_NAME") or col_map.get("PROJECT NAME")
        code_col = col_map.get("PROJECT_CODE") or col_map.get("PROJECT CODE")
        pm_col = col_map.get("PROJECT_MANAGER") or col_map.get("PM")
        type_col = col_map.get("PROJECT_TYPE")

        if p_col:
            for _, r in df.iterrows():
                p_key = clean_project_num(r.get(p_col))
                if p_key:
                    name_val = str(r.get(name_col) or "").strip() if name_col else ""
                    code_val = str(r.get(code_col) or "").strip() if code_col else ""
                    if code_val.lower() == "nan":
                        code_val = ""
                    pm_val = str(r.get(pm_col) or "").strip() if pm_col else ""
                    master[p_key] = {
                        "project_number": p_key,
                        "project_name": name_val,
                        "project_code": code_val,
                        "project_manager": pm_val,
                        "project_type": str(r.get(type_col) or "").strip() if type_col else "",
                    }

        # Also check Sheet1 if exists for supplementary names/pm
        if "Sheet1" in xf.sheet_names and "Sheet1" != target_sheet:
            df1 = pd.read_excel(path, sheet_name="Sheet1")
            c1_map = {str(c).strip().upper(): c for c in df1.columns}
            p1_col = c1_map.get("PROJECT_NUMBER")
            n1_col = c1_map.get("PROJECT_NAME")
            pm1_col = c1_map.get("PM")
            if p1_col:
                for _, r in df1.iterrows():
                    p_key = clean_project_num(r.get(p1_col))
                    if p_key and p_key not in master:
                        master[p_key] = {
                            "project_number": p_key,
                            "project_name": str(r.get(n1_col) or "").strip() if n1_col else "",
                            "project_code": "",
                            "project_manager": str(r.get(pm1_col) or "").strip() if pm1_col else "",
                            "project_type": "",
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
            acct = str(sheet).strip()
            # If sheet name is not an account, check if it contains an account number
            acct_matched = next((a for a in ACCOUNTS if a in acct), None)
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
                if p_num not in project_additions:
                    project_additions[p_num] = {a: 0.0 for a in ACCOUNTS}

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
            acct = str(sheet).strip()
            acct_matched = next((a for a in ACCOUNTS if a in acct), None)
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
                if not p_num:
                    continue

                # Map text project names that carry project ID in asset category (e.g. FTTH NC 2025 -> 250103)
                cat_val = str(row.get(asset_cat_col) or "").strip() if asset_cat_col else ""
                cat_match = re.match(r"^(\d{6})", cat_val)
                if cat_match:
                    p_num = cat_match.group(1)
                elif not re.match(r"^\d{6}$", p_num):
                    continue

                amt = parse_numeric(row.get(amt_col))
                if p_num not in project_interfaces:
                    project_interfaces[p_num] = {a: 0.0 for a in ACCOUNTS}

                project_interfaces[p_num][acct_matched] += amt

                detailed_records.append({
                    "account": acct_matched,
                    "project_number": p_num,
                    "project_name": str(row.get(p_name_col) or "").strip() if p_name_col else "",
                    "asset_category": str(row.get(asset_cat_col) or "").strip() if asset_cat_col else "",
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
        file_path: Union[str, Path]
    ) -> Tuple[Dict[str, Dict[str, float]], List[Dict[str, Any]]]:
        """
        Reads Journal Details_Jul 26.xlsx.
        Returns:
            account_gl_summary: { account: { 'total_dr': ..., 'total_cr': ..., 'net': ... } }
            journal_rows: list of journal line items
        """
        path = Path(file_path)
        xf = pd.ExcelFile(path)
        account_gl_summary: Dict[str, Dict[str, float]] = {
            a: {"dr": 0.0, "cr": 0.0, "net": 0.0} for a in ACCOUNTS
        }
        journal_rows: List[Dict[str, Any]] = []

        for sheet in xf.sheet_names:
            acct = str(sheet).strip()
            acct_matched = next((a for a in ACCOUNTS if a in acct), None)
            if not acct_matched:
                continue

            df_raw = pd.read_excel(path, sheet_name=sheet, header=None)
            header_idx = None
            for idx, row in df_raw.iterrows():
                vals = [str(v).strip().upper() for v in row.values if pd.notna(v)]
                if "DR" in vals and "CR" in vals:
                    header_idx = idx
                    break

            if header_idx is None:
                continue

            df = pd.read_excel(path, sheet_name=sheet, header=header_idx)
            dr_col = next((c for c in df.columns if str(c).strip().upper() == "DR"), None)
            cr_col = next((c for c in df.columns if str(c).strip().upper() == "CR"), None)
            cat_col = next((c for c in df.columns if str(c).strip().lower() == "category"), None)
            src_col = next((c for c in df.columns if str(c).strip().lower() == "source"), None)
            jname_col = next((c for c in df.columns if "journal name" in str(c).strip().lower()), None)
            future_col = next((c for c in df.columns if str(c).strip().lower() == "future"), None)
            proj_col = next((c for c in df.columns if "project" in str(c).strip().lower()), None)

            if not dr_col or not cr_col:
                continue

            for _, row in df.iterrows():
                dr = parse_numeric(row.get(dr_col))
                cr = parse_numeric(row.get(cr_col))
                if dr == 0.0 and cr == 0.0:
                    continue

                account_gl_summary[acct_matched]["dr"] += dr
                account_gl_summary[acct_matched]["cr"] += cr
                account_gl_summary[acct_matched]["net"] += (dr - cr)

                journal_rows.append({
                    "account": acct_matched,
                    "dr": dr,
                    "cr": cr,
                    "net": dr - cr,
                    "category": str(row.get(cat_col) or "").strip() if cat_col else "",
                    "source": str(row.get(src_col) or "").strip() if src_col else "",
                    "journal_name": str(row.get(jname_col) or "").strip() if jname_col else "",
                    "future": str(row.get(future_col) or "").strip() if future_col else "",
                    "project": clean_project_num(row.get(proj_col)) if proj_col else None,
                    "sheet": sheet,
                })

        logger.info(
            f"Parsed journal details from {path.name}: {len(journal_rows)} journal entries"
        )
        return account_gl_summary, journal_rows

    @staticmethod
    def read_opening_balances(
        file_path: Union[str, Path]
    ) -> Dict[str, Dict[str, float]]:
        """
        Reads opening balances from an existing reference output or prior period file.
        Returns: { project_num: { account: balance, ... } }
        """
        path = Path(file_path)
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        opening: Dict[str, Dict[str, float]] = {}

        # Look at reference format: Row 2 has headers (Project No at Col 1, accounts at cols 4-9)
        acct_cols = {}
        for c in range(4, 10):
            acct_val = str(ws.cell(2, c).value or "").strip()
            if acct_val in ACCOUNTS:
                acct_cols[c] = acct_val

        for r in range(3, ws.max_row + 1):
            p_val = clean_project_num(ws.cell(r, 1).value)
            if not p_val or str(p_val).lower() == "total":
                continue

            p_balances = {a: 0.0 for a in ACCOUNTS}
            for c_idx, acct in acct_cols.items():
                p_balances[acct] = parse_numeric(ws.cell(r, c_idx).value)

            opening[p_val] = p_balances

        logger.info(f"Loaded opening balances for {len(opening)} projects from {path.name}")
        return opening

