"""Financial Analysis Report API Routes (quarterly P&L analysis from trial balances)"""
import logging
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.user_and_log import User
from app.routes.use_case_routes import require_use_case
from app.services.audit_logger import log_audit
from config import settings
from services.financial_analysis import mapping_store, tb_store
from services.financial_analysis.budget_reader import BudgetFormatError
from services.financial_analysis import budget_store
from services.financial_analysis.mapping_reader import MappingFormatError
from services.financial_analysis.periods import Period, Quarter
from services.financial_analysis.pl_engine import (
    MissingPeriodsError, build_analysis, monthly_trend, required_periods,
)
from services.financial_analysis.report_generator import ReportInputs, ReportTemplateError, generate_report
from services.financial_analysis.tb_reader import TBFormatError, read_trial_balance

logger = logging.getLogger(__name__)
financial_analysis_router = APIRouter(prefix="/api/financial-analysis", tags=["financial-analysis"])

USE_CASE = "financial_analysis"
MODULE = "Financial Analysis Report"
UPLOAD_DIR = settings.UPLOAD_DIR / "financial_analysis"
MAPPING_DIR = UPLOAD_DIR / "mapping"
BUDGET_DIR  = UPLOAD_DIR / "budget"
OUTPUT_DIR = settings.OUTPUT_DIR / "financial_analysis"
FILENAME_PATTERN = re.compile(r"^Financial_Analysis_Q[1-4]_\d{4}_[0-9a-f]{8}\.docx$")
ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}
SUMMARY_LINES = ["revenue", "operating_costs", "ebitda", "operating_profit", "profit_before_tax", "profit_after_tax"]


class GenerateRequest(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    quarter: int = Field(..., ge=1, le=4)


async def _save_upload(file: UploadFile) -> Path:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"{file.filename}: upload an Excel file (.xlsx or .xlsm).")
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"{file.filename}: file exceeds {settings.MAX_FILE_SIZE_MB} MB.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(content)
    return path


def _period_json(record) -> dict:
    period = Period(record.period_year, record.period_month)
    return {
        "year": period.year,
        "month": period.month,
        "label": period.label,
        "filename": record.source_filename,
        "accounts": record.account_count,
        "rows": record.row_count,
        "net_ytd": round(record.net_ytd, 2),
        "uploaded_at": record.uploaded_at.isoformat() if record.uploaded_at else None,
    }


def _quarter_options(loaded: set) -> List[dict]:
    """Every quarter whose quarter-end TB is loaded, with the TBs it still needs."""
    quarters = sorted({Quarter.ending(p) for p in loaded if Quarter.ending(p)}, reverse=True)
    return [
        {
            "year": q.year,
            "quarter": q.quarter,
            "label": q.label,
            "missing": [p.label for p in required_periods(q) if p not in loaded],
        }
        for q in quarters
    ]


@financial_analysis_router.get("/status")
def get_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    records = tb_store.list_periods(db)
    loaded = {Period(r.period_year, r.period_month) for r in records}
    budgets = budget_store.list_budgets(BUDGET_DIR)
    return {
        "periods": [_period_json(r) for r in records],
        "mapping": mapping_store.mapping_info(MAPPING_DIR),
        "budgets": budgets,
        "budget": budgets[0] if budgets else None,
        "quarters": _quarter_options(loaded),
        "budget_available": len(budgets) > 0,
    }


@financial_analysis_router.post("/trial-balances")
async def upload_trial_balances(
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Reads one or more detail TB exports. Each is stored by its period; reloading a month replaces it."""
    results = []
    for file in files:
        path = await _save_upload(file)
        try:
            tb = await run_in_threadpool(read_trial_balance, path)
            existed = tb_store.load_ytd(db, tb.period) is not None
            tb_store.save_trial_balance(db, tb, file.filename, current_user.id)
            results.append({
                "filename": file.filename,
                "status": "replaced" if existed else "loaded",
                "period": tb.period.label,
                "accounts": len(tb.accounts),
                "rows": tb.row_count,
                "warnings": tb.warnings,
            })
            log_audit(
                db=db, action="Upload Trial Balance", module=MODULE,
                description=f"{'Replaced' if existed else 'Loaded'} trial balance {tb.period.label} from {file.filename}",
                user_id=current_user.id, user_name=current_user.full_name, request=request,
            )
        except TBFormatError as exc:
            results.append({"filename": file.filename, "status": "error", "error": str(exc)})
        except Exception as exc:
            logger.exception(f"Trial balance upload failed for {file.filename}: {exc}")
            results.append({"filename": file.filename, "status": "error", "error": f"Could not read the file: {exc}"})
        finally:
            path.unlink(missing_ok=True)
    return {"results": results}


@financial_analysis_router.delete("/trial-balances/{year}/{month}")
def delete_trial_balance(
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    try:
        period = Period(year, month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not tb_store.delete_trial_balance(db, period):
        raise HTTPException(status_code=404, detail=f"No trial balance loaded for {period.label}.")
    log_audit(
        db=db, action="Delete Trial Balance", module=MODULE,
        description=f"Deleted trial balance {period.label}",
        user_id=current_user.id, user_name=current_user.full_name, request=request,
    )
    return {"status": "deleted", "period": period.label}


@financial_analysis_router.post("/budget")
async def upload_budgets(
    request: Request,
    files: List[UploadFile] = File(...),
    ytd_cumulate: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Reads one or more budget workbooks (monthly YTD budget files or multi-month workbooks). Each is stored by period."""
    results = []
    for file in files:
        path = await _save_upload(file)
        try:
            loaded_periods = await run_in_threadpool(
                budget_store.save_budget_file, BUDGET_DIR, path, file.filename,
                current_user.full_name, ytd_cumulate,
            )
            for item in loaded_periods:
                results.append(item)
                log_audit(
                    db=db, action="Upload FA Budget", module=MODULE,
                    description=f"{'Replaced' if item.get('status') == 'replaced' else 'Loaded'} FA budget {item.get('period')} from {file.filename}",
                    user_id=current_user.id, user_name=current_user.full_name, request=request,
                )
        except BudgetFormatError as exc:
            results.append({"filename": file.filename, "status": "error", "error": str(exc)})
        except Exception as exc:
            logger.exception(f"Budget upload failed for {file.filename}: {exc}")
            results.append({"filename": file.filename, "status": "error", "error": f"Could not read the file: {exc}"})
        finally:
            path.unlink(missing_ok=True)
    return {"results": results, "budgets": budget_store.list_budgets(BUDGET_DIR)}


@financial_analysis_router.delete("/budget/{year}/{month}")
def delete_budget(
    year: int,
    month: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Remove the stored FA budget for a specific period."""
    try:
        period = Period(year, month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not budget_store.delete_budget(BUDGET_DIR, year, month):
        raise HTTPException(status_code=404, detail=f"No budget loaded for {period.label}.")
    log_audit(
        db=db, action="Delete FA Budget", module=MODULE,
        description=f"Deleted FA budget for {period.label}",
        user_id=current_user.id, user_name=current_user.full_name, request=request,
    )
    return {"status": "deleted", "period": period.label}


@financial_analysis_router.delete("/budget")
def clear_all_budgets(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Remove all stored FA budgets."""
    deleted_count = budget_store.clear_all_budgets(BUDGET_DIR)
    log_audit(
        db=db, action="Clear FA Budgets", module=MODULE,
        description=f"Cleared {deleted_count} FA budget files",
        user_id=current_user.id, user_name=current_user.full_name, request=request,
    )
    return {"status": "deleted", "count": deleted_count}


@financial_analysis_router.post("/mapping")
async def upload_mapping(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Replaces the GL code mapping workbook (sheet '6.PL-EBITDA' layout) after validating it."""
    path = await _save_upload(file)
    try:
        mapping = await run_in_threadpool(
            mapping_store.save_mapping, MAPPING_DIR, path, file.filename, current_user.full_name
        )
    except MappingFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)

    log_audit(
        db=db, action="Upload GL Mapping", module=MODULE,
        description=f"Uploaded GL code mapping {file.filename}",
        user_id=current_user.id, user_name=current_user.full_name, request=request,
    )
    return {
        "status": "success",
        "mapping": mapping_store.mapping_info(MAPPING_DIR),
        "lines": [
            {"label": line.label, "ranges": [str(r) for r in line.ranges]}
            for line in mapping.lines.values()
        ],
        "warnings": mapping.warnings,
    }


def _summary(comparison) -> dict:
    rows = {r.key: r for r in comparison.rows}
    out = []
    for key in SUMMARY_LINES:
        r = rows[key]
        sign = -1 if key == "operating_costs" else 1   # Opex shown as a positive cost, as in the report
        out.append({
            "key": key,
            "label": "Opex" if key == "operating_costs" else r.label,
            "current": round(sign * r.current, 1),
            "base": round(sign * r.base, 1),
            "variance": round(sign * r.variance, 1),
            "variance_pct": None if r.variance_pct is None else round(sign * r.variance_pct * 100, 1),
            "favourable": r.variance >= 0,
        })
    return {"title": comparison.title, "rows": out}


@financial_analysis_router.post("/generate")
async def generate_financial_analysis(
    body: GenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    quarter = Quarter(body.year, body.quarter)
    try:
        mapping = await run_in_threadpool(mapping_store.load_mapping, MAPPING_DIR)
    except MappingFormatError as exc:
        raise HTTPException(status_code=422, detail=f"The stored GL mapping no longer reads: {exc}") from exc
    if mapping is None:
        raise HTTPException(status_code=422, detail="Upload the GL code mapping workbook first.")

    # Load budget data if available
    b_end = budget_store.load_budget(BUDGET_DIR, quarter.end)
    b_start = budget_store.load_budget(BUDGET_DIR, quarter.previous().end) if quarter.quarter > 1 else None

    load = lru_cache(maxsize=None)(lambda period: tb_store.load_ytd(db, period))
    try:
        analysis = build_analysis(quarter, load, mapping, budget_end=b_end, budget_start=b_start)
    except MissingPeriodsError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Load these trial balances before generating {quarter.label}: "
                   + ", ".join(p.label for p in exc.periods),
        ) from exc

    trend = monthly_trend(quarter.end, load, mapping)
    records = {Period(r.period_year, r.period_month): r for r in tb_store.list_periods(db)}
    used = [records[p] for p in required_periods(quarter)]
    notes = ["Trial balances used: " + "; ".join(
        f"{Period(r.period_year, r.period_month).label} ({r.source_filename})" for r in used)]
    notes += [f"GL mapping: {w}" for w in mapping.warnings]
    notes += [f"{Period(r.period_year, r.period_month).label} trial balance does not net to zero "
              f"(YTD total {r.net_ytd:,.2f})" for r in used if abs(r.net_ytd) > 100]

    try:
        output_path = await run_in_threadpool(generate_report, ReportInputs(analysis, trend, notes), OUTPUT_DIR)
    except ReportTemplateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"Financial analysis report failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to generate the report: {exc}") from exc

    log_audit(
        db=db, action="Report Generation", module=MODULE,
        description=f"Generated Financial Analysis Report for {quarter.label}",
        user_id=current_user.id, user_name=current_user.full_name, request=request,
    )

    warnings = [f"Account {u.account} {u.name.strip()} is not in the GL mapping (LKR {u.amount:,.1f} Mn, {u.period})"
                for u in analysis.unmapped] + [f"GL mapping: {w}" for w in mapping.warnings]
    return {
        "status": "success",
        "filename": output_path.name,
        "quarter": quarter.label,
        "comparisons": [_summary(c) for c in analysis.comparisons.values()],
        "margins": {k: None if v is None else round(v * 100, 1)
                    for k, v in analysis.comparisons["quarter_vs_last_year"].current.margins.items()},
        "budget_available": analysis.budget_available,
        "warnings": warnings,
    }


@financial_analysis_router.get("/download/{filename}")
async def download_financial_analysis(
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    if not FILENAME_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file not found. Generate it again.")

    log_audit(
        db=db, action="Download Report", module=MODULE,
        description=f"Downloaded Financial Analysis Report: {filename}",
        user_id=current_user.id, user_name=current_user.full_name, request=request,
    )
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
