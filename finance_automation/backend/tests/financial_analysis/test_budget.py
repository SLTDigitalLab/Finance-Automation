"""Tests for Financial Analysis Budget Reader, Store, and API endpoints."""
from pathlib import Path
import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.jwt_handler import get_current_active_user
from app.database.connection import Base, get_db
from app.models.user_and_log import User
from app.routes import financial_analysis_routes as routes
from services.financial_analysis.budget_reader import (
    BudgetFormatError,
    read_fa_budget,
)
from services.financial_analysis import budget_store
from services.financial_analysis.periods import Period


def _create_sample_notes_budget_wb(path: Path, period_str: str = "Jun-26", opex_ytd: float = 23886.44):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "NA"

    # Row 1-4 preamble
    ws.append([])
    ws.append([None, "Notes to the Statement of Finacial Performance"])
    ws.append([])
    ws.append([None, "SLT Primary Ledger"])
    ws.append([None, f"LKR {period_str}"])
    ws.append([])
    ws.append([])
    ws.append([])

    # Row 9: Headers
    ws.append([None, None, "PTD-Actual", "PTD-Budget", "PTD-Actual", "PTD-Actual", "YTD-Actual", "YTD-Budget", "YTD-Actual"])
    ws.append([None, "", "Current Month", "Current Month", "Last year", "Previous Month", "", "", "Last Year"])

    # Sample rows
    ws.append([None, "International Settlement", 92, 70.77, 77.67, 99.84, 593.39, 420.11, 420.95])
    ws.append([None, "Internet Back-Bone", 101, 61.75, 57.84, 96.44, 643.38, 370.47, 358.84])
    ws.append([None, "Direct Staff cost", 465, 451.41, 416.67, 448.89, 2719.71, 2694.12, 2494.6])
    ws.append([None, "Total Operating Cost", 3900, 3986.31, 3800, 3950, 24000, opex_ytd, 22000])

    wb.save(path)
    return path


def _create_sample_gl_budget_wb(path: Path, year: int = 2026):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Budget 2026"

    # Row 1-2 preamble
    ws.append(["SLT Budget Model", f"Year {year}"])
    ws.append([])

    # Row 3: Header with account code and months
    ws.append(["GL Account", "Description", f"Jan {year}", f"Feb {year}", f"Mar {year}", f"Apr {year}", f"May {year}", f"Jun {year}", f"Jul {year}", f"Aug {year}", f"Sep {year}", f"Oct {year}", f"Nov {year}", f"Dec {year}"])

    # Sample rows (account, desc, 12 months)
    ws.append([411101, "Initiation - Gross", 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200])
    ws.append([511101, "Staff Cost", 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600])

    wb.save(path)
    return path


def test_notes_budget_reader(tmp_path):
    wb_path = _create_sample_notes_budget_wb(tmp_path / "YTD June 26.xlsx", "Jun-26", 23886.44)
    budget = read_fa_budget(wb_path)

    assert budget.period == Period(2026, 6)
    assert budget.year == 2026
    assert budget.months_loaded == [6]
    assert "International Settlement" in budget.lines
    assert budget.lines["International Settlement"]["ytd"] == 420.11
    assert budget.total_operating_cost["ytd"] == 23886.44


def test_gl_budget_reader(tmp_path):
    wb_path = _create_sample_gl_budget_wb(tmp_path / "budget.xlsx")
    budget = read_fa_budget(wb_path, ytd_cumulate=False)

    assert budget.year == 2026
    assert set(budget.months_loaded) == set(range(1, 13))
    assert 411101 in budget.accounts
    assert 511101 in budget.accounts
    assert budget.accounts[411101].ytd[3] == 300


def test_budget_reader_invalid_file(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Nothing", "Relevant"])
    wb_path = tmp_path / "invalid.xlsx"
    wb.save(wb_path)

    with pytest.raises(BudgetFormatError):
        read_fa_budget(wb_path)


def test_budget_store_multiple_periods(tmp_path):
    budget_dir = tmp_path / "budget_store"

    # Initial state
    assert budget_store.list_budgets(budget_dir) == []

    # Save March 26
    m1_path = _create_sample_notes_budget_wb(tmp_path / "YTD March 26.xlsx", "Mar-26", 11920.87)
    res1 = budget_store.save_budget_file(budget_dir, m1_path, "YTD March 26.xlsx", user_name="Admin")
    assert len(res1) == 1
    assert res1[0]["period"] == "Mar 2026"
    assert res1[0]["status"] == "loaded"

    # Save June 26
    m2_path = _create_sample_notes_budget_wb(tmp_path / "YTD June 26.xlsx", "Jun-26", 23886.44)
    res2 = budget_store.save_budget_file(budget_dir, m2_path, "YTD June 26.xlsx", user_name="Admin")
    assert len(res2) == 1
    assert res2[0]["period"] == "Jun 2026"

    # Check listing: contains both
    budgets = budget_store.list_budgets(budget_dir)
    assert len(budgets) == 2
    assert [b["label"] for b in budgets] == ["Jun 2026", "Mar 2026"]

    # Delete March 26
    assert budget_store.delete_budget(budget_dir, 2026, 3) is True
    budgets = budget_store.list_budgets(budget_dir)
    assert len(budgets) == 1
    assert budgets[0]["label"] == "Jun 2026"


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    admin = User(full_name="Test Admin", email="admin@example.com", role="Admin", status="Approved")
    db.add(admin)
    db.commit()

    monkeypatch.setattr(routes, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(routes, "BUDGET_DIR", tmp_path / "uploads" / "budget")
    monkeypatch.setattr(routes, "MAPPING_DIR", tmp_path / "uploads" / "mapping")
    monkeypatch.setattr(routes, "OUTPUT_DIR", tmp_path / "outputs")

    app = FastAPI()
    app.include_router(routes.financial_analysis_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_active_user] = lambda: admin
    yield TestClient(app)
    db.close()


def test_budget_api_multi_upload(client, tmp_path):
    # 1. Initial status -> no budgets
    resp = client.get("/api/financial-analysis/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["budgets"] == []
    assert data["budget_available"] is False

    # 2. Upload multiple budget files together
    p1 = _create_sample_notes_budget_wb(tmp_path / "YTD March 26.xlsx", "Mar-26", 11920.87)
    p2 = _create_sample_notes_budget_wb(tmp_path / "YTD June 26.xlsx", "Jun-26", 23886.44)

    with open(p1, "rb") as f1, open(p2, "rb") as f2:
        resp = client.post(
            "/api/financial-analysis/budget",
            files=[
                ("files", ("YTD March 26.xlsx", f1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
                ("files", ("YTD June 26.xlsx", f2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
            ],
        )
    assert resp.status_code == 200
    upload_res = resp.json()
    assert len(upload_res["results"]) == 2
    assert {r["period"] for r in upload_res["results"]} == {"Mar 2026", "Jun 2026"}

    # 3. Status now lists both budgets
    resp = client.get("/api/financial-analysis/status")
    data = resp.json()
    assert data["budget_available"] is True
    assert len(data["budgets"]) == 2

    # 4. Delete one budget period
    resp = client.delete("/api/financial-analysis/budget/2026/3")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # 5. Status after deleting one period
    resp = client.get("/api/financial-analysis/status")
    data = resp.json()
    assert len(data["budgets"]) == 1
    assert data["budgets"][0]["label"] == "Jun 2026"
