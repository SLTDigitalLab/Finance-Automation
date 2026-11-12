"""
CIP Reconciliation API Routes
Use Case 4: CIP Reconciliation Report
"""
import io
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
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
    load_metadata,
    remove_file,
    save_uploaded_file,
)
from services.cip_reconciliation.cip_store import CATEGORIES, OUTPUT_DIR, UPLOAD_DIR

logger = logging.getLogger(__name__)

USE_CASE = "use_case_4"
MODULE = "CIP Reconciliation Report"

cip_router = APIRouter(
    prefix="/api/cip",
    tags=["cip-reconciliation"],
)

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}

# In-memory cache for current reconciliation result
_RECON_CACHE: Dict[str, Any] = {}


@cip_router.get("/status")
async def get_cip_status(
    period: str = Query("Jul-26"),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Returns the upload and readiness status of files for the requested period."""
    return get_status(period=period, user_id=current_user.id)


@cip_router.post("/upload/{category}")
async def upload_cip_file(
    category: str,
    request: Request,
    file: UploadFile = File(...),
    period: str = Query("Jul-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Uploads a file for one of the CIP categories."""
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
    period: str = Query("Jul-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Removes an uploaded file from a category."""
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


@cip_router.post("/load-sample")
async def load_sample_dataset(
    request: Request,
    period: str = Query("Jul-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Loads the reference July 2026 dataset from the Input folder directly."""
    # Input folder is one level above the backend/ directory
    input_base = settings.BASE_DIR.parent / "Input" / "CIP_Reconciliation_report"
    if not input_base.exists():
        # Fallback: resolve from this file's location
        input_base = Path(__file__).resolve().parent.parent.parent.parent / "Input" / "CIP_Reconciliation_report"

    if not input_base.exists():
        raise HTTPException(status_code=404, detail=f"Sample dataset folder not found at {input_base}")

    sample_mappings = {
        "journal_details": "Journal Details_Jul 26.xlsx",
        "project_codes": "Project_Details_Codes.xlsx",
        "interfaced_cip": "SLT_Interfaced_CIP_RWIP_Amount_jUL26_111401 to 111406.xls",
        "subledger_detail": "SLT_Project_Subledger__Detail__Jul26_111401 to 111406.xlsx",
        "opening_balances": "CIP reconciliation report_Jul26_output file.xlsx",
    }

    uploader = current_user.full_name or current_user.email or "Demo Admin"
    loaded = []

    for cat, filename in sample_mappings.items():
        src_path = input_base / filename
        if src_path.exists():
            save_uploaded_file(
                category=cat,
                temp_path=src_path,
                original_name=filename,
                period=period,
                uploaded_by=uploader,
                user_id=current_user.id,
            )
            loaded.append(cat)

    log_audit(
        db=db,
        action="CIP_SAMPLE_LOADED",
        module=MODULE,
        description=f"Loaded July 2026 sample files for categories: {', '.join(loaded)}",
        user_id=current_user.id,
        user_name=current_user.full_name or current_user.email,
        request=request,
    )

    return {
        "status": "success",
        "message": f"Successfully loaded {len(loaded)} sample files for {period}.",
        "categories_loaded": loaded,
    }


@cip_router.post("/reconcile")
async def run_reconciliation(
    period: str = Query("Jul-26"),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Executes reconciliation logic and caches the results."""
    # Find all file paths for current user
    pm_path = get_file_path("project_codes", period, user_id=current_user.id)
    sub_path = get_file_path("subledger_detail", period, user_id=current_user.id)
    int_path = get_file_path("interfaced_cip", period, user_id=current_user.id)
    jd_path = get_file_path("journal_details", period, user_id=current_user.id)
    open_path = get_file_path("opening_balances", period, user_id=current_user.id)

    missing = []
    if not pm_path:
        missing.append("Project Details & Codes")
    if not sub_path:
        missing.append("Project Subledger Details")
    if not int_path:
        missing.append("Interfaced CIP Amounts")
    if not jd_path:
        missing.append("Journal Details")

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required files for reconciliation: {', '.join(missing)}",
        )

    try:
        pm = CIPReader.read_project_master(pm_path)
        sub_add, _ = CIPReader.read_subledger_detail(sub_path)
        int_cip, _ = CIPReader.read_interfaced_cip(int_path)
        gl_summary, _ = CIPReader.read_journal_details(jd_path)
        opening = CIPReader.read_opening_balances(open_path) if open_path else {}

        engine = CIPReconciliationEngine(
            project_master=pm,
            subledger_additions=sub_add,
            interfaced_cip=int_cip,
            gl_summary=gl_summary,
            opening_balances=opening,
            period=period,
        )

        result = engine.run()
        _RECON_CACHE[f"{current_user.id}_{period}"] = result

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
            "discrepancies": result.discrepancies,
            "projects": result.projects,
        }
    except Exception as exc:
        logger.exception("Error executing CIP reconciliation")
        raise HTTPException(
            status_code=500,
            detail=f"Reconciliation calculation failed: {str(exc)}",
        )


@cip_router.post("/generate-report")
async def generate_cip_report(
    request: Request,
    period: str = Query("Jul-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Generates the Excel CIP Reconciliation Report."""
    recon_result = _RECON_CACHE.get(f"{current_user.id}_{period}")
    if not recon_result:
        # Run reconciliation automatically if not cached
        pm_path = get_file_path("project_codes", period, user_id=current_user.id)
        sub_path = get_file_path("subledger_detail", period, user_id=current_user.id)
        int_path = get_file_path("interfaced_cip", period, user_id=current_user.id)
        jd_path = get_file_path("journal_details", period, user_id=current_user.id)
        open_path = get_file_path("opening_balances", period, user_id=current_user.id)

        if not (pm_path and sub_path and int_path and jd_path):
            raise HTTPException(status_code=400, detail="Missing required files to generate report")

        pm = CIPReader.read_project_master(pm_path)
        sub_add, _ = CIPReader.read_subledger_detail(sub_path)
        int_cip, _ = CIPReader.read_interfaced_cip(int_path)
        gl_summary, _ = CIPReader.read_journal_details(jd_path)
        opening = CIPReader.read_opening_balances(open_path) if open_path else {}

        engine = CIPReconciliationEngine(
            project_master=pm,
            subledger_additions=sub_add,
            interfaced_cip=int_cip,
            gl_summary=gl_summary,
            opening_balances=opening,
            period=period,
        )
        recon_result = engine.run()
        _RECON_CACHE[f"{current_user.id}_{period}"] = recon_result

    clean_p = period.replace(" ", "_").replace("-", "_")
    filename = f"CIP_Reconciliation_Report_{clean_p}.xlsx"
    user_out_dir = OUTPUT_DIR / str(current_user.id)
    user_out_dir.mkdir(parents=True, exist_ok=True)
    out_file = user_out_dir / filename

    generator = CIPReportGenerator(recon_result)
    generator.generate(out_file)

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
        "message": f"Successfully generated report {filename}",
    }


@cip_router.get("/download")
async def download_cip_report(
    filename: Optional[str] = None,
    period: str = Query("Jul-26"),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Downloads the generated CIP Reconciliation Report."""
    if not filename:
        clean_p = period.replace(" ", "_").replace("-", "_")
        filename = f"CIP_Reconciliation_Report_{clean_p}.xlsx"

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


@cip_router.post("/reset")
async def reset_cip_data(
    request: Request,
    period: str = Query("Jul-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Reset all uploaded source files and generated reports for the current user and period."""
    clean_p = period.replace(" ", "_").replace("-", "_")
    upload_folder = UPLOAD_DIR / str(current_user.id) / clean_p
    output_folder = OUTPUT_DIR / str(current_user.id)

    deleted_items = []
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
