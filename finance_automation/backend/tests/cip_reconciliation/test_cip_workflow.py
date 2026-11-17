import openpyxl
import pytest

from services.cip_reconciliation.cip_journal_review_generator import CIPJournalReviewGenerator
from services.cip_reconciliation.cip_reader import CIPInputError, CIPReader
from services.cip_reconciliation.cip_reconciliation_engine import CIPReconciliationEngine
from services.cip_reconciliation.cip_report_generator import CIPReportGenerator
from services.cip_reconciliation.cip_store import CATEGORIES


def test_journal_formula_rows_are_skipped_and_unique_correction_uses_copy(tmp_path):
    account = "987654"
    source_path = tmp_path / "journal.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = account
    worksheet.append(["Category", "Source", "Future", "DR", "CR"])
    worksheet.append(["Normal", "Manual", "ABC", 80, 0])
    worksheet.append(["Normal", "Assets", "ABC", 0, 25])
    worksheet.append(["Total", "Manual", "ABC", "=SUM(D2:D3)", 0])
    worksheet.append(["Normal", "Projects", 123457, 3, 0])
    workbook.save(source_path)
    workbook.close()

    project_master = {"123456": {"project_code": "ABC"}, "123457": {"project_code": "XYZ"}}
    journal_summary, journal_rows = CIPReader.read_journal_details(source_path, project_master)
    assert len(journal_rows) == 3
    assert journal_rows[0]["project"] == "123456"
    assert journal_rows[2]["project"] == "123457"
    assert journal_summary[account]["sources"]["manual"]["net"] == 80
    assert journal_summary[account]["sources"]["projects"]["net"] == 3
    assert journal_summary[account]["sources"]["assets"]["net"] == -25

    result = CIPReconciliationEngine(
        project_master=project_master,
        subledger_additions={"123456": {account: 100}},
        interfaced_cip={"123456": {account: 30}},
        gl_summary=journal_summary,
        journal_rows=journal_rows,
        period="Mar-26",
    ).run()
    corrections = {row["kind"]: row for row in result.journal_adjustments}
    assert corrections["additions"]["status"] == "applied_to_copy"
    assert corrections["additions"]["adjusted_dr"] == 100
    assert corrections["interface"]["status"] == "applied_to_copy"
    assert corrections["interface"]["adjusted_cr"] == 30

    review_path = tmp_path / "journal-review.xlsx"
    CIPJournalReviewGenerator.generate(
        source_path,
        review_path,
        project_master,
        result.journal_adjustments,
    )

    original = openpyxl.load_workbook(source_path, data_only=True)
    review = openpyxl.load_workbook(review_path, data_only=True)
    try:
        assert original[account]["D2"].value == 80
        assert original[account]["U2"].value is None
        assert original[account]["E3"].value == 25
        assert original[account]["U4"].value is None
        assert original[account]["U5"].value is None
        assert review[account]["D2"].value == 100
        assert review[account]["U2"].value == 123456
        assert review[account]["E3"].value == 30
        assert review[account]["U4"].value is None
        assert review[account]["U5"].value == 123457
    finally:
        original.close()
        review.close()


def test_opening_balances_discover_account_codes_from_report_headers(tmp_path):
    accounts = ["987654", "987655"]
    source_path = tmp_path / "prior-report.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.cell(1, 4, "Balance Feb2026")
    worksheet.cell(2, 1, "Project No")
    for offset, account in enumerate(accounts):
        worksheet.cell(2, 4 + offset, int(account))
    worksheet.cell(3, 1, 123456)
    worksheet.cell(3, 4, 10)
    workbook.save(source_path)
    workbook.close()

    balances = CIPReader.read_opening_balances(source_path, expected_period="Feb-26")
    assert balances["123456"] == {"987654": 10, "987655": None}
    with pytest.raises(CIPInputError, match="expected closing balances for Mar-26"):
        CIPReader.read_opening_balances(source_path, expected_period="Mar-26")


def test_project_year_uses_master_start_date_and_reports_code_mismatch(tmp_path):
    source_path = tmp_path / "project-master.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append([
        "Project Number",
        "Project Name",
        "Project Code",
        "Project Type",
        "Project Manager",
        "Start Date",
    ])
    worksheet.append([241234, "Project", "A1", "Capital", "Manager", "01-MAY-25 12.00.00.000000000 AM"])
    workbook.save(source_path)
    workbook.close()

    project_master = CIPReader.read_project_master(source_path)
    result = CIPReconciliationEngine(
        project_master=project_master,
        subledger_additions={},
        interfaced_cip={},
        gl_summary={},
        opening_balances={"241234": {"987654": 10}},
        period="Mar-26",
    ).run()

    assert project_master["241234"]["project_year"] == 2025
    assert result.projects[0]["year"] == 2025
    assert any(
        item["type"] == "Project Year Mapping Variance"
        and item["project_no"] == "241234"
        for item in result.discrepancies
    )


def test_subledger_discovers_account_code_from_sheet_name(tmp_path):
    source_path = tmp_path / "subledger.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "987654"
    worksheet.append(["Project Number", "Project Name", "Task Name", "Expenditure Type", "Total Cost"])
    worksheet.append([123456, "Project", "Task", "Labor", 35])
    workbook.save(source_path)
    workbook.close()

    additions, _ = CIPReader.read_subledger_detail(source_path)
    assert additions == {"123456": {"987654": 35}}


def test_journal_future_project_number_maps_without_a_project_code(tmp_path):
    source_path = tmp_path / "journal.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "987654"
    worksheet.append(["Category", "Source", "Future", "DR", "CR"])
    worksheet.append(["Normal", "Cost Management", 123456, 10, 0])
    worksheet.append(["Normal", "Cost Management", "NO_MATCH", 5, 0])
    workbook.save(source_path)
    workbook.close()

    summary, rows = CIPReader.read_journal_details(
        source_path,
        {"123456": {"project_code": ""}},
    )
    assert rows[0]["project"] == "123456"
    assert rows[0]["project_mapping_status"] == "mapped"
    assert rows[1]["project"] is None
    assert rows[1]["project_mapping_status"] == "unmatched_code"

    result = CIPReconciliationEngine(
        project_master={"123456": {"project_code": ""}},
        subledger_additions={"123456": {"987654": 10}},
        interfaced_cip={},
        gl_summary=summary,
        opening_balances={"123456": {"987654": 0}},
        period="Mar-26",
        journal_rows=rows,
    ).run()
    assert any(item["type"] == "Unmatched Project Code" for item in result.discrepancies)


def test_trial_balance_reads_current_period_from_column_e(tmp_path):
    account = "987654"
    source_path = tmp_path / "trial-balance.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(["Account", "YTD Actual", None, None, "YTD Actual"])
    worksheet.append([None, "Feb-26", None, None, "Mar-26"])
    worksheet.append([int(account), 10, None, None, 20])
    worksheet["C3"] = "Current Period:Mar-26"
    workbook.save(source_path)
    workbook.close()

    balances = CIPReader.read_trial_balance(source_path, "Mar-26")
    assert balances["period"] == "Mar-26"
    assert balances["opening_period"] == "Feb-26"
    assert balances["opening_balances"][account] == 10
    assert balances["balances"][account] == 20
    with pytest.raises(CIPInputError, match="current period is Mar-26"):
        CIPReader.read_trial_balance(source_path, "Apr-26")


def test_report_uses_dynamic_accounts_and_original_single_sheet_layout(tmp_path):
    account = "987654"
    result = CIPReconciliationEngine(
        project_master={"123456": {"project_code": "ABC", "project_name": "Project"}},
        subledger_additions={"123456": {account: 5}},
        interfaced_cip={"123456": {account: 2}},
        gl_summary={
            account: {
                "sources": {
                    "assets": {"source": "Assets", "net": 2},
                }
            }
        },
        opening_balances={"123456": {account: 1}},
        period="Mar-26",
        trial_balance={
            "period": "Mar-26",
            "balances": {account: 12},
            "opening_balances": {account: 3},
        },
    ).run()
    report_path = tmp_path / "reconciliation.xlsx"
    CIPReportGenerator(result).generate(report_path)

    workbook = openpyxl.load_workbook(report_path, data_only=False, keep_links=False)
    try:
        assert workbook.sheetnames == ["Sheet1"]
        worksheet = workbook["Sheet1"]
        assert worksheet.max_column == 9
        assert worksheet["D2"].value == int(account)
        assert worksheet["F2"].value == int(account)
        assert worksheet["G2"].value == int(account)
        assert worksheet["H2"].value == int(account)
        assert worksheet["D1"].value == "Feb2026"
        assert worksheet["F1"].value == "Additions Mar'2026"
        assert worksheet["G1"].value == "Interface Mar2026"
        assert worksheet["H1"].value == "Balance Mar2026"
        assert worksheet["D3"].value == 1
        assert worksheet["F3"].value == 5
        assert worksheet["G3"].value == 2
        assert worksheet["E3"].value == "=SUM(D3:D3)"
        assert worksheet["H3"].value == "=+D3+F3+G3"
        assert worksheet["I3"].value == "=SUM(H3:H3)"
        assert worksheet["D4"].value == "=SUM(D3:D3)"
        assert worksheet["E4"].value == "=SUM(E3:E3)"
        assert worksheet["F4"].value == "=SUM(F3:F3)"
        assert worksheet["G4"].value == "=SUM(G3:G3)"
        assert worksheet["H4"].value == "=SUM(H3:H3)"
        assert worksheet["I4"].value == "=SUM(I3:I3)"
        assert worksheet.max_row == 4
        assert not any(
            "Trial Balance Validation" in str(cell.value)
            for row in worksheet.iter_rows()
            for cell in row
        )
        assert workbook.calculation.fullCalcOnLoad
        assert not workbook._external_links
    finally:
        workbook.close()

    next_opening = CIPReader.read_opening_balances(report_path, expected_period="Mar-26")
    assert next_opening["123456"][account] == 8
    account_result = result.account_reconciliations[0]
    assert account_result["trial_balance_variance"] == -4
    assert account_result["opening_trial_balance_variance"] == -2


def test_report_expands_all_rollforward_blocks_for_additional_accounts(tmp_path):
    accounts = [str(987600 + index) for index in range(7)]
    result = CIPReconciliationEngine(
        project_master={"123456": {"project_name": "Project"}},
        subledger_additions={"123456": {account: 2 for account in accounts}},
        interfaced_cip={"123456": {account: 3 for account in accounts}},
        gl_summary={},
        opening_balances={"123456": {account: 1 for account in accounts}},
        period="Mar-26",
        trial_balance={"balances": {account: 10 for account in accounts}},
    ).run()
    report_path = tmp_path / "expanded-report.xlsx"
    CIPReportGenerator(result).generate(report_path)

    workbook = openpyxl.load_workbook(report_path, data_only=False, keep_links=False)
    try:
        worksheet = workbook["Sheet1"]
        assert worksheet.max_column == 33
        assert worksheet["J2"].value == int(accounts[-1])
        assert worksheet["AG3"].value == "=SUM(Z3:AF3)"
        assert worksheet["AG4"].value == "=SUM(AG3:AG3)"
        assert {"D1:K1", "L1:R1", "S1:Y1", "Z1:AG1"}.issubset(
            {str(merged_range) for merged_range in worksheet.merged_cells.ranges}
        )
    finally:
        workbook.close()


def test_missing_trial_balance_account_is_reported_without_forcing_a_value():
    account = "987654"
    result = CIPReconciliationEngine(
        project_master={},
        subledger_additions={"123456": {account: 5}},
        interfaced_cip={},
        gl_summary={},
        opening_balances={},
        period="Mar-26",
        trial_balance={"balances": {}},
    ).run()

    validation = result.trial_balance_reconciliations[0]
    assert validation["trial_balance_closing"] is None
    assert validation["variance"] is None
    assert validation["status"] == "Missing Trial Balance Account"
    assert any(item["type"] == "Missing Trial Balance Account" for item in result.discrepancies)
    assert any(item["type"] == "Missing Opening Balance" for item in result.discrepancies)


def test_trial_balance_is_not_a_required_upload_and_missing_opening_is_not_assumed_zero(tmp_path):
    account = "987654"
    assert "trial_balance" not in CATEGORIES
    result = CIPReconciliationEngine(
        project_master={"123456": {"project_name": "Opening project"}, "123457": {"project_name": "New project"}},
        subledger_additions={"123457": {account: 5}},
        interfaced_cip={},
        gl_summary={},
        opening_balances={"123456": {account: 10}},
        period="Mar-26",
    ).run()

    missing_opening = next(project for project in result.projects if project["project_no"] == "123457")
    assert missing_opening["opening_total"] is None
    assert missing_opening["closing"][account] is None
    assert missing_opening["closing_total"] is None
    assert not result.trial_balance_reconciliations
    assert not any(item["type"] == "Missing Trial Balance Account" for item in result.discrepancies)

    report_path = tmp_path / "report-with-missing-opening.xlsx"
    CIPReportGenerator(result).generate(report_path)
    workbook = openpyxl.load_workbook(report_path, data_only=False, keep_links=False)
    try:
        worksheet = workbook["Sheet1"]
        assert worksheet.max_row == 4
        assert worksheet["A3"].value == 123456
        assert worksheet["A4"].value is None
        assert worksheet["H3"].value == "=+D3+F3+G3"
    finally:
        workbook.close()


def test_unique_interface_difference_is_excluded_and_reported():
    account = "987654"
    result = CIPReconciliationEngine(
        project_master={},
        subledger_additions={},
        interfaced_cip={
            "123456": {account: 90},
            "123457": {account: 10},
        },
        gl_summary={
            account: {
                "sources": {
                    "assets": {"source": "Assets", "net": -90},
                }
            }
        },
        opening_balances={
            "123456": {account: 100},
            "123457": {account: 200},
        },
        period="Mar-26",
    ).run()

    projects = {row["project_no"]: row for row in result.projects}
    assert projects["123456"]["interface"][account] == -90
    assert account not in projects["123457"]["interface"]
    assert projects["123457"]["closing"][account] == 200
    assert result.account_reconciliations[0]["interface_variance"] == -10
    assert any(
        item["type"] == "Unmatched Interface Movement"
        and item["project_no"] == "123457"
        and item["amount"] == -10
        for item in result.discrepancies
    )


def test_journal_addition_fills_missing_project_account_without_overwriting_subledger():
    account = "987654"
    result = CIPReconciliationEngine(
        project_master={"123456": {}, "123457": {}},
        subledger_additions={"123456": {account: 5}},
        interfaced_cip={},
        gl_summary={
            account: {
                "sources": {
                    "costmanagement": {"source": "Cost Management", "net": 15},
                }
            }
        },
        opening_balances={
            "123456": {account: 100},
            "123457": {account: 100},
        },
        period="Mar-26",
        journal_rows=[
            {"account": account, "source": "Cost Management", "project": "123456", "net": 10},
            {"account": account, "source": "Cost Management", "project": "123457", "net": 5},
        ],
    ).run()

    projects = {row["project_no"]: row for row in result.projects}
    assert projects["123456"]["additions"][account] == 5
    assert projects["123457"]["additions"][account] == 5
    assert result.summary["subledger_additions"][account] == 5
    assert result.summary["additions"][account] == 10
    assert any(
        item["type"] == "Journal Addition Missing from Subledger"
        and item["project_no"] == "123457"
        and item["amount"] == 5
        for item in result.discrepancies
    )


def test_unmapped_journal_addition_is_reported_as_unallocated_and_included_in_report(tmp_path):
    account = "987654"
    opening = 100
    addition = 25
    result = CIPReconciliationEngine(
        project_master={"123456": {"project_name": "Project"}},
        subledger_additions={},
        interfaced_cip={},
        gl_summary={
            account: {
                "sources": {
                    "payables": {"source": "Payables", "net": addition},
                }
            }
        },
        opening_balances={"123456": {account: opening}},
        period="Mar-26",
        trial_balance={
            "balances": {account: opening + addition},
            "opening_balances": {account: opening},
        },
        journal_rows=[{
            "account": account,
            "source": "Payables",
            "project": None,
            "net": addition,
            "row_number": 11,
        }],
    ).run()

    assert result.unallocated_additions == {account: addition}
    assert result.summary["closing"][account] == opening + addition
    assert result.trial_balance_reconciliations[0]["status"] == "Reconciled"
    assert any(
        item["type"] == "Unmapped Journal Transaction"
        and item["account"] == account
        and item["amount"] == addition
        for item in result.discrepancies
    )

    report_path = tmp_path / "report-with-unallocated-journal.xlsx"
    CIPReportGenerator(result).generate(report_path)
    workbook = openpyxl.load_workbook(report_path, data_only=False)
    try:
        worksheet = workbook["Sheet1"]
        assert worksheet["A4"].value is None
        assert worksheet["B4"].value == "Unmapped Journal Activity"
        assert worksheet["F4"].value == addition
        assert worksheet["H4"].value == "=+D4+F4+G4"
        assert worksheet["F5"].value == "=SUM(F3:F4)"
        assert worksheet["H5"].value == "=SUM(H3:H4)"
    finally:
        workbook.close()


def test_unallocated_addition_is_not_reported_when_its_opening_account_is_missing(tmp_path):
    opening_account = "987654"
    missing_account = "987655"
    addition = 25
    result = CIPReconciliationEngine(
        project_master={"123456": {"project_name": "Project"}},
        subledger_additions={},
        interfaced_cip={},
        gl_summary={
            missing_account: {
                "sources": {
                    "payables": {"source": "Payables", "net": addition},
                }
            }
        },
        opening_balances={"123456": {opening_account: 100}},
        period="Mar-26",
        journal_rows=[{
            "account": missing_account,
            "source": "Payables",
            "project": None,
            "net": addition,
            "row_number": 11,
        }],
    ).run()

    assert result.unallocated_additions == {missing_account: addition}
    assert result.summary["additions"][missing_account] == 0
    assert result.summary["closing"][missing_account] == 0
    assert any(
        item["type"] == "Missing Opening Balance Account"
        and item["account"] == missing_account
        for item in result.discrepancies
    )

    report_path = tmp_path / "report-with-missing-opening-account.xlsx"
    CIPReportGenerator(result).generate(report_path)
    workbook = openpyxl.load_workbook(report_path, data_only=False)
    try:
        worksheet = workbook["Sheet1"]
        assert worksheet["H4"].value is None
        assert worksheet["H5"].value == "=SUM(H3:H4)"
    finally:
        workbook.close()
