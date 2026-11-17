"""Creates an isolated journal review workbook with project mappings and safe corrections."""
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import openpyxl
import pandas as pd

from .cip_reader import (
    CIPInputError,
    build_project_code_lookup,
    clean_project_num,
    normalize_project_code,
)

logger = logging.getLogger(__name__)


def _header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _header_row(rows: List[List[Any]]) -> Optional[Tuple[int, Dict[str, int]]]:
    for row_index, row in enumerate(rows):
        headers = {_header_key(value): col for col, value in enumerate(row) if value is not None}
        if "dr" in headers and "cr" in headers:
            return row_index, headers
    return None


def _project_value(project_number: str) -> Union[str, int]:
    return int(project_number) if project_number.isdigit() else project_number


def _is_summary_row(row: List[Any], headers: Dict[str, int]) -> bool:
    summary_labels = {"total", "subtotal", "subtotals", "grandtotal"}
    return any(
        index < len(row) and _header_key(row[index]) in summary_labels
        for key in ("category", "source")
        if (index := headers.get(key)) is not None
    )


class CIPJournalReviewGenerator:
    """Writes changes to a new workbook and never alters the uploaded journal file."""

    @staticmethod
    def generate(
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        project_master: Dict[str, Dict[str, Any]],
        adjustments: List[Dict[str, Any]],
    ) -> Path:
        source = Path(input_path)
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        project_lookup, _ = build_project_code_lookup(project_master)
        adjustment_map = {
            (item["sheet"], item["row_number"]): item
            for item in adjustments
            if item.get("status") == "applied_to_copy"
            and item.get("sheet")
            and item.get("row_number")
        }

        if source.suffix.lower() in {".xlsx", ".xlsm"}:
            wb = openpyxl.load_workbook(source, data_only=False, keep_vba=False)
            try:
                for ws in wb.worksheets:
                    rows = [list(row) for row in ws.iter_rows(values_only=True)]
                    header = _header_row(rows)
                    if not header:
                        continue
                    header_index, headers = header
                    future_col = headers.get("future")
                    project_col = 20
                    existing_project_col = headers.get("project")
                    if existing_project_col is not None and existing_project_col != project_col:
                        raise CIPInputError(
                            f"{source.name}, sheet '{ws.title}': Project column is not column U."
                        )
                    project_header = ws.cell(header_index + 1, project_col + 1)
                    if project_header.value is not None and _header_key(project_header.value) not in {"project", "projectnumber"}:
                        raise CIPInputError(
                            f"{source.name}, sheet '{ws.title}': column U is already used by another field."
                        )
                    project_header.value = project_header.value or "Project"

                    for row_number in range(header_index + 2, ws.max_row + 1):
                        if _is_summary_row(rows[row_number - 1], headers):
                            continue
                        amount_cells = (
                            ws.cell(row_number, headers["dr"] + 1),
                            ws.cell(row_number, headers["cr"] + 1),
                        )
                        if any(
                            cell.data_type == "f"
                            or (isinstance(cell.value, str) and cell.value.startswith("="))
                            for cell in amount_cells
                        ):
                            continue
                        future = ws.cell(row_number, future_col + 1).value if future_col is not None else None
                        direct_project = clean_project_num(future)
                        mapped_project = (
                            direct_project
                            if direct_project in project_master
                            else project_lookup.get(normalize_project_code(future))
                        )
                        project_cell = ws.cell(row_number, project_col + 1)
                        existing_project = clean_project_num(project_cell.value)
                        if mapped_project:
                            project_cell.value = _project_value(mapped_project)
                        elif project_cell.data_type == "f" or (
                            isinstance(project_cell.value, str) and project_cell.value.startswith("=")
                        ) or (isinstance(project_cell.value, str) and project_cell.value.startswith("#")):
                            project_cell.value = None

                        adjustment = adjustment_map.get((ws.title, row_number))
                        if adjustment:
                            ws.cell(row_number, headers["dr"] + 1).value = adjustment["adjusted_dr"]
                            ws.cell(row_number, headers["cr"] + 1).value = adjustment["adjusted_cr"]
                        elif existing_project and not mapped_project:
                            project_cell.value = _project_value(existing_project)
                wb.save(destination)
            finally:
                wb.close()
        else:
            CIPJournalReviewGenerator._convert_xls(
                source,
                destination,
                project_master,
                project_lookup,
                adjustment_map,
            )

        logger.info("Generated journal review workbook at %s", destination)
        return destination

    @staticmethod
    def _convert_xls(
        source: Path,
        destination: Path,
        project_master: Dict[str, Dict[str, Any]],
        project_lookup: Dict[str, str],
        adjustment_map: Dict[Tuple[str, int], Dict[str, Any]],
    ) -> None:
        workbook = openpyxl.Workbook()
        workbook.remove(workbook.active)
        excel = pd.ExcelFile(source, engine="xlrd")
        for sheet in excel.sheet_names:
            frame = pd.read_excel(source, sheet_name=sheet, header=None, engine="xlrd")
            rows = frame.values.tolist()
            ws = workbook.create_sheet(title=sheet[:31])
            for row_index, row in enumerate(rows, start=1):
                for col_index, value in enumerate(row, start=1):
                    if value is not None and not (isinstance(value, float) and pd.isna(value)):
                        ws.cell(row_index, col_index).value = value
            header = _header_row(rows)
            if not header:
                continue
            header_index, headers = header
            future_col = headers.get("future")
            if headers.get("project") not in (None, 20):
                raise CIPInputError(f"{source.name}, sheet '{sheet}': Project column is not column U.")
            if ws.cell(header_index + 1, 21).value not in (None, "Project", "Project Number"):
                raise CIPInputError(f"{source.name}, sheet '{sheet}': column U is already used by another field.")
            ws.cell(header_index + 1, 21).value = "Project"

            for row_number in range(header_index + 2, len(rows) + 1):
                if _is_summary_row(rows[row_number - 1], headers):
                    continue
                future = ws.cell(row_number, future_col + 1).value if future_col is not None else None
                direct_project = clean_project_num(future)
                mapped_project = (
                    direct_project
                    if direct_project in project_master
                    else project_lookup.get(normalize_project_code(future))
                )
                if mapped_project:
                    ws.cell(row_number, 21).value = _project_value(mapped_project)
                adjustment = adjustment_map.get((sheet, row_number))
                if adjustment:
                    ws.cell(row_number, headers["dr"] + 1).value = adjustment["adjusted_dr"]
                    ws.cell(row_number, headers["cr"] + 1).value = adjustment["adjusted_cr"]
        workbook.save(destination)
        workbook.close()
