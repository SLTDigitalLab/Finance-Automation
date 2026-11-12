"""
Debtor Age Analysis Report API Routes
Use Case 6: Debtor Age Analysis Report
"""
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.user_and_log import User
from app.routes.use_case_routes import require_use_case
from app.services.audit_logger import log_audit
from config import settings
from services.debtor_age_analysis_service import (
    DebtorAgeAnalysisError,
    generate_debtor_age_analysis,
    validate_debtor_aging_file,
    validate_netting_report_file,
)

logger = logging.getLogger(__name__)

debtor_age_router = APIRouter(
    prefix="/api/debtor-age",
    tags=["debtor-age-analysis"],
)

USE_CASE = "use_case_6"
MODULE   = "Debtor Age Analysis Report"

UPLOAD_DIR = settings.UPLOAD_DIR / "debtor_age_analysis"
OUTPUT_DIR = settings.OUTPUT_DIR / "debtor_age_analysis"
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}

OUTPUT_FILENAME = "SLT_Debtor_Age_Analysis_Report.xlsx"
EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_upload_dir(user_id: int) -> Path:
    return UPLOAD_DIR / str(user_id)


def _user_output_dir(user_id: int) -> Path:
    return OUTPUT_DIR / str(user_id)


def _check_ext(filename: str) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Only Excel files are accepted (.xlsx, .xls, .xlsm). Got: {ext!r}",
        )


def _check_size(content: bytes) -> None:
    limit = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds the {settings.MAX_FILE_SIZE_MB} MB upload limit.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@debtor_age_router.get("/status")
async def get_debtor_age_status(
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Return the current upload status for the two input files."""
    upload_dir = _user_upload_dir(current_user.id)
    output_dir = _user_output_dir(current_user.id)

    debtor_path  = upload_dir / "debtor_aging.xlsx"
    netting_path = upload_dir / "netting_report.xlsx"
    output_path  = output_dir / OUTPUT_FILENAME

    return {
        "debtor_aging": {
            "uploaded": debtor_path.exists(),
            "filename": debtor_path.name if debtor_path.exists() else None,
            "size":     debtor_path.stat().st_size if debtor_path.exists() else None,
        },
        "netting_report": {
            "uploaded": netting_path.exists(),
            "filename": netting_path.name if netting_path.exists() else None,
            "size":     netting_path.stat().st_size if netting_path.exists() else None,
        },
        "report_ready": output_path.exists(),
        "report_filename": OUTPUT_FILENAME if output_path.exists() else None,
    }


@debtor_age_router.post("/upload/debtor-aging")
async def upload_debtor_aging(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Upload the Debtor Aging (Net of Creditors) Excel workbook."""
    _check_ext(file.filename or "")
    content = await file.read()
    _check_size(content)

    upload_dir = _user_upload_dir(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / "debtor_aging.xlsx"
    dest.write_bytes(content)

    # Validate workbook structure
    try:
        info = validate_debtor_aging_file(dest)
    except DebtorAgeAnalysisError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Upload",
        module=MODULE,
        description=f"Uploaded debtor aging file: {file.filename}",
        request=request,
    )

    return {
        "message": "Debtor aging file uploaded and validated successfully.",
        "original_filename": file.filename,
        "sheets": info["sheets"],
        "file_size": len(content),
    }


@debtor_age_router.post("/upload/netting-report")
async def upload_netting_report(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Upload the SLT AR/AP Netting Report Excel workbook."""
    _check_ext(file.filename or "")
    content = await file.read()
    _check_size(content)

    upload_dir = _user_upload_dir(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / "netting_report.xlsx"
    dest.write_bytes(content)

    # Validate
    try:
        info = validate_netting_report_file(dest)
    except DebtorAgeAnalysisError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Upload",
        module=MODULE,
        description=f"Uploaded AR/AP netting report: {file.filename}",
        request=request,
    )

    return {
        "message": "AR/AP netting report uploaded and validated successfully.",
        "original_filename": file.filename,
        "sheets": info["sheets"],
        "receivables_rows": info["receivables_rows"],
        "payables_rows": info["payables_rows"],
        "file_size": len(content),
    }


@debtor_age_router.delete("/upload/{file_key}")
async def delete_uploaded_file(
    file_key: str,
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Delete an uploaded input file. file_key: 'debtor-aging' or 'netting-report'."""
    key_map = {
        "debtor-aging":   "debtor_aging.xlsx",
        "netting-report": "netting_report.xlsx",
    }
    if file_key not in key_map:
        raise HTTPException(status_code=400, detail=f"Unknown file key: {file_key!r}")

    upload_dir = _user_upload_dir(current_user.id)
    dest = upload_dir / key_map[file_key]
    if dest.exists():
        dest.unlink()
        return {"message": f"File '{file_key}' removed."}
    return {"message": "File not found – nothing to remove."}


@debtor_age_router.post("/generate")
async def generate_report(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Generate the Debtor Age Analysis Report from the two uploaded input files."""
    upload_dir = _user_upload_dir(current_user.id)
    debtor_path  = upload_dir / "debtor_aging.xlsx"
    netting_path = upload_dir / "netting_report.xlsx"

    if not debtor_path.exists():
        raise HTTPException(
            status_code=400,
            detail="Debtor aging file has not been uploaded. Please upload it first.",
        )
    if not netting_path.exists():
        raise HTTPException(
            status_code=400,
            detail="AR/AP netting report has not been uploaded. Please upload it first.",
        )

    output_dir = _user_output_dir(current_user.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / OUTPUT_FILENAME

    try:
        await run_in_threadpool(
            generate_debtor_age_analysis,
            debtor_path,
            netting_path,
            output_path,
        )
    except DebtorAgeAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error generating Debtor Age Analysis Report: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Report generation failed: {exc}",
        )

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Generate",
        module=MODULE,
        description=f"Generated {OUTPUT_FILENAME}",
        request=request,
    )

    return {
        "message": "Debtor Age Analysis Report generated successfully.",
        "filename": OUTPUT_FILENAME,
        "file_size": output_path.stat().st_size,
    }


@debtor_age_router.get("/download")
async def download_report(
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Download the generated Debtor Age Analysis Report."""
    output_path = _user_output_dir(current_user.id) / OUTPUT_FILENAME

    if not output_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Report has not been generated yet. Please run Generate first.",
        )

    return FileResponse(
        path=str(output_path),
        filename=OUTPUT_FILENAME,
        media_type=EXCEL_MEDIA_TYPE,
    )


@debtor_age_router.post("/reset")
async def reset_debtor_age_data(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Reset all uploaded source files and generated report for the current user."""
    upload_dir = _user_upload_dir(current_user.id)
    output_dir = _user_output_dir(current_user.id)

    deleted_items = []
    for target_dir in [upload_dir, output_dir]:
        if target_dir.exists():
            for f in target_dir.glob("*"):
                if f.is_file():
                    f.unlink(missing_ok=True)
                    deleted_items.append(f.name)

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name or current_user.email,
        action="Reset",
        module=MODULE,
        description="Reset Debtor Age Analysis uploads and generated report.",
        request=request,
    )

    return {
        "message": "Debtor Age Analysis data has been reset to the initial state.",
        "deleted": deleted_items,
    }


