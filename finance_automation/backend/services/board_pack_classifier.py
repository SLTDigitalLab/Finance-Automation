"""
Structure-based file classifier for Finance Board Pack.

Identifies uploaded Excel and PowerPoint files based on their internal structure,
sheets, headers, and content rather than filenames.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import openpyxl
from pptx import Presentation


def _norm(val: Any) -> str:
    """Strip all non-alphanumeric characters and lowercase."""
    return re.sub(r"[^a-z0-9]", "", str(val or "").lower())


def _extract_period_from_text(text: str) -> Optional[Tuple[str, int]]:
    """Tries to extract (Month_Name, Year) from a text string or date string."""
    text_clean = str(text or "").strip()
    # Check ISO date format YYYY-MM-DD
    iso_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text_clean)
    if iso_match:
        y = int(iso_match.group(1))
        m = int(iso_match.group(2))
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        if 1 <= m <= 12 and 1900 <= y <= 2100:
            return month_names[m - 1], y

    months = [
        ("Jan", ["jan", "january"]),
        ("Feb", ["feb", "february"]),
        ("Mar", ["mar", "march"]),
        ("Apr", ["apr", "april"]),
        ("May", ["may"]),
        ("Jun", ["jun", "june"]),
        ("Jul", ["jul", "july"]),
        ("Aug", ["aug", "august"]),
        ("Sep", ["sep", "sept", "september"]),
        ("Oct", ["oct", "october"]),
        ("Nov", ["nov", "november"]),
        ("Dec", ["dec", "december"]),
    ]
    found_month = None
    for abbrev, variants in months:
        for v in variants:
            if re.search(rf"\b{v}\b", text_clean, re.IGNORECASE) or re.search(rf"{v}[-_'\s]", text_clean, re.IGNORECASE):
                found_month = abbrev
                break
        if found_month:
            break

    # Look for 4-digit year or 2-digit apostrophe year or dash year e.g. Oct-26
    year_match = re.search(r"(?:19|20)\d{2}", text_clean)
    found_year = int(year_match.group(0)) if year_match else None
    if not found_year:
        short_year_match = re.search(r"[-_'’](\d{2})\b", text_clean)
        if short_year_match:
            found_year = 2000 + int(short_year_match.group(1))

    if found_month and found_year:
        return found_month, found_year
    return None


def classify_file(file_path: Path) -> Dict[str, Any]:
    """
    Inspects an uploaded file and returns its classification, detected roles,
    period, and summary details.
    """
    ext = file_path.suffix.lower()
    res: Dict[str, Any] = {
        "filename": file_path.name,
        "extension": ext,
        "size": file_path.stat().st_size if file_path.exists() else 0,
        "roles": [],
        "period": None,
        "sheets": [],
        "valid": False,
        "details": "",
    }

    if ext in (".xlsx", ".xlsm"):
        try:
            wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
            res["sheets"] = wb.sheetnames
            sheets_norm = [_norm(s) for s in wb.sheetnames]

            # 1. Check Mobitel Excel
            has_slt_pres = any("sltpresentation" in s for s in sheets_norm)
            has_bs = any(s == "bs" for s in sheets_norm)
            has_cf = any(s == "cf" for s in sheets_norm)
            has_sub = any("subscriber" in s for s in sheets_norm)
            if has_slt_pres and (has_bs or has_cf or has_sub):
                res["roles"].append("mobitel_excel")
                # Detect period from SLT Presentation (Month in C1, Year in C3 or BS date in C3)
                ws_pres = None
                for s in wb.sheetnames:
                    if "sltpresentation" in _norm(s):
                        ws_pres = wb[s]
                        break
                if ws_pres:
                    c1_val = str(ws_pres.cell(1, 3).value or "")
                    c3_val = str(ws_pres.cell(3, 3).value or "")
                    period = _extract_period_from_text(f"{c1_val} {c3_val}")
                    if period:
                        res["period"] = f"{period[0]} {period[1]}"
                if not res["period"] and has_bs:
                    for s in wb.sheetnames:
                        if _norm(s) == "bs":
                            val = str(wb[s].cell(3, 3).value or "")
                            period = _extract_period_from_text(val)
                            if period:
                                res["period"] = f"{period[0]} {period[1]}"
                            break

            # 2. Check Board Pack (9 slides) Sub workings
            has_income = any(s.startswith("income") for s in sheets_norm)
            has_bdslides = any(s.startswith("bdslides") for s in sheets_norm)
            if has_income and has_bdslides:
                res["roles"].append("board_pack_excel")
                if not res["period"]:
                    # Try to extract period from cell A4 of income or bdslides
                    for s in wb.sheetnames:
                        if _norm(s).startswith("income") or _norm(s).startswith("bdslides"):
                            ws = wb[s]
                            val = str(ws.cell(4, 1).value or "")
                            period = _extract_period_from_text(val)
                            if period:
                                res["period"] = f"{period[0]} {period[1]}"
                                break

            # 3. Check Ratio Report (2 slides)
            visible_sheets = [s for s in wb.sheetnames]
            if len(visible_sheets) >= 2:
                ws_first = wb[visible_sheets[0]]
                c1 = _norm(ws_first.cell(1, 1).value)
                ws_last = wb[visible_sheets[-1]]
                c_last = _norm(ws_last.cell(1, 1).value)
                if c1 in {"keyfinancialratios", "ratios"} and c_last == "balancesheetgroup":
                    res["roles"].append("ratio_excel")
                    if not res["period"]:
                        p_val = str(ws_first.cell(3, 5).value or "")
                        period = _extract_period_from_text(p_val)
                        if period:
                            res["period"] = f"{period[0]} {period[1]}"

            # 4. Check Telecom Services Information Excel
            has_detailed_info = any("detailedinformationforppt" in s for s in sheets_norm)
            has_treasury = any("treasury" in s for s in sheets_norm)
            if has_detailed_info or has_treasury:
                res["roles"].append("telecom_info_excel")
                if not res["period"]:
                    for s in wb.sheetnames:
                        if "detailedinformationforppt" in _norm(s):
                            ws = wb[s]
                            for r in range(1, 6):
                                val = str(ws.cell(r, 2).value or "")
                                period = _extract_period_from_text(val)
                                if period:
                                    res["period"] = f"{period[0]} {period[1]}"
                                    break
                            break

            # 5. Check Telecom Services PL Summary Excel
            is_telecom_pl = False
            for s in wb.sheetnames:
                ws = wb[s]
                col_a = [_norm(ws.cell(r, 1).value) for r in range(1, min(ws.max_row or 25, 25))]
                if "ebitda" in col_a and "ebit" in col_a and "npat" in col_a:
                    is_telecom_pl = True
                    if not res["period"]:
                        for r in range(1, 6):
                            for c in range(1, 10):
                                p_val = str(ws.cell(r, c).value or "")
                                period = _extract_period_from_text(p_val)
                                if period:
                                    res["period"] = f"{period[0]} {period[1]}"
                                    break
                            if res["period"]:
                                break
                    break
            if is_telecom_pl:
                res["roles"].append("telecom_pl_excel")

            wb.close()
            res["valid"] = len(res["roles"]) > 0
            res["details"] = f"Sheets: {len(res['sheets'])}, Roles: {', '.join(res['roles']) if res['roles'] else 'Unrecognized'}"
        except Exception as exc:
            res["valid"] = False
            res["details"] = f"Error reading Excel workbook: {exc}"

    elif ext == ".pptx":
        try:
            prs = Presentation(str(file_path))
            slides_text = []
            for s in prs.slides:
                t = ""
                for sh in s.shapes:
                    if sh.has_text_frame:
                        t += " " + sh.text_frame.text
                    if sh.has_table:
                        for row in sh.table.rows:
                            for cell in row.cells:
                                t += " " + cell.text
                slides_text.append(t)

            slides_norm = [_norm(t) for t in slides_text]

            # Telecom Services BS & CF presentation check:
            # Has ~2 slides containing SLTS balance sheet and cash flow
            has_bs_slts = any("balancesheetslts" in t for t in slides_norm)
            has_cf_slts = any("cashflowstatementslts" in t for t in slides_norm)
            if has_bs_slts and has_cf_slts:
                res["roles"].append("telecom_bscf_pptx")
                for t in slides_text:
                    period = _extract_period_from_text(t)
                    if period:
                        res["period"] = f"{period[0]} {period[1]}"
                        break

            res["valid"] = len(res["roles"]) > 0
            res["details"] = f"Slides: {len(prs.slides)}, Roles: {', '.join(res['roles']) if res['roles'] else 'Unrecognized'}"
            prs = None
        except Exception as exc:
            res["valid"] = False
            res["details"] = f"Error reading PowerPoint presentation: {exc}"

    return res


def check_section_requirements(
    selected_sections: List[str], classified_files: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Evaluates whether all requirements are met for the selected sections.
    Returns:
    {
        "all_ready": bool,
        "sections": {
            "board_pack": {"required": bool, "ready": bool, "inputs": [...]},
            "ratio_report": {"required": bool, "ready": bool, "inputs": [...]},
            "mobitel": {"required": bool, "ready": bool, "inputs": [...]},
            "telecom_services": {"required": bool, "ready": bool, "inputs": [...]},
        },
        "missing": [...]
    }
    """
    available_roles = set()
    for f in classified_files:
        if f.get("valid"):
            for r in f.get("roles", []):
                available_roles.add(r)

    # Requirements definition
    req_map = {
        "board_pack": [
            ("board_pack_excel", "Sub workings Excel (INCOME Amalg & BD Slides tabs)")
        ],
        "ratio_report": [
            ("ratio_excel", "Ratio & Group Balance Sheet Excel")
        ],
        "mobitel": [
            ("mobitel_excel", "Mobitel Excel (SLT Presentation, BS, CF, Subscriber tabs)")
        ],
        "telecom_services": [
            ("telecom_info_excel", "Telecom Services Information Excel (Detailed Information for PPT)"),
            ("telecom_pl_excel", "SLTS P&L Summary Excel"),
            ("telecom_bscf_pptx", "Telecom Services BS & CF PowerPoint"),
        ],
    }

    result_sections: Dict[str, Any] = {}
    missing_items: List[str] = []
    all_ready = True

    for sec in ["board_pack", "ratio_report", "mobitel", "telecom_services"]:
        is_selected = sec in selected_sections
        sec_inputs = []
        sec_ready = True

        for role_key, label in req_map[sec]:
            matched_file = next(
                (f["filename"] for f in classified_files if role_key in f.get("roles", []) and f.get("valid")),
                None,
            )
            is_avail = matched_file is not None
            sec_inputs.append({
                "role": role_key,
                "label": label,
                "available": is_avail,
                "filename": matched_file,
            })
            if is_selected and not is_avail:
                sec_ready = False
                all_ready = False
                missing_items.append(f"{label} for {sec.replace('_', ' ').title()}")

        result_sections[sec] = {
            "selected": is_selected,
            "ready": sec_ready if is_selected else True,
            "inputs": sec_inputs,
        }

    return {
        "all_ready": all_ready and len(selected_sections) > 0,
        "sections": result_sections,
        "missing": missing_items,
    }
