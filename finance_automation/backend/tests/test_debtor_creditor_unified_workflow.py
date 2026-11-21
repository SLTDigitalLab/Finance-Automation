import random
import string
from io import BytesIO
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import openpyxl
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.routes import debtor_age_analysis_routes as routes
from app.auth.jwt_handler import get_current_active_user
from app.database.connection import get_db
from app.models.user_and_log import User
from main import app


NETTING_HEADERS = [
    "Source Name", "Customer Supplier Name", "Supplier Site", "Supplier Category",
    "Trx Number", "Transaction Date", "Gl Date", "Due Date", "Event Class",
    "Payment Terms", "Invoice Type", "Transaction Type Name", "Trx Currency Code",
    "Invoice Type Lookup Code", "Exchange Rate", "Period Name",
    "Entered Due Remaining", "Ledger Due Remaining",
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _netting_workbook_bytes(bulk_rows: int = 0) -> bytes:
    workbook = openpyxl.Workbook()
    receivables_sheet = workbook.active
    receivables_sheet.title = "Receivables Detail"
    receivables_sheet.append(["Receivables"])
    receivables_sheet.append(["Source Name"])
    receivable = [None] * len(NETTING_HEADERS)
    receivable[0] = "Receivables"
    receivable[1] = "Debtor Supplier"
    receivable[4] = "INV-001"
    receivable[5] = datetime(2026, 10, 1)
    receivable[7] = datetime(2026, 10, 31)
    receivable[12] = "USD"
    receivable[16] = 100
    receivable[17] = 100
    receivables_sheet.append(receivable)

    payables_sheet = workbook.create_sheet("Payables Detail")
    payables_sheet.append(["Payables"])
    payables_sheet.append(NETTING_HEADERS)
    payable = [None] * len(NETTING_HEADERS)
    payable[0] = "Paybles"
    payable[1] = "Creditor Supplier"
    payable[4] = "PINV-001"
    payable[5] = datetime(2026, 10, 1)
    payable[7] = datetime(2026, 10, 31)
    payable[12] = "USD"
    payable[16] = -50
    payables_sheet.append(payable)

    if bulk_rows:
        bulk = workbook.create_sheet("Supplemental Data")
        for row_number in range(bulk_rows):
            generator = random.Random(row_number)
            bulk.append([
                "".join(generator.choices(string.ascii_letters + string.digits, k=32767))
            ])

    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _debtor_aging_workbook_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    workbook.active.title = "Summary"
    workbook.create_sheet("122105 (Voice)")
    workbook.create_sheet("122107  (Non Voice)")
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _erp_debtor_workbook_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "ERP Data"
    worksheet["B2"] = datetime(2026, 10, 31)
    headers = [
        "Customer Name", "Customer Number", "Transaction Number", "Trx Type Name",
        "TRX Date", "Due Date", "Currency Code", "Exchange Rate", "Natural Account",
        "Entered Amount", "Outstanding Amount", "Current Bucket", "Age 00 - 30",
        "Age 31 - 60", "Age 61 - 90", "Age 91 - 180", "Age 181 - 365",
        "Age 366 - 730", "Age 731 - 1095", "Age 1096 Above",
    ]
    for column, value in enumerate(headers, start=1):
        worksheet.cell(10, column, value)
    values = ["Supplier", 1, "INV-001", "Invoice", None, None, "USD", None, None,
              100, 100, 100, 0, 0, 0, 0, 0, 0, 0, 0]
    for column, value in enumerate(values, start=1):
        worksheet.cell(11, column, value)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


@pytest.mark.anyio
async def test_shared_netting_upload_validates_xlsx_and_stores_one_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir()
    monkeypatch.setattr(routes, "_user_upload_dir", lambda _user_id: upload_dir)
    monkeypatch.setattr(routes, "_user_output_dir", lambda _user_id: output_dir)
    monkeypatch.setattr(routes, "log_audit", lambda **_kwargs: None)
    upload = UploadFile(
        filename="renamed-shared-workbook.xlsx",
        file=BytesIO(_netting_workbook_bytes()),
    )

    result = await routes.upload_shared_netting_report(
        request=object(),
        file=upload,
        db=None,
        current_user=SimpleNamespace(id=8, full_name="Test User"),
    )

    assert result["receivables_rows"] == 1
    assert result["payables_rows"] == 1
    assert result["sheets"] == ["Receivables Detail", "Payables Detail"]
    stored = openpyxl.load_workbook(upload_dir / "netting_report.xlsx", data_only=True)
    assert stored.sheetnames == ["Receivables Detail", "Payables Detail"]
    stored.close()
    assert not (upload_dir / "creditor_netting.xlsx").exists()


@pytest.mark.anyio
async def test_other_two_required_workbooks_still_upload_and_validate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(routes, "_user_upload_dir", lambda _user_id: upload_dir)
    monkeypatch.setattr(routes, "_user_output_dir", lambda _user_id: tmp_path / "outputs")
    monkeypatch.setattr(routes, "log_audit", lambda **_kwargs: None)
    user = SimpleNamespace(id=12, full_name="Test User")

    debtor_result = await routes.upload_debtor_aging(
        request=object(),
        file=UploadFile(
            filename="debtors.xlsx",
            file=BytesIO(_debtor_aging_workbook_bytes()),
        ),
        db=None,
        current_user=user,
    )
    erp_result = await routes.upload_erp_debtor_aging(
        request=object(),
        file=UploadFile(
            filename="erp.xlsx",
            file=BytesIO(_erp_debtor_workbook_bytes()),
        ),
        db=None,
        current_user=user,
    )

    assert debtor_result["sheets"] == ["Summary", "122105 (Voice)", "122107  (Non Voice)"]
    assert erp_result["report_date"] == "2026-10-31"
    assert (upload_dir / "debtor_aging.xlsx").exists()
    assert (upload_dir / "erp_debtor_aging.xlsx").exists()


@pytest.mark.anyio
async def test_legacy_xls_shared_upload_is_normalized_and_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source_path = (
        Path(__file__).resolve().parents[2]
        / "Input"
        / "CIP_Reconciliation_report"
        / "SLT_Interfaced_CIP_RWIP_Amount_jUL26_111401 to 111406.xls"
    )
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir()
    monkeypatch.setattr(routes, "_user_upload_dir", lambda _user_id: upload_dir)
    monkeypatch.setattr(routes, "_user_output_dir", lambda _user_id: output_dir)
    monkeypatch.setattr(routes, "log_audit", lambda **_kwargs: None)
    validated_paths = []

    def validate_debtor(path: Path):
        validated_paths.append(path)
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        names = workbook.sheetnames
        workbook.close()
        return {"sheets": names, "receivables_rows": 1, "payables_rows": 0}

    def validate_creditor(path: Path):
        validated_paths.append(path)
        return {"payables_rows": 1, "currencies": ["USD"]}

    monkeypatch.setattr(routes, "validate_netting_report_file", validate_debtor)
    monkeypatch.setattr(routes, "validate_creditor_netting_file", validate_creditor)
    upload = UploadFile(filename=source_path.name, file=BytesIO(source_path.read_bytes()))

    result = await routes.upload_shared_netting_report(
        request=object(),
        file=upload,
        db=None,
        current_user=SimpleNamespace(id=9, full_name="Test User"),
    )

    assert len(validated_paths) == 2
    assert validated_paths[0] == validated_paths[1]
    assert validated_paths[0].suffix == ".xlsx"
    stored = openpyxl.load_workbook(
        upload_dir / "netting_report.xlsx", read_only=True
    )
    assert result["sheets"] == stored.sheetnames
    stored.close()
    assert (upload_dir / "netting_report.xlsx").exists()


@pytest.mark.anyio
async def test_invalid_netting_file_is_rejected_without_replacing_current_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    existing = upload_dir / "netting_report.xlsx"
    existing.write_bytes(b"previous valid input")
    monkeypatch.setattr(routes, "_user_upload_dir", lambda _user_id: upload_dir)
    monkeypatch.setattr(routes, "_user_output_dir", lambda _user_id: tmp_path / "outputs")
    monkeypatch.setattr(routes, "log_audit", lambda **_kwargs: None)

    with pytest.raises(HTTPException) as error:
        await routes.upload_shared_netting_report(
            request=object(),
            file=UploadFile(filename="bad.xlsx", file=BytesIO(b"not an Excel file")),
            db=None,
            current_user=SimpleNamespace(id=10, full_name="Test User"),
        )

    assert error.value.status_code == 422
    assert "Cannot open AR/AP netting workbook" in error.value.detail
    assert existing.read_bytes() == b"previous valid input"
    assert not list(upload_dir.glob(".upload-*.xlsx"))


@pytest.mark.anyio
async def test_large_valid_netting_workbook_uploads_within_configured_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(routes, "_user_upload_dir", lambda _user_id: upload_dir)
    monkeypatch.setattr(routes, "_user_output_dir", lambda _user_id: tmp_path / "outputs")
    monkeypatch.setattr(routes, "log_audit", lambda **_kwargs: None)
    content = _netting_workbook_bytes(bulk_rows=50)
    assert 1_000_000 < len(content) < routes.settings.MAX_FILE_SIZE_MB * 1024 * 1024

    result = await routes.upload_shared_netting_report(
        request=object(),
        file=UploadFile(filename="large-netting.xlsx", file=BytesIO(content)),
        db=None,
        current_user=SimpleNamespace(id=11, full_name="Test User"),
    )

    assert result["receivables_rows"] == 1
    assert (upload_dir / "netting_report.xlsx").exists()


def test_shared_netting_upload_paths_are_post_routes():
    route_methods = {
        route.path: route.methods for route in routes.debtor_age_router.routes
    }

    assert "POST" in route_methods["/api/debtor-age/upload/netting-report"]
    assert "POST" in route_methods["/api/debtor-age/upload/shared-netting-report"]


def test_existing_netting_post_route_accepts_multipart_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(routes, "_user_upload_dir", lambda _user_id: upload_dir)
    monkeypatch.setattr(routes, "_user_output_dir", lambda _user_id: tmp_path / "outputs")
    monkeypatch.setattr(routes, "log_audit", lambda **_kwargs: None)
    test_user = User(id=21, full_name="Test User", role="Admin")
    monkeypatch.setitem(app.dependency_overrides, get_current_active_user, lambda: test_user)
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: None)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/debtor-age/upload/netting-report",
            files={
                "file": (
                    "renamed-netting.xlsx",
                    _netting_workbook_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    assert response.json()["receivables_rows"] == 1
    assert response.json()["payables_rows"] == 1
    assert (upload_dir / "netting_report.xlsx").exists()


def test_http_generate_all_upload_download_regenerate_and_legacy_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir()
    monkeypatch.setattr(routes, "_user_upload_dir", lambda _user_id: upload_dir)
    monkeypatch.setattr(routes, "_user_output_dir", lambda _user_id: output_dir)
    monkeypatch.setattr(routes, "log_audit", lambda **_kwargs: None)
    user = User(id=22, full_name="Test User", role="Admin")
    monkeypatch.setitem(app.dependency_overrides, get_current_active_user, lambda: user)
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: None)

    debtor_runs = []
    creditor_runs = []
    real_debtor_generator = routes.generate_debtor_age_analysis
    real_creditor_generator = routes.generate_creditor_aging_report

    def count_debtor_runs(*args):
        debtor_runs.append(args[1])
        return real_debtor_generator(*args)

    def count_creditor_runs(*args):
        creditor_runs.append(args[0])
        return real_creditor_generator(*args)

    monkeypatch.setattr(routes, "generate_debtor_age_analysis", count_debtor_runs)
    monkeypatch.setattr(routes, "generate_creditor_aging_report", count_creditor_runs)

    client = TestClient(app)
    try:
        missing = client.post("/api/debtor-age/generate/all")
        assert missing.status_code == 400
        assert "Debtor Aging workbook" in missing.json()["detail"]
        assert "shared SLT AR/AP Netting Report workbook" in missing.json()["detail"]

        debtor_upload = client.post(
            "/api/debtor-age/upload/debtor-aging",
            files={"file": ("debtors.xlsx", _debtor_aging_workbook_bytes())},
        )
        shared_upload = client.post(
            "/api/debtor-age/upload/netting-report",
            files={"file": ("shared.xlsx", _netting_workbook_bytes())},
        )
        erp_upload = client.post(
            "/api/debtor-age/upload/erp-debtor-aging",
            files={"file": ("erp.xlsx", _erp_debtor_workbook_bytes())},
        )
        assert [debtor_upload.status_code, shared_upload.status_code, erp_upload.status_code] == [
            200, 200, 200,
        ]

        legacy_debtor = client.post("/api/debtor-age/generate")
        assert legacy_debtor.status_code == 200
        legacy_netting = client.post(
            "/api/debtor-age/upload/creditor-netting",
            files={"file": ("shared-again.xlsx", _netting_workbook_bytes())},
        )
        assert legacy_netting.status_code == 200
        legacy_creditor = client.post("/api/debtor-age/generate/creditor-aging")
        assert legacy_creditor.status_code == 200

        debtor_runs.clear()
        creditor_runs.clear()
        generated = client.post("/api/debtor-age/generate/all")
        assert generated.status_code == 200, generated.text
        assert len(debtor_runs) == 1
        assert len(creditor_runs) == 1
        assert debtor_runs[0] == upload_dir / "netting_report.xlsx"
        assert creditor_runs[0] == upload_dir / "netting_report.xlsx"
        assert generated.json()["debtor_process"]["status"] == "success"
        assert generated.json()["creditor_process"]["report_count"] == 3
        assert generated.json()["reconciliation"]["net_total"] == "50"

        downloaded = client.get("/api/debtor-age/download/all")
        assert downloaded.status_code == 200
        with ZipFile(BytesIO(downloaded.content)) as archive:
            assert archive.namelist() == [
                routes.OUTPUT_FILENAME,
                routes.SUPPLIER_NET_OUTPUT_FILENAME,
            ]
            creditor_bytes = archive.read(routes.SUPPLIER_NET_OUTPUT_FILENAME)
        creditor_workbook = openpyxl.load_workbook(BytesIO(creditor_bytes), read_only=True)
        assert creditor_workbook.sheetnames == [
            "Creditor Aging Details",
            "Supplier-wise Net Aging",
            "Reconciliation",
        ]
        creditor_workbook.close()

        regenerated = client.post("/api/debtor-age/generate/all")
        assert regenerated.status_code == 200, regenerated.text
        assert len(debtor_runs) == 2
        assert len(creditor_runs) == 2

        removed = client.delete("/api/debtor-age/upload/erp-debtor-aging")
        assert removed.status_code == 200
        missing_erp = client.post("/api/debtor-age/generate/all")
        assert missing_erp.status_code == 400
        assert "SLT Debtor Age Analysis ERP Report" in missing_erp.json()["detail"]
        assert client.get("/api/debtor-age/download/all").status_code == 404
    finally:
        client.close()


@pytest.mark.anyio
async def test_generate_all_reports_reuses_shared_netting_and_downloads_latest_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir()
    for filename in ("debtor_aging.xlsx", "netting_report.xlsx", "erp_debtor_aging.xlsx"):
        (upload_dir / filename).write_bytes(b"input")

    monkeypatch.setattr(routes, "_user_upload_dir", lambda _user_id: upload_dir)
    monkeypatch.setattr(routes, "_user_output_dir", lambda _user_id: output_dir)
    netting_paths = []
    generation_runs = []

    def generate_debtor(_debtor_path: Path, netting_path: Path, output_path: Path):
        netting_paths.append(netting_path)
        generation_runs.append(None)
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "SLT_Debtor_Age_Analysis_Report_"
        worksheet.cell(2, 2, datetime(2026, 9, 30) if len(generation_runs) == 1 else datetime(2026, 10, 31))
        workbook.save(output_path)
        workbook.close()
        return output_path

    def generate_creditor(netting_path: Path, _erp_path: Path, output_path: Path):
        netting_paths.append(netting_path)
        workbook = openpyxl.Workbook()
        workbook.remove(workbook.active)
        workbook.create_sheet("Creditor Aging Details")
        workbook.create_sheet("Supplier-wise Net Aging")
        reconciliation = workbook.create_sheet("Reconciliation")
        reconciliation.cell(19, 5, "Match Status")
        reconciliation.cell(20, 5, "Matched - review mapping")
        reconciliation.cell(21, 5, "Debtor only")
        workbook.save(output_path)
        workbook.close()
        return {
            "report_date": date(2026, 10, 31),
            "currency": "USD",
            "debtor_total": Decimal("250"),
            "creditor_total": Decimal("40"),
            "net_total": Decimal("210"),
        }

    async def run_in_threadpool(function, *args):
        return function(*args)

    monkeypatch.setattr(routes, "generate_debtor_age_analysis", generate_debtor)
    monkeypatch.setattr(routes, "generate_creditor_aging_report", generate_creditor)
    monkeypatch.setattr(routes, "run_in_threadpool", run_in_threadpool)
    monkeypatch.setattr(routes, "log_audit", lambda **_kwargs: None)
    user = SimpleNamespace(id=7, full_name="Test User")

    result = await routes.generate_all_reports(request=object(), db=None, current_user=user)

    assert netting_paths == [upload_dir / "netting_report.xlsx"] * 2
    assert result["debtor_process"]["report_date"] == "2026-09-30"
    assert result["creditor_process"]["report_count"] == 3
    assert result["reconciliation"]["net_total"] == "210"
    assert result["warnings"] == [
        "1 supplier match(es) need mapping review.",
        "Unmatched suppliers: 1 debtor-only and 0 creditor-only; see the Reconciliation report.",
    ]
    with ZipFile(output_dir / routes.ALL_REPORTS_FILENAME) as archive:
        assert archive.namelist() == [
            routes.OUTPUT_FILENAME,
            routes.SUPPLIER_NET_OUTPUT_FILENAME,
        ]

    status = await routes.get_debtor_age_status(current_user=user)
    assert status["all_reports_ready"] is True
    assert status["generation_summary"]["creditor_process"]["report_date"] == "2026-10-31"
    download = await routes.download_all_reports(current_user=user)
    assert download.path == str(output_dir / routes.ALL_REPORTS_FILENAME)

    regenerated = await routes.generate_all_reports(
        request=object(),
        db=None,
        current_user=user,
    )
    assert regenerated["debtor_process"]["report_date"] == "2026-10-31"
    assert len(generation_runs) == 2

    routes._invalidate_combined_reports(output_dir)
    with pytest.raises(HTTPException) as error:
        await routes.download_all_reports(current_user=user)
    assert error.value.status_code == 404
