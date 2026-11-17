"""
CIP Report Generator
Generates the single-sheet CIP rollforward in the supplied report layout.
"""
from copy import copy
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Dict, List, Tuple, Union
import zipfile

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from .cip_reader import previous_period
from .cip_reconciliation_engine import CIPReconciliationResult

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "cip_report_template.xlsx"
TEMPLATE_ACCOUNT_COUNT = 6

_SUM_FORMULA = re.compile(r"^=SUM\(([A-Z]{1,3}\d+):([A-Z]{1,3}\d+)\)$")
_ADD_FORMULA = re.compile(r"^=\+?([A-Z]{1,3}\d+(?:\+[A-Z]{1,3}\d+)*)$")
_CELL_XML = re.compile(rb'<c\b([^>]*)>(.*?)</c>', re.DOTALL)
_CELL_REFERENCE_XML = re.compile(rb'(?:^|\s)r="([^"]+)"')
_FORMULA_XML = re.compile(rb"<f(?:\s[^>]*)?(?:>.*?</f>|/>)", re.DOTALL)
_VALUE_XML = re.compile(rb"<v(?:\s[^>]*)?>.*?</v>|<v\s*/>", re.DOTALL)


def _calculate_formula_values(worksheet: Worksheet) -> Dict[str, Union[int, float]]:
    """Calculate report formulas for viewers that do not recalculate workbooks."""
    pending = {
        cell.coordinate: cell.value
        for row in worksheet.iter_rows()
        for cell in row
        if cell.data_type == "f"
    }
    calculated: Dict[str, Union[int, float]] = {}

    while pending:
        resolved: List[Tuple[str, Union[int, float]]] = []
        for coordinate, formula in pending.items():
            sum_match = _SUM_FORMULA.fullmatch(formula)
            add_match = _ADD_FORMULA.fullmatch(formula)
            if sum_match:
                min_col, min_row, max_col, max_row = range_boundaries(
                    f"{sum_match.group(1)}:{sum_match.group(2)}"
                )
                references = [
                    worksheet.cell(row, column).coordinate
                    for row in range(min_row, max_row + 1)
                    for column in range(min_col, max_col + 1)
                ]
                ignore_text = True
            elif add_match:
                references = add_match.group(1).split("+")
                ignore_text = False
            else:
                raise ValueError(f"Unsupported CIP report formula in {coordinate}: {formula}")

            if any(reference in pending for reference in references):
                continue

            values = []
            for reference in references:
                value = calculated.get(reference, worksheet[reference].value)
                if value is None:
                    values.append(0)
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.append(value)
                elif ignore_text:
                    continue
                else:
                    raise ValueError(
                        f"CIP report formula in {coordinate} references non-numeric cell {reference}."
                    )

            value = sum(values)
            if isinstance(value, float):
                value = float(format(value, ".15g"))
            resolved.append((coordinate, value))

        if not resolved:
            raise ValueError("Unable to calculate cached values for CIP report formulas.")

        for coordinate, value in resolved:
            calculated[coordinate] = value
            del pending[coordinate]

    return calculated


def _add_formula_cache(output_file: Path, values: Dict[str, Union[int, float]]) -> None:
    """Store calculated formula values alongside formulas in the workbook package."""
    if not values:
        return

    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{output_file.name}.",
        suffix=".tmp",
        dir=output_file.parent,
    )
    os.close(descriptor)
    cached_cells = set()
    try:
        with zipfile.ZipFile(output_file, "r") as source, zipfile.ZipFile(temporary_path, "w") as target:
            for member in source.infolist():
                contents = source.read(member.filename)
                if member.filename == "xl/worksheets/sheet1.xml":
                    def cache_cell(match):
                        attributes, body = match.groups()
                        reference_match = _CELL_REFERENCE_XML.search(attributes)
                        if not reference_match:
                            return match.group(0)
                        reference = reference_match.group(1).decode("ascii")
                        if reference not in values:
                            return match.group(0)
                        if not _FORMULA_XML.search(body):
                            raise ValueError(f"Expected a formula in CIP report cell {reference}.")
                        cached_value = format(values[reference], ".15g").encode("ascii")
                        updated_body, count = _VALUE_XML.subn(
                            lambda _: b"<v>" + cached_value + b"</v>",
                            body,
                            count=1,
                        )
                        if count != 1:
                            raise ValueError(f"Missing cached-value element in CIP report cell {reference}.")
                        cached_cells.add(reference)
                        return b"<c" + attributes + b">" + updated_body + b"</c>"

                    contents = _CELL_XML.sub(cache_cell, contents)
                target.writestr(member, contents)

        missing_cells = set(values) - cached_cells
        if missing_cells:
            raise ValueError(
                f"Unable to write cached values for CIP report cells: {', '.join(sorted(missing_cells))}"
            )
        os.replace(temporary_path, output_file)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


class CIPReportGenerator:
    """Generates the CIP reconciliation workbook from a data-free style template."""

    def __init__(self, recon_result: CIPReconciliationResult):
        self.result = recon_result

    @staticmethod
    def _template_column(
        column: int,
        open_total: int,
        additions_start: int,
        interface_start: int,
        closing_start: int,
        closing_total: int,
    ) -> int:
        if column <= 3:
            return column
        if column < open_total:
            return 4 + min(column - 4, TEMPLATE_ACCOUNT_COUNT - 1)
        if column == open_total:
            return 10
        if additions_start <= column < interface_start:
            return 11 + min(column - additions_start, TEMPLATE_ACCOUNT_COUNT - 1)
        if interface_start <= column < closing_start:
            return 17 + min(column - interface_start, TEMPLATE_ACCOUNT_COUNT - 1)
        if closing_start <= column < closing_total:
            return 23 + min(column - closing_start, TEMPLATE_ACCOUNT_COUNT - 1)
        return 29

    @staticmethod
    def _account_header(account: str) -> Union[int, str]:
        try:
            return int(account)
        except ValueError:
            return account

    @staticmethod
    def _numeric_project_number(project_no: str) -> Union[int, str]:
        try:
            return int(project_no)
        except (TypeError, ValueError):
            return project_no

    def generate(self, output_path: Union[str, Path]) -> Path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        accounts = list(self.result.summary.get("opening", {}))
        if not accounts:
            raise ValueError("Cannot generate the CIP report because no account codes were reconciled.")
        if not TEMPLATE_PATH.is_file():
            raise FileNotFoundError(f"CIP report style template not found: {TEMPLATE_PATH}")

        wb = openpyxl.load_workbook(TEMPLATE_PATH, keep_links=False)
        try:
            if wb.sheetnames != ["Sheet1"]:
                raise ValueError("CIP report template must contain only the Sheet1 reconciliation layout.")
            ws = wb["Sheet1"]
            original_max_column = ws.max_column
            style_map = {
                row: {column: copy(ws.cell(row, column)._style) for column in range(1, original_max_column + 1)}
                for row in range(1, 5)
            }
            width_map = {
                column: ws.column_dimensions[get_column_letter(column)].width
                for column in range(1, original_max_column + 1)
            }
            row_heights = {row: ws.row_dimensions[row].height for row in range(1, 5)}
            for merged_range in list(ws.merged_cells.ranges):
                ws.unmerge_cells(str(merged_range))

            account_count = len(accounts)
            if account_count < TEMPLATE_ACCOUNT_COUNT:
                extra_columns = TEMPLATE_ACCOUNT_COUNT - account_count
                for start in (23, 17, 11, 4):
                    ws.delete_cols(start + account_count, extra_columns)
            elif account_count > TEMPLATE_ACCOUNT_COUNT:
                extra_columns = account_count - TEMPLATE_ACCOUNT_COUNT
                for start in (29, 23, 17, 10):
                    ws.insert_cols(start, extra_columns)

            open_start = 4
            open_total = open_start + account_count
            additions_start = open_total + 1
            interface_start = additions_start + account_count
            closing_start = interface_start + account_count
            closing_total = closing_start + account_count
            last_column = closing_total

            def source_column(column: int) -> int:
                return self._template_column(
                    column,
                    open_total,
                    additions_start,
                    interface_start,
                    closing_start,
                    closing_total,
                )

            for row in range(1, 5):
                for column in range(1, last_column + 1):
                    ws.cell(row, column)._style = copy(style_map[row][source_column(column)])

            for key in list(ws.column_dimensions):
                del ws.column_dimensions[key]
            for column in range(1, last_column + 1):
                ws.column_dimensions[get_column_letter(column)].width = width_map[source_column(column)]
            for row in range(1, 5):
                ws.row_dimensions[row].height = row_heights[row]

            current_date = datetime.strptime(self.result.period, "%b-%y")
            opening_date = datetime.strptime(previous_period(self.result.period), "%b-%y")
            current_heading = current_date.strftime("%b%Y")
            opening_heading = opening_date.strftime("%b%Y")
            ws.merge_cells(start_row=1, start_column=open_start, end_row=1, end_column=open_total)
            ws.merge_cells(
                start_row=1,
                start_column=additions_start,
                end_row=1,
                end_column=interface_start - 1,
            )
            ws.merge_cells(
                start_row=1,
                start_column=interface_start,
                end_row=1,
                end_column=closing_start - 1,
            )
            ws.merge_cells(start_row=1, start_column=closing_start, end_row=1, end_column=closing_total)
            ws.cell(1, open_start).value = opening_heading
            ws.cell(1, additions_start).value = f"Additions {current_date.strftime('%b')}'{current_date.year}"
            ws.cell(1, interface_start).value = f"Interface {current_heading}"
            ws.cell(1, closing_start).value = f"Balance {current_heading}"

            ws.cell(2, 1).value = "Project No"
            ws.cell(2, 2).value = "Project Name"
            ws.cell(2, 3).value = "Year"
            for index, account in enumerate(accounts):
                ws.cell(2, open_start + index).value = self._account_header(account)
                ws.cell(2, additions_start + index).value = self._account_header(account)
                ws.cell(2, interface_start + index).value = self._account_header(account)
                ws.cell(2, closing_start + index).value = self._account_header(account)
            ws.cell(2, open_total).value = "Total"
            ws.cell(2, closing_total).value = "Total"

            missing_opening_projects = {
                row.get("project_no")
                for row in self.result.discrepancies
                if row.get("type") == "Missing Opening Balance"
            }
            projects = [
                project
                for project in self.result.projects
                if project["project_no"] not in missing_opening_projects
            ]
            if not projects:
                raise ValueError(
                    "Cannot generate the CIP report because no projects have prior-period opening balances."
                )
            has_unallocated_additions = bool(self.result.unallocated_additions)
            unallocated_row = 3 + len(projects) if has_unallocated_additions else None
            total_row = 3 + len(projects) + int(has_unallocated_additions)
            for row in range(3, total_row + 1):
                style_row = 4 if row == total_row else 3
                for column in range(1, last_column + 1):
                    ws.cell(row, column)._style = copy(style_map[style_row][source_column(column)])
                ws.row_dimensions[row].height = row_heights[style_row]

            for index, project in enumerate(projects, start=3):
                ws.cell(index, 1).value = self._numeric_project_number(project["project_no"])
                ws.cell(index, 2).value = project.get("project_name", "")
                ws.cell(index, 3).value = project.get("year")
                for account_index, account in enumerate(accounts):
                    ws.cell(index, open_start + account_index).value = project["opening"].get(account)
                    ws.cell(index, additions_start + account_index).value = project["additions"].get(account)
                    ws.cell(index, interface_start + account_index).value = project["interface"].get(account)
                    if project["closing"].get(account) is not None:
                        open_cell = get_column_letter(open_start + account_index)
                        additions_cell = get_column_letter(additions_start + account_index)
                        interface_cell = get_column_letter(interface_start + account_index)
                        ws.cell(index, closing_start + account_index).value = (
                            f"=+{open_cell}{index}+{additions_cell}{index}+{interface_cell}{index}"
                        )

            missing_opening_accounts = {
                row.get("account")
                for row in self.result.discrepancies
                if row.get("type") == "Missing Opening Balance Account"
            }
            if unallocated_row is not None:
                ws.cell(unallocated_row, 2).value = "Unmapped Journal Activity"
                for account_index, account in enumerate(accounts):
                    amount = self.result.unallocated_additions.get(account)
                    if amount is None or account in missing_opening_accounts:
                        continue
                    additions_cell = get_column_letter(additions_start + account_index)
                    open_cell = get_column_letter(open_start + account_index)
                    interface_cell = get_column_letter(interface_start + account_index)
                    ws.cell(unallocated_row, additions_start + account_index).value = amount
                    ws.cell(unallocated_row, closing_start + account_index).value = (
                        f"=+{open_cell}{unallocated_row}+{additions_cell}{unallocated_row}"
                        f"+{interface_cell}{unallocated_row}"
                    )
                if not missing_opening_accounts:
                    closing_start_letter = get_column_letter(closing_start)
                    closing_end_letter = get_column_letter(closing_total - 1)
                    ws.cell(unallocated_row, closing_total).value = (
                        f"=SUM({closing_start_letter}{unallocated_row}:{closing_end_letter}{unallocated_row})"
                    )

            for index, account in enumerate(accounts):
                if account not in missing_opening_accounts:
                    opening_cell = get_column_letter(open_start + index)
                    closing_cell = get_column_letter(closing_start + index)
                    ws.cell(total_row, open_start + index).value = (
                        f"=SUM({opening_cell}3:{opening_cell}{total_row - 1})"
                    )
                    ws.cell(total_row, closing_start + index).value = (
                        f"=SUM({closing_cell}3:{closing_cell}{total_row - 1})"
                    )
                for column in (
                    additions_start + index,
                    interface_start + index,
                ):
                    column_letter = get_column_letter(column)
                    ws.cell(total_row, column).value = (
                        f"=SUM({column_letter}3:{column_letter}{total_row - 1})"
                    )

            if not missing_opening_accounts:
                open_total_letter = get_column_letter(open_total)
                closing_total_letter = get_column_letter(closing_total)
                ws.cell(total_row, open_total).value = (
                    f"=SUM({open_total_letter}3:{open_total_letter}{total_row - 1})"
                )
                ws.cell(total_row, closing_total).value = (
                    f"=SUM({closing_total_letter}3:{closing_total_letter}{total_row - 1})"
                )

            for index, project in enumerate(projects, start=3):
                if project.get("opening_total") is not None and not missing_opening_accounts:
                    open_start_letter = get_column_letter(open_start)
                    open_end_letter = get_column_letter(open_total - 1)
                    ws.cell(index, open_total).value = (
                        f"=SUM({open_start_letter}{index}:{open_end_letter}{index})"
                    )
                if project.get("closing_total") is not None and not missing_opening_accounts:
                    closing_start_letter = get_column_letter(closing_start)
                    closing_end_letter = get_column_letter(closing_total - 1)
                    ws.cell(index, closing_total).value = (
                        f"=SUM({closing_start_letter}{index}:{closing_end_letter}{index})"
                    )

            wb._external_links = []
            wb.calculation.fullCalcOnLoad = True
            wb.calculation.forceFullCalc = True
            wb.calculation.calcMode = "auto"
            formula_values = _calculate_formula_values(ws)
            wb.save(output_file)
        finally:
            wb.close()
        _add_formula_cache(output_file, formula_values)
        logger.info("Successfully generated CIP reconciliation report at %s", output_file)
        return output_file
