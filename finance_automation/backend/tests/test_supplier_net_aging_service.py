from datetime import datetime
from decimal import Decimal
from pathlib import Path

import openpyxl

from services.supplier_net_aging_service import generate_creditor_aging_report


NETTING_HEADERS = [
    "Source Name",
    "Customer Supplier Name",
    "Supplier Site",
    "Supplier Category",
    "Trx Number",
    "Transaction Date",
    "Gl Date",
    "Due Date",
    "Event Class",
    "Payment Terms",
    "Invoice Type",
    "Transaction Type Name",
    "Trx Currency Code",
    "Invoice Type Lookup Code",
    "Exchange Rate",
    "Period Name",
    "Entered Due Remaining",
]

ERP_HEADERS = [
    "Customer Name",
    "Customer Number",
    "Transaction Number",
    "Trx Type Name",
    "TRX Date",
    "Due Date",
    "Currency Code",
    "Exchange Rate",
    "Natural Account",
    "Entered Amount",
    "Outstanding Amount",
    "Current Bucket",
    "Age 00 - 30",
    "Age 31 - 60",
    "Age 61 - 90",
    "Age 91 - 180",
    "Age 181 - 365",
    "Age 366 - 730",
    "Age 731 - 1095",
    "Age 1096 Above",
]


def _create_sample_workbooks(tmp_path: Path):
    creditor_path = tmp_path / "source-one.xlsx"
    creditor_workbook = openpyxl.Workbook()
    creditor_sheet = creditor_workbook.active
    creditor_sheet.title = "Renamed Netting Data"
    creditor_sheet.append(["A title"])
    creditor_sheet.append(NETTING_HEADERS)
    creditor_sheet.append(
        [
            "Paybles", "Supplier Co. Ltd.", None, None, "invoice", None, None,
            datetime(2026, 10, 15), "Invoice", None, None, None, "USD", None,
            None, None, -100,
        ]
    )
    creditor_sheet.append(
        [
            "Paybles", "Supplier Co. Ltd.", None, None, "debit memo", None, None,
            datetime(2026, 10, 31), "Debit Memo", None, None, None, "USD", None,
            None, None, 20,
        ]
    )
    creditor_sheet.append(
        [
            "Paybles", "Creditor Only LLC", None, None, "credit", None, None,
            datetime(2026, 10, 1), "Invoice", None, None, None, "USD", None,
            None, None, 50,
        ]
    )
    creditor_sheet.append(
        [
            "Paybles", "Telecom Malaysia Berhad", None, None, "invoice-2", None, None,
            datetime(2026, 10, 31), "Invoice", None, None, None, "USD", None,
            None, None, -10,
        ]
    )
    creditor_workbook.save(creditor_path)

    debtor_path = tmp_path / "source-two.xlsx"
    debtor_workbook = openpyxl.Workbook()
    debtor_sheet = debtor_workbook.active
    debtor_sheet.title = "ERP Data"
    debtor_sheet["B2"] = datetime(2026, 10, 31)
    debtor_sheet["A9"] = "Currency:"
    debtor_sheet["B9"] = "USD"
    for _ in range(10, 12):
        debtor_sheet.append([])
    debtor_sheet.append(ERP_HEADERS)
    debtor_sheet.append(
        [
            "Supplier Co", 1, "trx-1", None, None, None, "USD", None, None,
            200, 200, 100, 100, 0, 0, 0, 0, 0, 0, 0,
        ]
    )
    debtor_sheet.append(
        [
            "Debtor Only Inc.", 2, "trx-2", None, None, None, "USD", None, None,
            40, 40, 40, 0, 0, 0, 0, 0, 0, 0, 0,
        ]
    )
    debtor_sheet.append(
        [
            "Telekom Malaysia Berhad", 3, "trx-3", None, None, None, "USD", None, None,
            10, 10, 10, 0, 0, 0, 0, 0, 0, 0, 0,
        ]
    )
    debtor_sheet.append(
        [
            "Sub Total :", None, None, None, None, None, None, None, None,
            250, 250, 150, 100, 0, 0, 0, 0, 0, 0, 0,
        ]
    )
    debtor_sheet.append(
        [
            "Grand Total :", None, None, None, None, None, None, None, None,
            250, 250, 150, 100, 0, 0, 0, 0, 0, 0, 0,
        ]
    )
    debtor_workbook.save(debtor_path)
    return creditor_path, debtor_path


def test_report_uses_column_headers_signed_amounts_and_report_date(tmp_path):
    creditor_path, debtor_path = _create_sample_workbooks(tmp_path)
    output_path = tmp_path / "report.xlsx"

    result = generate_creditor_aging_report(creditor_path, debtor_path, output_path)

    assert result["report_date"].isoformat() == "2026-10-31"
    assert result["currency"] == "USD"
    assert result["debtor_total"] == Decimal("250")
    assert result["creditor_total"] == Decimal("40")
    assert result["net_total"] == Decimal("210")

    workbook = openpyxl.load_workbook(output_path, data_only=True)
    assert workbook.sheetnames == [
        "Creditor Aging Details",
        "Supplier-wise Net Aging",
        "Reconciliation",
    ]
    creditor_sheet = workbook["Creditor Aging Details"]
    assert creditor_sheet.max_row == 6
    assert creditor_sheet["B2"].value == datetime(2026, 10, 31)
    assert creditor_sheet["G2"].value == "USD"
    assert creditor_sheet["H2"].value == -100
    assert creditor_sheet["I2"].value == 100
    assert creditor_sheet["K2"].value == "00-30"
    assert creditor_sheet["H3"].value == 20
    assert creditor_sheet["I3"].value == -20
    assert creditor_sheet["K3"].value == "Current"
    assert creditor_sheet["H6"].value == -40
    assert creditor_sheet["I6"].value == 40
    assert sum(creditor_sheet.cell(6, column).value for column in range(12, 21)) == 40

    supplier_sheet = workbook["Supplier-wise Net Aging"]
    supplier_names = {
        supplier_sheet.cell(row, 1).value
        for row in range(2, supplier_sheet.max_row)
    }
    assert supplier_names == {
        "Supplier Co",
        "Debtor Only Inc.",
        "Creditor Only LLC",
        "Telekom Malaysia Berhad",
    }
    supplier_rows = {
        supplier_sheet.cell(row, 1).value: row
        for row in range(2, supplier_sheet.max_row)
    }
    matched_row = supplier_rows["Supplier Co"]
    assert supplier_sheet.cell(matched_row, 2).value == datetime(2026, 10, 31)
    assert supplier_sheet.cell(matched_row, 6).value == "USD"
    assert supplier_sheet.cell(matched_row, 7).value == 200
    assert supplier_sheet.cell(matched_row, 8).value == 80
    assert supplier_sheet.cell(matched_row, 9).value == 120
    supplier_total_row = supplier_sheet.max_row
    assert supplier_sheet.cell(supplier_total_row, 7).value == 250
    assert supplier_sheet.cell(supplier_total_row, 8).value == 40
    assert supplier_sheet.cell(supplier_total_row, 9).value == 210
    assert sum(supplier_sheet.cell(supplier_total_row, column).value for column in range(10, 19)) == 250
    assert sum(supplier_sheet.cell(supplier_total_row, column).value for column in range(19, 28)) == 40
    assert sum(supplier_sheet.cell(supplier_total_row, column).value for column in range(28, 37)) == 210

    reconciliation = workbook["Reconciliation"]
    assert reconciliation["B4"].value == 250
    assert reconciliation["B8"].value == 40
    assert reconciliation["B13"].value == 210
    assert reconciliation["B6"].value == 0
    assert reconciliation["B10"].value == 0
    assert reconciliation["B14"].value == 210
    assert reconciliation["B15"].value == 0
    mapping_rows = list(
        reconciliation.iter_rows(min_row=19, values_only=True)
    )
    fuzzy_mapping = next(row for row in mapping_rows if row[0] == "Telekom Malaysia Berhad")
    assert fuzzy_mapping[1] == "Telecom Malaysia Berhad"
    assert fuzzy_mapping[3] == "Unique high-similarity name"
    assert fuzzy_mapping[4] == "Matched - review mapping"
    workbook.close()


def test_october_voice_workbooks_reconcile_to_source_totals(tmp_path):
    sample_dir = Path(__file__).resolve().parents[2] / "files"
    creditor_paths = list(sample_dir.glob("*Netting*.xlsx"))
    debtor_paths = list(sample_dir.glob("*Debtor*Voice*.xlsx"))
    if not creditor_paths or not debtor_paths:
        import pytest

        pytest.skip("October Voice sample workbooks are not present.")

    result = generate_creditor_aging_report(
        creditor_paths[0],
        debtor_paths[0],
        tmp_path / "october-voice-report.xlsx",
    )

    assert result["report_date"].isoformat() == "2026-10-31"
    assert result["currency"] == "USD"
    assert result["debtor_total"] == Decimal("2300159.93")
    assert result["creditor_total"] == Decimal("1845203.19")
    assert result["net_total"] == Decimal("454956.74")
