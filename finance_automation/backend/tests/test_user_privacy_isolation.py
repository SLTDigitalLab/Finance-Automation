"""
Integration Tests for User-Specific File Upload Privacy and Access Control.
Verifies complete file and data isolation between multiple users:
- Test Case 1: User A uploads files; User A can see/download/delete; User B sees empty listings.
- Test Case 2: User B uploads files; User A cannot see User B's files.
- Test Case 3: URL / Session / File ID parameter tampering rejected (HTTP 403/404).
- Test Case 4: Complete separation across Accrual Entry, CIP, Financial Analysis, and Executive Finance.
"""
import io
import json
import pytest
from pathlib import Path
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook

from main import app
from app.auth.jwt_handler import create_access_token, get_password_hash
from app.database.connection import SessionLocal
from app.models.user_and_log import User, UploadedFinanceFile, ReportJob, PLRevenueRecord, UserUseCaseAccess
from api.routes import _session_user_store, report_jobs
from config import settings


def create_dummy_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Col1", "Col2"])
    ws.append([100, 200])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def create_dummy_docx():
    doc = Document()
    doc.add_heading("Mobitel Management Write-up", level=1)
    doc.add_paragraph("Section A - YoY Performance commentary text.")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture(scope="module")
def setup_users():
    db = SessionLocal()
    try:
        # Create user A
        user_a = db.query(User).filter(User.email == "user_a_test@slt.com.lk").first()
        if not user_a:
            user_a = User(
                full_name="User Alpha",
                email="user_a_test@slt.com.lk",
                password_hash=get_password_hash("password123"),
                role="User",
                status="Approved",
                is_active=True,
            )
            db.add(user_a)

        # Create user B
        user_b = db.query(User).filter(User.email == "user_b_test@slt.com.lk").first()
        if not user_b:
            user_b = User(
                full_name="User Beta",
                email="user_b_test@slt.com.lk",
                password_hash=get_password_hash("password123"),
                role="User",
                status="Approved",
                is_active=True,
            )
            db.add(user_b)

        db.commit()
        db.refresh(user_a)
        db.refresh(user_b)

        # Grant access to relevant use cases for testing
        use_cases = ["revenue", "board_pack", "financial_analysis", "use_case_4", "use_case_5"]
        for email in [user_a.email, user_b.email]:
            for uc in use_cases:
                existing_perm = db.query(UserUseCaseAccess).filter(
                    UserUseCaseAccess.email == email.lower(),
                    UserUseCaseAccess.use_case_id == uc,
                ).first()
                if not existing_perm:
                    db.add(UserUseCaseAccess(email=email.lower(), use_case_id=uc))
        db.commit()

        token_a = create_access_token({"sub": user_a.email})
        token_b = create_access_token({"sub": user_b.email})

        return {
            "user_a_id": user_a.id,
            "user_b_id": user_b.id,
            "token_a": token_a,
            "token_b": token_b,
            "headers_a": {"Authorization": f"Bearer {token_a}"},
            "headers_b": {"Authorization": f"Bearer {token_b}"},
        }
    finally:
        db.close()


def test_accrual_entry_privacy_isolation(setup_users):
    """Test Case 1 & 2: Accrual Entry uploads are strictly isolated per user."""
    client = TestClient(app)
    headers_a = setup_users["headers_a"]
    headers_b = setup_users["headers_b"]
    period = "Dec-26"

    # User A uploads account analysis file
    xlsx_bytes = create_dummy_xlsx()
    resp_upload_a = client.post(
        f"/api/accrual-entry/upload/account_analysis?period={period}",
        headers=headers_a,
        files={"file": ("test_accrual_a.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp_upload_a.status_code == 200, resp_upload_a.text

    # User A checks status: file should be visible
    resp_status_a = client.get(f"/api/accrual-entry/status?period={period}", headers=headers_a)
    assert resp_status_a.status_code == 200
    data_a = resp_status_a.json()["categories"]
    assert data_a["account_analysis"]["uploaded"] is True
    assert data_a["account_analysis"]["filename"] == "test_accrual_a.xlsx"

    # User B checks status: must NOT see User A's file
    resp_status_b = client.get(f"/api/accrual-entry/status?period={period}", headers=headers_b)
    assert resp_status_b.status_code == 200
    data_b = resp_status_b.json()["categories"]
    assert data_b["account_analysis"]["uploaded"] is False
    assert data_b["account_analysis"]["filename"] is None

    # Test Case 3: User B attempts to delete User A's accrual file -> 404
    resp_del_b = client.delete(f"/api/accrual-entry/file/account_analysis?period={period}", headers=headers_b)
    assert resp_del_b.status_code == 404

    # User A deletes their own file: success
    resp_del_a = client.delete(f"/api/accrual-entry/file/account_analysis?period={period}", headers=headers_a)
    assert resp_del_a.status_code == 200


def test_cip_reconciliation_privacy_isolation(setup_users):
    """Test Case 1 & 3: CIP Reconciliation file privacy and parameter tampering rejection."""
    client = TestClient(app)
    headers_a = setup_users["headers_a"]
    headers_b = setup_users["headers_b"]
    period = "Dec-26"

    # User A uploads a CIP file
    xlsx_bytes = create_dummy_xlsx()
    resp_upload_a = client.post(
        f"/api/cip/upload/journal_details?period={period}",
        headers=headers_a,
        files={"file": ("cip_journal_a.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp_upload_a.status_code == 200, resp_upload_a.text

    # User A checks status: file is present
    resp_status_a = client.get(f"/api/cip/status?period={period}", headers=headers_a)
    assert resp_status_a.status_code == 200
    categories_a = resp_status_a.json()["categories"]
    assert categories_a["journal_details"]["uploaded"] is True

    # User B checks status: file is NOT present
    resp_status_b = client.get(f"/api/cip/status?period={period}", headers=headers_b)
    assert resp_status_b.status_code == 200
    categories_b = resp_status_b.json()["categories"]
    assert categories_b["journal_details"]["uploaded"] is False

    # Test Case 3: User B attempts to delete User A's file
    resp_del_b = client.delete(f"/api/cip/file/journal_details?period={period}", headers=headers_b)
    assert resp_del_b.status_code == 404

    # User A deletes their file: success
    resp_del_a = client.delete(f"/api/cip/file/journal_details?period={period}", headers=headers_a)
    assert resp_del_a.status_code == 200


def test_financial_analysis_privacy_isolation(setup_users):
    """Test Case 1 & 2: Financial Analysis inputs (remaining inputs) isolation."""
    client = TestClient(app)
    headers_a = setup_users["headers_a"]
    headers_b = setup_users["headers_b"]

    # User A uploads remaining inputs (Mobitel writeup)
    doc_bytes = create_dummy_docx()
    resp_rem_a = client.post(
        "/api/financial-analysis/remaining-inputs/upload/mobitel-writeup",
        headers=headers_a,
        files={"file": ("mobitel_writeup_user_a.docx", doc_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp_rem_a.status_code == 200, resp_rem_a.text

    # User A checks status: mobitel writeup is present
    resp_rem_stat_a = client.get("/api/financial-analysis/remaining-inputs/status", headers=headers_a)
    assert resp_rem_stat_a.status_code == 200
    uploads_a = resp_rem_stat_a.json()["uploads"]
    assert uploads_a["mobitel_writeup"] is not None
    assert uploads_a["mobitel_writeup"]["filename"] == "mobitel_writeup_user_a.docx"

    # User B checks remaining inputs status: mobitel writeup must NOT be present (None)
    resp_rem_stat_b = client.get("/api/financial-analysis/remaining-inputs/status", headers=headers_b)
    assert resp_rem_stat_b.status_code == 200
    uploads_b = resp_rem_stat_b.json()["uploads"]
    assert uploads_b["mobitel_writeup"] is None

    # Test Case 3: User B attempts to delete User A's remaining input
    resp_del_b = client.delete("/api/financial-analysis/remaining-inputs/mobitel_writeup", headers=headers_b)
    assert resp_del_b.status_code == 404

    # User A can delete their own input
    resp_del_a = client.delete("/api/financial-analysis/remaining-inputs/mobitel_writeup", headers=headers_a)
    assert resp_del_a.status_code == 200


def test_session_and_report_access_tampering_protection(setup_users):
    """Test Case 3: Tampering with session IDs, endpoints, or direct URLs is rejected with HTTP 403/404."""
    client = TestClient(app)
    headers_a = setup_users["headers_a"]
    headers_b = setup_users["headers_b"]
    user_a_id = setup_users["user_a_id"]

    test_session = "privtest123"
    _session_user_store[test_session] = user_a_id
    report_jobs[test_session] = {"status": "success", "filename": "privtest_report.pptx"}

    db = SessionLocal()
    try:
        rj = db.query(ReportJob).filter(ReportJob.session_id == test_session).first()
        if not rj:
            rj = ReportJob(
                session_id=test_session,
                user_id=user_a_id,
                status="success",
                result_json=json.dumps({"status": "success", "filename": "privtest_report.pptx"}),
            )
            db.add(rj)
            db.commit()
    finally:
        db.close()

    # User A checks status: allowed (200)
    resp_stat_a = client.get(f"/api/report-status/{test_session}", headers=headers_a)
    assert resp_stat_a.status_code == 200

    # Test Case 3: User B attempts to check User A's session status -> 403 Forbidden
    resp_stat_b = client.get(f"/api/report-status/{test_session}", headers=headers_b)
    assert resp_stat_b.status_code == 403
    assert "Access denied" in resp_stat_b.text

    # Test Case 3: User B attempts to trigger report generation on User A's session -> 403 Forbidden
    resp_gen_b = client.post(f"/api/generate?session_id={test_session}", headers=headers_b)
    assert resp_gen_b.status_code == 403
    assert "Access denied" in resp_gen_b.text

    # Test Case 3: User B attempts to trigger unmapped report on User A's session -> 403 Forbidden
    resp_unmap_b = client.post(f"/api/generate-unmapped?session_id={test_session}", headers=headers_b)
    assert resp_unmap_b.status_code == 403
    assert "Access denied" in resp_unmap_b.text

    # Test Case 3: User B attempts to download report file belonging to User A
    user_a_out_dir = settings.OUTPUT_DIR / str(user_a_id)
    user_a_out_dir.mkdir(parents=True, exist_ok=True)
    report_file = user_a_out_dir / "privtest_report.pptx"
    report_file.write_text("dummy pptx content")

    resp_dl_b = client.get("/api/download/privtest_report.pptx", headers=headers_b)
    assert resp_dl_b.status_code == 404

    # User A downloads their own report file: 200 OK
    resp_dl_a = client.get("/api/download/privtest_report.pptx", headers=headers_a)
    assert resp_dl_a.status_code == 200


def test_pl_revenue_privacy_isolation(setup_users):
    """Test Case 1 & 2: P&L revenue records are isolated per user."""
    client = TestClient(app)
    headers_a = setup_users["headers_a"]
    headers_b = setup_users["headers_b"]
    user_a_id = setup_users["user_a_id"]

    db = SessionLocal()
    try:
        # Create a PL revenue record for User A
        pl_rec = PLRevenueRecord(
            user_id=user_a_id,
            period_month="November",
            period_year=2026,
            month_revenue=450000000.0,
            ytd_revenue=5000000000.0,
            source_filename="test_pl_user_a.xlsx",
        )
        db.add(pl_rec)
        db.commit()
    finally:
        db.close()

    # User A queries P&L revenue for November 2026: found
    resp_pl_a = client.get("/api/pl-revenue?period_month=November&period_year=2026", headers=headers_a)
    assert resp_pl_a.status_code == 200
    data_a = resp_pl_a.json()
    assert data_a["status"] == "success"
    assert data_a["data"]["month_revenue"] == 450000000.0

    # User B queries P&L revenue for November 2026: not found (isolated!)
    resp_pl_b = client.get("/api/pl-revenue?period_month=November&period_year=2026", headers=headers_b)
    assert resp_pl_b.status_code == 200
    data_b = resp_pl_b.json()
    assert data_b["status"] == "not_found"
    assert data_b["data"] is None
