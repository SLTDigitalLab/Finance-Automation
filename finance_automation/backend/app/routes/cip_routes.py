"""
CIP Reconciliation API Routes
Use Case 4: CIP Reconciliation Report
"""
import logging
from pathlib import Path
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.user_and_log import User
from app.routes.use_case_routes import require_use_case
from app.services.audit_logger import log_audit
from config import settings
from services.cip_reconciliation import (
    CIPReader,
    CIPReconciliationEngine,
    CIPReportGenerator,
    get_file_path,
    get_status,
    remove_file,
    save_uploaded_file,
)
from services.cip_reconciliation.cip_journal_review_generator import CIPJournalReviewGenerator
from services.cip_reconciliation.cip_reader import CIPInputError, previous_period
from services.cip_reconciliation.cip_store import CATEGORIES, OUTPUT_DIR, UPLOAD_DIR, normalize_period

logger = logging.getLogger(__name__)

USE_CASE = "use_case_4"
MODULE = "CIP Reconciliation Report"

cip_router = APIRouter(
    prefix="/api/cip",
    tags=["cip-reconciliation"],
)

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}

def _compute_reconciliation(period: str, user_id: int):
    paths = {
        category: get_file_path(category, period, user_id=user_id)
        for category in CATEGORIES
    }
    missing = [category.replace("_", " ").title() for category, path in paths.items() if not path]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required files for reconciliation: {', '.join(missing)}",
        )

    try:
        project_master = CIPReader.read_project_master(paths["project_codes"])
        additions, _ = CIPReader.read_subledger_detail(paths["subledger_detail"])
        interfaced, _ = CIPReader.read_interfaced_cip(paths["interfaced_cip"])
        journal_summary, journal_rows = CIPReader.read_journal_details(
            paths["journal_details"],
            project_master=project_master,
        )
        opening = CIPReader.read_opening_balances(
            paths["opening_balances"],
            expected_period=previous_period(period),
        )
        engine = CIPReconciliationEngine(
            project_master=project_master,
            subledger_additions=additions,
            interfaced_cip=interfaced,
            gl_summary=journal_summary,
            opening_balances=opening,
            period=period,
            journal_rows=journal_rows,
        )
        return engine.run(), paths, project_master
    except CIPInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error executing CIP reconciliation")
        raise HTTPException(
            status_code=500,
            detail=f"Reconciliation calculation failed: {str(exc)}",
        ) from exc


@cip_router.get("/status")
async def get_cip_status(
    period: Optional[str] = Query(None),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Returns the upload and readiness status of files for the requested period."""
    try:
        return get_status(period=period, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@cip_router.post("/upload/{category}")
async def upload_cip_file(
    category: str,
    request: Request,
    file: UploadFile = File(...),
    period: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Uploads a file for one of the CIP categories."""
    try:
        period = normalize_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if category not in CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Allowed: {', '.join(CATEGORIES)}",
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file extension '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    if category == "opening_balances" and ext not in {".xlsx", ".xlsm"}:
        raise HTTPException(
            status_code=400,
            detail="Opening balance reports must use the .xlsx or .xlsm format.",
        )
    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB} MB",
        )

    # Save to temp and then store
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        uploader = current_user.full_name or current_user.email or "Unknown"
        meta = save_uploaded_file(
            category=category,
            temp_path=tmp_path,
            original_name=file.filename or f"{category}{ext}",
            period=period,
            uploaded_by=uploader,
            user_id=current_user.id,
        )
        log_audit(
            db=db,
            action="CIP_FILE_UPLOADED",
            module=MODULE,
            description=f"Uploaded {file.filename} for category {category} ({period})",
            user_id=current_user.id,
            user_name=current_user.full_name or current_user.email,
            request=request,
        )
        return {"status": "success", "file": meta}
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


@cip_router.delete("/file/{category}")
async def delete_cip_file(
    category: str,
    request: Request,
    period: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Removes an uploaded file from a category."""
    try:
        period = normalize_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")

    success = remove_file(category, period, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    log_audit(
        db=db,
        action="CIP_FILE_DELETED",
        module=MODULE,
        description=f"Deleted {category} file for {period}",
        user_id=current_user.id,
        user_name=current_user.full_name or current_user.email,
        request=request,
    )
    return {"status": "success", "message": f"{category} removed for {period}"}


@cip_router.post("/reconcile")
async def run_reconciliation(
    period: str = Query(...),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Executes reconciliation logic and caches the results."""
    try:
        period = normalize_period(period)
        result, _, _ = _compute_reconciliation(period, current_user.id)
        return {
            "status": "success",
            "period": period,
            "metrics": {
                "total_projects": result.total_projects_count,
                "reconciled_projects": result.reconciled_projects_count,
                "unreconciled_projects": result.unreconciled_projects_count,
                "total_opening": result.total_opening_balance,
                "total_additions": result.total_additions,
                "total_interface": result.total_interface,
                "total_closing": result.total_closing_balance,
                "discrepancies_count": len(result.discrepancies),
            },
            "summary": result.summary,
            "account_reconciliations": result.account_reconciliations,
            "trial_balance_reconciliations": result.trial_balance_reconciliations,
            "journal_adjustments": result.journal_adjustments,
            "discrepancies": result.discrepancies,
            "projects": result.projects,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error executing CIP reconciliation")
        raise HTTPException(
            status_code=500,
            detail=f"Reconciliation calculation failed: {str(exc)}",
        )


@cip_router.post("/generate-report")
async def generate_cip_report(
    request: Request,
    period: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Generates the Excel CIP Reconciliation Report."""
    try:
        period = normalize_period(period)
        recon_result, paths, project_master = _compute_reconciliation(period, current_user.id)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    clean_p = period.replace("-", "_")
    filename = f"CIP_Reconciliation_Report_{clean_p}.xlsx"
    journal_review_filename = f"CIP_Journal_Details_Review_{clean_p}.xlsx"
    user_out_dir = OUTPUT_DIR / str(current_user.id)
    user_out_dir.mkdir(parents=True, exist_ok=True)
    out_file = user_out_dir / filename
    journal_review_file = user_out_dir / journal_review_filename

    generator = CIPReportGenerator(recon_result)
    generator.generate(out_file)
    CIPJournalReviewGenerator.generate(
        paths["journal_details"],
        journal_review_file,
        project_master,
        recon_result.journal_adjustments,
    )

    log_audit(
        db=db,
        action="CIP_REPORT_GENERATED",
        module=MODULE,
        description=f"Generated CIP report {filename}",
        user_id=current_user.id,
        user_name=current_user.full_name or current_user.email,
        request=request,
    )

    return {
        "status": "success",
        "filename": filename,
        "journal_review_filename": journal_review_filename,
        "warnings": [
            item["detail"]
            for item in recon_result.discrepancies
            if item.get("type") in {
                "Missing Opening Balance",
                "Missing Opening Balance Account",
                "Missing Project Master",
                "Unmatched Project Code",
                "Ambiguous Project Code",
                "Project Year Mapping Variance",
                "Journal Project Missing from CIP Inputs",
                "Journal Addition Missing from Subledger",
                "Unmapped Journal Transaction",
                "Unmatched Interface Movement",
                "Journal Amount Review",
                "GL vs Subledger Variance",
                "GL vs Interface Variance",
                "Trial Balance Closing Variance",
                "Prior Period Opening Variance",
                "Missing Trial Balance Account",
            }
        ],
        "message": "Successfully generated the CIP reconciliation report and journal review.",
    }


@cip_router.get("/download")
async def download_cip_report(
    filename: Optional[str] = None,
    period: Optional[str] = Query(None),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Downloads the generated CIP Reconciliation Report."""
    if not filename:
        try:
            period = normalize_period(period)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        clean_p = period.replace("-", "_")
        filename = f"CIP_Reconciliation_Report_{clean_p}.xlsx"

    filename = Path(filename).name
    target = (OUTPUT_DIR / str(current_user.id)) / filename
    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Report file {filename} does not exist. Please generate it first.",
        )

    return FileResponse(
        path=target,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@cip_router.get("/download-journal-review")
async def download_cip_journal_review(
    filename: Optional[str] = None,
    period: Optional[str] = Query(None),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Downloads the generated journal review copy."""
    if not filename:
        try:
            period = normalize_period(period)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        clean_p = period.replace("-", "_")
        filename = f"CIP_Journal_Details_Review_{clean_p}.xlsx"

    filename = Path(filename).name
    target = (OUTPUT_DIR / str(current_user.id)) / filename
    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Journal review file {filename} does not exist. Please generate it first.",
        )

    return FileResponse(
        path=target,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@cip_router.post("/reset")
async def reset_cip_data(
    request: Request,
    period: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Reset all uploaded source files and generated reports for the current user and period."""
    try:
        period = normalize_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clean_p = period.replace("-", "_")
    upload_folder = UPLOAD_DIR / str(current_user.id) / period
    output_folder = OUTPUT_DIR / str(current_user.id)
    deleted_items = []
    for category in CATEGORIES:
        remove_file(category, period, user_id=current_user.id)
    if upload_folder.exists():
        for f in upload_folder.glob("*"):
            if f.is_file():
                f.unlink(missing_ok=True)
                deleted_items.append(f.name)

    if output_folder.exists():
        for f in output_folder.glob(f"*{clean_p}*"):
            if f.is_file():
                f.unlink(missing_ok=True)
                deleted_items.append(f.name)

    log_audit(
        db=db,
        action="Reset",
        module=MODULE,
        description=f"Reset CIP Reconciliation uploads and report for period {period}.",
        user_id=current_user.id,
        user_name=current_user.full_name or current_user.email,
        request=request,
    )

    return {
        "message": f"CIP Reconciliation data for {period} has been reset to the initial state.",
        "deleted": deleted_items,
    }
