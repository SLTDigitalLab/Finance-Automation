"""Reads the uploaded Chart of Accounts workbook used for report labels."""
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Union

import openpyxl


class ChartOfAccountsFormatError(ValueError):
    """The workbook does not contain the required code-to-description sheets."""


@dataclass
class ChartOfAccounts:
    product_categories: Dict[str, str]
    accounts: Dict[str, str]


def normalize_code(value) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    if re.fullmatch(r"[+-]?\d+\.0+", text):
        return text[:text.index(".")]
    return text


def _read_sheet(workbook, sheet_name: str) -> Dict[str, str]:
    if sheet_name not in workbook.sheetnames:
        raise ChartOfAccountsFormatError(f"The Chart of Accounts workbook is missing the '{sheet_name}' sheet.")
    worksheet = workbook[sheet_name]
    header_row = None
    code_column = description_column = None
    for row in worksheet.iter_rows(min_row=1, max_row=min(worksheet.max_row, 20)):
        headers = {
            re.sub(r"[^a-z]", "", str(cell.value or "").lower()): cell.column
            for cell in row
        }
        if "translatedvalue" in headers and "description" in headers:
            header_row = row[0].row
            code_column = headers["translatedvalue"]
            description_column = headers["description"]
            break
    if header_row is None:
        raise ChartOfAccountsFormatError(
            f"The '{sheet_name}' sheet must contain 'Translated Value' and 'Description' columns."
        )

    descriptions: Dict[str, str] = {}
    for row in worksheet.iter_rows(min_row=header_row + 1):
        code = normalize_code(row[code_column - 1].value)
        if not code:
            continue
        description_value = row[description_column - 1].value
        description = str(description_value).strip() if description_value is not None else ""
        if not description:
            continue
        existing = descriptions.get(code)
        if existing is not None and existing != description:
            raise ChartOfAccountsFormatError(
                f"The '{sheet_name}' sheet maps code {code} to more than one description."
            )
        descriptions[code] = description
    if not descriptions:
        raise ChartOfAccountsFormatError(f"The '{sheet_name}' sheet has no code descriptions.")
    return descriptions


def read_chart_of_accounts(source: Union[str, Path, bytes]) -> ChartOfAccounts:
    try:
        if isinstance(source, bytes):
            workbook = openpyxl.load_workbook(BytesIO(source), data_only=True, read_only=True)
        else:
            workbook = openpyxl.load_workbook(source, data_only=True, read_only=True)
    except Exception as exc:
        raise ChartOfAccountsFormatError(f"Could not open the Chart of Accounts workbook: {exc}") from exc
    try:
        return ChartOfAccounts(
            product_categories=_read_sheet(workbook, "Product Category"),
            accounts=_read_sheet(workbook, "Account"),
        )
    finally:
        workbook.close()
