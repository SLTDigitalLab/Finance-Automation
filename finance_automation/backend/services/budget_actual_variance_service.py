import calendar
import re
from copy import copy
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple

import openpyxl
from openpyxl.cell.cell import MergedCell


class BudgetActualInputError(ValueError):
    pass


MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def normalize_code(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.startswith("="):
        return ""
    return text.split(".")[0]


def to_number(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or text.startswith("="):
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_budget(content: bytes) -> Dict:
    try:
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    except Exception as exc:
        raise BudgetActualInputError("The uploaded Budget file is not a readable Excel workbook.") from exc
    ws = wb[wb.sheetnames[0]]
    header_row = None
    month_columns: Dict[int, int] = {}
    year = None
    month_pattern = re.compile(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)[\s\-_/']*(20\d{2}|2\d)",
        re.I,
    )
    for r in range(1, min(ws.max_row, 50) + 1):
        row_months = {}
        row_year = None
        for c in range(1, ws.max_column + 1):
            value = ws.cell(r, c).value
            if not isinstance(value, str):
                continue
            match = month_pattern.search(value)
            if match:
                month = MONTHS.get(match.group(1).lower()[:3])
                if month:
                    row_months[c] = month
                year_text = match.group(2)
                row_year = int(year_text) if len(year_text) == 4 else 2000 + int(year_text)
        if len(row_months) >= 12:
            header_row = r
            month_columns = row_months
            year = row_year
            break
    if header_row is None:
        raise BudgetActualInputError("Could not find twelve monthly budget columns in the Budget workbook.")

    account_col = 1
    for r in range(1, min(ws.max_row, header_row) + 1):
        for c in range(1, ws.max_column + 1):
            value = ws.cell(r, c).value
            if isinstance(value, str) and re.search(r"\baccount\b", value, re.I):
                account_col = c - 1 if c > 1 and ws.cell(r, c - 1).value is None else c
                break
        if account_col != 1:
            break

    names = {}
    values = {}
    header_text = " ".join(
        str(ws.cell(r, c).value)
        for r in range(1, min(ws.max_row, header_row) + 1)
        for c in range(1, ws.max_column + 1)
        if ws.cell(r, c).value is not None
    ).lower()
    explicitly_millions = bool(re.search(r"\b(?:million|millions|mn|m)\b", header_text))
    explicitly_rupees = bool(re.search(r"\blkr\b", header_text)) or bool(re.search(r"\brupees?\b", header_text))
    for r in range(header_row + 1, ws.max_row + 1):
        code = normalize_code(ws.cell(r, account_col).value)
        if not code:
            continue
        name_value = ws.cell(r, account_col + 1).value
        if name_value is not None:
            names[code] = str(name_value).strip()
        row_values = {}
        for c, month in month_columns.items():
            amount = to_number(ws.cell(r, c).value)
            if explicitly_millions:
                converted = amount
            elif explicitly_rupees:
                converted = amount / 1000000
            elif abs(amount) >= 1000000:
                converted = amount / 1000000
            else:
                converted = amount
            row_values[month] = converted
        values[code] = row_values
    wb.close()
    if not values:
        raise BudgetActualInputError("No account rows with budget values were found in the Budget workbook.")
    return {"names": names, "values": values, "year": year}


def read_actual(content: bytes) -> Dict:
    try:
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    except Exception as exc:
        raise BudgetActualInputError("The uploaded Actual file is not a readable Excel workbook.") from exc
    ws = wb[wb.sheetnames[0]]
    month_pattern = re.compile(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\-_/']*(20\d{2}|2\d)",
        re.I,
    )
    month_match = None
    for r in range(1, min(ws.max_row, 12) + 1):
        for c in range(1, ws.max_column + 1):
            value = ws.cell(r, c).value
            if not isinstance(value, str):
                continue
            candidate = month_pattern.search(value)
            if candidate and re.search(r"\b(?:month|ytd)\b", value, re.I) and not re.search(r"\b(?:oct|sep|nov|dec|jan|feb|mar|apr|may|jun|jul|aug)[\s\-_/']*25\b", value, re.I):
                month_match = candidate
                break
        if month_match:
            break
    if month_match is None:
        header_text = " ".join(str(ws.cell(r, c).value) for r in range(1, min(ws.max_row, 12) + 1)
                               for c in range(1, ws.max_column + 1) if ws.cell(r, c).value is not None)
        month_match = month_pattern.search(header_text)
    if not month_match:
        raise BudgetActualInputError("Reporting month and year could not be detected from the Actual workbook.")
    month = MONTHS.get(month_match.group(1).lower()[:3])
    year_text = month_match.group(2)
    year = int(year_text) if len(year_text) == 4 else 2000 + int(year_text)

    names = {}
    values = {}
    for r in range(1, ws.max_row + 1):
        code = normalize_code(ws.cell(r, 1).value)
        if not code:
            continue
        name_value = ws.cell(r, 3).value
        if name_value is not None:
            names[code] = str(name_value).strip()
        # Prefer columns already expressed in millions (H/K/N); fall back to raw rupees (D/E/F).
        monthly_m = to_number(ws.cell(r, 8).value)
        ytd_m = to_number(ws.cell(r, 11).value)
        prior_m = to_number(ws.cell(r, 14).value)
        if monthly_m or ytd_m or prior_m:
            monthly, ytd, prior = monthly_m, ytd_m, prior_m
        else:
            monthly = to_number(ws.cell(r, 4).value)
            ytd = to_number(ws.cell(r, 5).value)
            prior = to_number(ws.cell(r, 6).value)
            monthly = monthly / 1000000 if abs(monthly) >= 100000 else monthly
            ytd = ytd / 1000000 if abs(ytd) >= 100000 else ytd
            prior = prior / 1000000 if abs(prior) >= 100000 else prior
        values[code] = {"monthly": monthly, "ytd": ytd, "prior": prior}
    wb.close()
    if not values:
        raise BudgetActualInputError("No account rows with actual values were found in the Actual workbook.")
    return {"names": names, "values": values, "month": month, "year": year}


def read_mapping(content: bytes) -> Dict:
    try:
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    except Exception as exc:
        raise BudgetActualInputError("The uploaded Mapping file is not a readable Excel workbook.") from exc
    ws = wb[wb.sheetnames[0]]
    groups: Dict[str, List[str]] = {}
    names = {}
    current = ""
    for r in range(1, ws.max_row + 1):
        account_raw = ws.cell(r, 1).value
        account = normalize_code(account_raw)
        if re.fullmatch(r"\d+", account):
            current = account
            if ws.cell(r, 2).value is not None:
                names[current] = str(ws.cell(r, 2).value).strip()
        child_raw = ws.cell(r, 3).value
        child = normalize_code(child_raw)
        if re.fullmatch(r"\d+", child) and current:
            groups.setdefault(current, [])
            if child not in groups[current]:
                groups[current].append(child)
    wb.close()
    return {"groups": groups, "names": names}


def clear_range(ws, min_row, max_row, min_col, max_col):
    for row in ws.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col):
        for cell in row:
            if not isinstance(cell, MergedCell):
                cell.value = None


def unmerge_range(ws, min_row, max_row, min_col, max_col):
    for merged in list(ws.merged_cells.ranges):
        if (
            merged.min_row <= max_row and merged.max_row >= min_row
            and merged.min_col <= max_col and merged.max_col >= min_col
        ):
            ws.unmerge_cells(str(merged))


def copy_sheet(source, target):
    for row in source.iter_rows():
        for src in row:
            dst = target[src.coordinate]
            dst.value = src.value
            if src.has_style:
                dst._style = copy(src._style)
            dst.number_format = src.number_format
            dst.font = copy(src.font)
            dst.fill = copy(src.fill)
            dst.border = copy(src.border)
            dst.alignment = copy(src.alignment)
            dst.protection = copy(src.protection)
    for key, dim in source.column_dimensions.items():
        target.column_dimensions[key].width = dim.width
        target.column_dimensions[key].hidden = dim.hidden
    for key, dim in source.row_dimensions.items():
        target.row_dimensions[key].height = dim.height
        target.row_dimensions[key].hidden = dim.hidden
    for merged in list(source.merged_cells.ranges):
        target.merge_cells(str(merged))


def copy_cached_source(formula_source, cached_source, target):
    for row in formula_source.iter_rows():
        for src in row:
            dst = target[src.coordinate]
            cached = cached_source[src.coordinate].value
            dst.value = cached
            if src.has_style:
                dst._style = copy(src._style)
            dst.number_format = src.number_format
            dst.font = copy(src.font)
            dst.fill = copy(src.fill)
            dst.border = copy(src.border)
            dst.alignment = copy(src.alignment)
            dst.protection = copy(src.protection)
    for key, dim in formula_source.column_dimensions.items():
        target.column_dimensions[key].width = dim.width
        target.column_dimensions[key].hidden = dim.hidden
    for key, dim in formula_source.row_dimensions.items():
        target.row_dimensions[key].height = dim.height
        target.row_dimensions[key].hidden = dim.hidden
    for merged in list(formula_source.merged_cells.ranges):
        target.merge_cells(str(merged))


def generate_budget_actual_report(template_path: Path, budget_content: bytes, actual_content: bytes, mapping_content: bytes) -> Tuple[bytes, Dict]:
    budget = read_budget(budget_content)
    actual = read_actual(actual_content)
    mapping = read_mapping(mapping_content)
    month = actual["month"]
    year = actual["year"]
    if budget["year"] and budget["year"] != year:
        raise BudgetActualInputError(
            f"The Budget workbook year {budget['year']} does not match the Actual reporting year {year}."
        )

    groups = mapping["groups"]

    wb = openpyxl.load_workbook(template_path)
    main = wb["Main Sheet"]
    main["C1"] = f"Budget Vs Actuals - {calendar.month_name[month]} {year}"
    main.freeze_panes = "C5"

    accounts = []
    account_rows = {}
    for r in range(5, main.max_row + 1):
        code = normalize_code(main.cell(r, 1).value)
        if code:
            if code not in account_rows:
                accounts.append(code)
            account_rows.setdefault(code, []).append(r)

    rows = []
    for code in accounts:
        children = groups.get(code, [])
        source_codes = list(dict.fromkeys([code] + children))
        monthly_budget = sum(budget["values"].get(source_code, {}).get(month, 0.0) for source_code in source_codes)
        ytd_budget = sum(
            value
            for source_code in source_codes
            for period, value in budget["values"].get(source_code, {}).items()
            if period <= month
        )
        monthly_actual = sum(actual["values"].get(source_code, {}).get("monthly", 0.0) for source_code in source_codes)
        ytd_actual = sum(actual["values"].get(source_code, {}).get("ytd", 0.0) for source_code in source_codes)
        prior_actual = sum(actual["values"].get(source_code, {}).get("prior", 0.0) for source_code in source_codes)
        name = mapping["names"].get(code) or budget["names"].get(code) or actual["names"].get(code) or ""
        rows.append({
            "code": code,
            "name": name,
            "monthly_budget": monthly_budget,
            "monthly_actual": monthly_actual,
            "ytd_budget": ytd_budget,
            "ytd_actual": ytd_actual,
            "prior_actual": prior_actual,
        })

    month_column = None
    ytd_column = None
    prior_column = None
    month_name = calendar.month_name[month]
    for c in range(1, main.max_column + 1):
        heading = str(main.cell(3, c).value or "")
        if re.search(rf"^\s*Month of\s+{month_name}\b", heading, re.I):
            month_column = c
        if re.search(rf"^\s*YTD\s+{month_name}\s+\d{{2}}", heading, re.I) and not re.search(r"25\s+Vs", heading, re.I):
            ytd_column = c
        if re.search(rf"25\s+Vs\s+{month_name}", heading, re.I):
            prior_column = c
    if month_column is None:
        month_column = 14
    if ytd_column is None:
        ytd_column = month_column + 4
    if prior_column is None:
        prior_column = ytd_column + 4

    for c in range(3, 11):
        clear_range(main, 5, main.max_row, c, c)
    clear_range(main, 5, main.max_row, 11, 12)
    report_columns = [
        month_column, month_column + 1, month_column + 2,
        ytd_column, ytd_column + 1, ytd_column + 2, ytd_column + 3,
        prior_column,
    ]
    subtotal_formulas = {}
    for r in range(5, main.max_row + 1):
        if normalize_code(main.cell(r, 1).value):
            continue
        subtotal_formulas[r] = {
            c: main.cell(r, c).value
            for c in report_columns
            if isinstance(main.cell(r, c).value, str)
            and str(main.cell(r, c).value).startswith("=")
        }
    for c in report_columns:
        clear_range(main, 5, main.max_row, c, c)
    for r, formulas in subtotal_formulas.items():
        for c, formula in formulas.items():
            main.cell(r, c, formula)

    for row in rows:
        code = row["code"]
        for i in account_rows[code]:
            main.cell(i, 2, row["name"] or main.cell(i, 2).value)
            annual_budget = sum(
                budget["values"].get(source_code, {}).get(period, 0.0)
                for source_code in list(dict.fromkeys([code] + groups.get(code, [])))
                for period in range(1, 13)
            )
            main.cell(i, 13, annual_budget)

            mb = month_column
            ma = mb + 1
            mv = mb + 2
            yb = ytd_column
            ya = yb + 1
            yv = yb + 2
            yp = yb + 3
            main.cell(i, mb, row["monthly_budget"])
            main.cell(i, ma, row["monthly_actual"])
            main.cell(i, mv, f"={openpyxl.utils.get_column_letter(mb)}{i}-{openpyxl.utils.get_column_letter(ma)}{i}")
            main.cell(i, yb, row["ytd_budget"])
            main.cell(i, ya, row["ytd_actual"])
            main.cell(i, yv, f"={openpyxl.utils.get_column_letter(yb)}{i}-{openpyxl.utils.get_column_letter(ya)}{i}")
            main.cell(i, yp, f'=IF({openpyxl.utils.get_column_letter(yb)}{i}=0,"",{openpyxl.utils.get_column_letter(yv)}{i}/{openpyxl.utils.get_column_letter(yb)}{i})')
            main.cell(i, prior_column, row["prior_actual"])

    summary = wb["Summary "]
    unmerge_range(summary, 2, summary.max_row, 1, 18)
    clear_range(summary, 2, summary.max_row, 2, 19)
    month_label = calendar.month_abbr[month]
    summary["M1"] = f"YTD Budget {month_label} {year}"
    summary["N1"] = f"YTD Actuals- {month_label} {year}"
    summary["O1"] = f"YTD Variance {month_label} {year}"
    summary["Q1"] = f"Actuals YTD {month_label} {year - 1}"
    summary["R1"] = f"{year - 1} Vs {year} actuals %"
    yb_letter = openpyxl.utils.get_column_letter(ytd_column)
    ya_letter = openpyxl.utils.get_column_letter(ytd_column + 1)
    prior_letter = openpyxl.utils.get_column_letter(prior_column)
    summary_formulas = {}
    template_summary = openpyxl.load_workbook(template_path, data_only=False)["Summary "]
    for r in range(2, template_summary.max_row + 1):
        summary_formulas[r] = {
            c: template_summary.cell(r, c).value
            for c in range(1, 20)
            if template_summary.cell(r, c).value is not None
        }
    for r, values in summary_formulas.items():
        if r == 1:
            continue
        for c, value in values.items():
            if isinstance(value, str) and c in (12, 13, 14, 17):
                value = re.sub(r"\bDI\b", yb_letter, value, flags=re.I)
                value = re.sub(r"\bDJ\b", ya_letter, value, flags=re.I)
                value = re.sub(r"\bDM\b", prior_letter, value, flags=re.I)
            if isinstance(value, str) and c in (12, 13, 14, 17):
                summary.cell(r, c, value)
            elif c == 1:
                summary.cell(r, c, value)
    for r in range(2, summary.max_row + 1):
        label = summary.cell(r, 1).value
        if label:
            summary.cell(r, 15, f'=M{r}-N{r}')
            summary.cell(r, 16, f'=IF(M{r}=0,"",O{r}/M{r})')
            summary.cell(r, 18, f'=IF(Q{r}=0,"",(Q{r}-N{r})/Q{r})')
            for c in range(13, 19):
                summary.cell(r, c).number_format = '0.000;[Red]-0.000'
    summary.freeze_panes = "B2"

    deficits = wb["OCT 26 Deficits"]
    deficits["C1"] = f"Budget Vs Actuals - {calendar.month_name[month]} {year}"
    clear_range(deficits, 5, deficits.max_row, 1, 120)
    template_deficit_count = 0
    template_deficit = openpyxl.load_workbook(template_path, data_only=True)["OCT 26 Deficits"]
    for r in range(5, template_deficit.max_row + 1):
        code = normalize_code(template_deficit.cell(r, 1).value)
        if re.fullmatch(r"\d+", code):
            template_deficit_count += 1
    ranked_deficits = sorted(
        (
            row
            for row in rows
            if row["ytd_actual"] > row["ytd_budget"]
        ),
        key=lambda row: row["ytd_actual"] - row["ytd_budget"],
        reverse=True,
    )
    deficits_rows = ranked_deficits[:template_deficit_count] if template_deficit_count else ranked_deficits
    if not deficits_rows:
        deficits["A5"] = "No deficits"
        deficits["B5"] = "No account has monthly actual greater than monthly budget."
    for i, row in enumerate(deficits_rows, start=5):
        deficits.cell(i, 1, row["code"])
        deficits.cell(i, 2, row["name"])
        deficits.cell(i, 14, row["monthly_budget"])
        deficits.cell(i, 15, row["monthly_actual"])
        deficits.cell(i, 16, f"=N{i}-O{i}")
        deficits.cell(i, 17, f'=IF(N{i}=0,"",P{i}/N{i})')
        deficits.cell(i, ytd_column, row["ytd_budget"])
        deficits.cell(i, ytd_column + 1, row["ytd_actual"])
        deficits.cell(i, ytd_column + 2, f"={openpyxl.utils.get_column_letter(ytd_column)}{i}-{openpyxl.utils.get_column_letter(ytd_column + 1)}{i}")
    deficits.freeze_panes = "C5"

    historical = wb["Actuals Jan 23-Oct 26 "]
    clear_range(historical, 1, historical.max_row, 1, 60)
    historical["A1"] = "Historical Actuals"
    historical["A2"] = "Historical actual data is not available in the uploaded Budget, Actual, or Mapping workbooks."
    historical["A3"] = "ACT CODE"
    historical["B3"] = "ACT NAME"
    historical["C3"] = f"YTD Actual {year - 1}"
    historical["D3"] = f"YTD Actual {year}"
    historical["E3"] = "Data Status"
    for i, row in enumerate(rows, start=4):
        historical.cell(i, 1, row["code"])
        historical.cell(i, 2, row["name"])
        historical.cell(i, 3, row["prior_actual"])
        historical.cell(i, 4, row["ytd_actual"])
        historical.cell(i, 5, "Available from uploaded Actuals" if row["prior_actual"] or row["ytd_actual"] else "Unavailable")

    budget_source_formula = openpyxl.load_workbook(BytesIO(budget_content), data_only=False)
    budget_source_cached = openpyxl.load_workbook(BytesIO(budget_content), data_only=True)
    wb.remove(wb["OCT 26 Budget"])
    budget_sheet = wb.create_sheet("Budget")
    copy_cached_source(
        budget_source_formula[budget_source_formula.sheetnames[0]],
        budget_source_cached[budget_source_cached.sheetnames[0]],
        budget_sheet,
    )
    budget_source_formula.close()
    budget_source_cached.close()

    actual_source_formula = openpyxl.load_workbook(BytesIO(actual_content), data_only=False)
    actual_source_cached = openpyxl.load_workbook(BytesIO(actual_content), data_only=True)
    wb.remove(wb["OCT 26 Actual"])
    actual_sheet = wb.create_sheet("Actual")
    copy_cached_source(
        actual_source_formula[actual_source_formula.sheetnames[0]],
        actual_source_cached[actual_source_cached.sheetnames[0]],
        actual_sheet,
    )
    actual_source_formula.close()
    actual_source_cached.close()
    wb._external_links = []

    wb["Summary "].title = "Summary"
    wb["OCT 26 Deficits"].title = "Deficits"
    wb["Actuals Jan 23-Oct 26 "].title = "Historical Actuals"
    wb._sheets = [
        wb["Main Sheet"], wb["Summary"], wb["Deficits"],
        wb["Historical Actuals"], wb["Budget"], wb["Actual"],
    ]
    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
    try:
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True
        wb.calculation.calcMode = "auto"
    except AttributeError:
        pass
    output = BytesIO()
    wb.save(output)
    wb.close()
    return output.getvalue(), {
        "month": month, "year": year, "account_count": len(rows),
        "mapping_groups": len(groups), "deficit_count": len(deficits_rows),
    }
