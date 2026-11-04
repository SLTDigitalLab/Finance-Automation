from pathlib import Path
import re

import openpyxl
import pytest

from services.accrual_entry_report_service import (
    _format_amount,
    _prefix_from_history,
    generate_accrual_entry_report,
)

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "files" / "New folder"
PAYMENT_FILE = SAMPLE_DIR / "Payment details Sep 26.xlsx"
PRIOR_FILE = SAMPLE_DIR / "Accrual-Aug 26.xlsx"
ACCOUNT_ANALYSIS_FILE = SAMPLE_DIR / "Account analysis Sep 26.xlsx"
REFERENCE_FILE = SAMPLE_DIR / "Accrual-Sep26.xlsx"


def test_format_amount_avoids_grouping_separators_in_journal_description():
    assert _format_amount(1234.5, "#,##0.00") == "1234.50"


def test_prefix_from_history_prefers_matching_contract_reference():
    prior_entries = [
        {"account": "511106", "description": "ORANGE SA-LD018565-$1810.00-AUG26"},
        {"account": "511106", "description": "Orange-LD015840-$1810.00-AUG26"},
    ]

    assert (
        _prefix_from_history("511106", "Orange-SA", "LD015840/LD014952", prior_entries)
        == "Orange-LD015840"
    )


@pytest.mark.skipif(
    not all(
        path.exists()
        for path in (PAYMENT_FILE, PRIOR_FILE, ACCOUNT_ANALYSIS_FILE, REFERENCE_FILE)
    ),
    reason="sample accrual workbooks are not present",
)
def test_sample_current_period_entries_match_reference(tmp_path):
    output_path = tmp_path / "accrual-report.xlsx"
    result = generate_accrual_entry_report(
        PAYMENT_FILE,
        PRIOR_FILE,
        ACCOUNT_ANALYSIS_FILE,
        "Sep-26",
        output_path,
    )

    def period_entries(path):
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            worksheet = workbook["Entry Origain (4)"]
            entries = []
            for row in worksheet.iter_rows(min_row=3, max_col=12, values_only=True):
                account, amount, description = row[5], row[9], row[11]
                if account is None or amount is None or not description:
                    continue
                is_period_entry = "SEP26" in str(description).upper()
                has_september_date = any(
                    int(month) == 9 and int(year) == 26
                    for month, year in re.findall(r"\d{1,2}\.(\d{2})\.(\d{2})", str(description))
                )
                if is_period_entry or has_september_date:
                    entries.append((str(account), round(float(amount), 2), str(description)))
            return set(entries)
        finally:
            workbook.close()

    assert period_entries(output_path) == period_entries(REFERENCE_FILE)
    assert result["current_period_entries"] == 41

    workbook = openpyxl.load_workbook(output_path, read_only=True)
    try:
        assert workbook.sheetnames == [
            "Entry Origain (6)",
            "Entry Origain (7)",
            "Entry Origain (4)",
        ]
    finally:
        workbook.close()
