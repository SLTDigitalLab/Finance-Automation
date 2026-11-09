"""API routes for Use Case 5: Accrual Entry Report."""

import json
import logging
from pathlib import Path
from typing import Dict
from datetime import datetime
from io import BytesIO

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.user_and_log import User
from app.routes.use_case_routes import require_use_case
from app.services.audit_logger import log_audit
from config import settings
from services.accrual_entry_report_service import (
    AccrualReportInputError,
    _period_token,
    generate_accrual_entry_report,
)

logger = logging.getLogger(__name__)

accrual_entry_router = APIRouter(
    prefix="/api/accrual-entry",
    tags=["accrual-entry-report"],
)

USE_CASE = "use_case_5"
MODULE = "Accrual Entry Report"
CATEGORIES = {
    "payment_details": "Payment details",
    "prior_accrual": "Prior month accrual",
    "account_analysis": "Account analysis",
}
BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = BASE_DIR / "uploads" / "accrual_entry_report"
OUTPUT_DIR = BASE_DIR / "outputs" / "accrual_entry_report"
SAMPLE_DIR = BASE_DIR / "files" / "New folder"
SAMPLE_FILES = {
    "payment_details": "Payment details Sep 26.xlsx",
    "prior_accrual": "Accrual-Aug 26.xlsx",
    "account_analysis": "Account analysis Sep 26.xlsx",
}
EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _period_folder(period: str) -> str:
    try:
        return _period_token(period).title()
    except AccrualReportInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _paths(period: str, user_id: int) -> Dict[str, Path]:
    folder = _period_folder(period)
    return {category: UPLOAD_DIR / str(user_id) / folder / f"{category}.xlsx" for category in CATEGORIES}


def _metadata_path(period: str, user_id: int) -> Path:
    return UPLOAD_DIR / str(user_id) / _period_folder(period) / "metadata.json"


def _read_metadata(period: str, user_id: int) -> dict:
    path = _metadata_path(period, user_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Could not read accrual input metadata for user %s, %s", user_id, period)
        raise HTTPException(status_code=500, detail="Unable to read accrual input metadata.") from exc


def _save_file(category: str, source: Path, period: str, original_name: str, user_id: int, uploaded_by: str) -> dict:
    target = _paths(period, user_id)[category]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    metadata = _read_metadata(period, user_id)
    metadata[category] = {
        "filename": original_name,
        "file_size": target.stat().st_size,
        "uploaded_at": datetime.utcnow().isoformat(),
        "uploaded_by": uploaded_by,
        "user_id": user_id,
    }
    _metadata_path(period, user_id).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata[category]


def _audit(
    db: Session,
    request: Request,
    user: User,
    action: str,
    description: str,
) -> None:
    log_audit(
        db=db,
        action=action,
        module=MODULE,
        description=description,
        user_id=user.id,
        user_name=user.full_name or user.email,
        request=request,
    )


@accrual_entry_router.get("/status")
async def get_accrual_entry_status(
    period: str = Query("Sep-26"),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    stored = _paths(period, current_user.id)
    metadata = _read_metadata(period, current_user.id)
    categories = {}
    for category, label in CATEGORIES.items():
        info = metadata.get(category, {})
        exists = stored[category].exists()
        categories[category] = {
            "label": label,
            "uploaded": exists,
            "filename": info.get("filename") if exists else None,
            "file_size": info.get("file_size") if exists else None,
            "uploaded_at": info.get("uploaded_at") if exists else None,
            "uploaded_by": info.get("uploaded_by") if exists else None,
        }
    return {
        "period": period,
        "categories": categories,
        "is_ready": all(item["uploaded"] for item in categories.values()),
    }


@accrual_entry_router.post("/upload/{category}")
async def upload_accrual_input(
    category: str,
    request: Request,
    file: UploadFile = File(...),
    period: str = Query("Sep-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category '{category}'.")
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Only .xlsx workbooks are supported.")
    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB} MB.",
        )
    try:
        workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
        workbook.close()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The uploaded file is not a readable Excel workbook.") from exc

    try:
        path = _paths(period, current_user.id)[category]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        metadata = _read_metadata(period, current_user.id)
        metadata[category] = {
            "filename": filename,
            "file_size": len(content),
            "uploaded_at": datetime.utcnow().isoformat(),
            "uploaded_by": current_user.full_name or current_user.email or "Unknown",
            "user_id": current_user.id,
        }
        _metadata_path(period, current_user.id).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    except HTTPException:
        raise
    except OSError as exc:
        logger.exception("Could not store %s accrual input", category)
        raise HTTPException(status_code=500, detail="Unable to store the uploaded workbook.") from exc

    _audit(db, request, current_user, "ACCRUAL_INPUT_UPLOADED", f"Uploaded {filename} as {category} for {period}.")
    return {"status": "success", "category": category, "file": metadata[category]}


@accrual_entry_router.delete("/file/{category}")
async def delete_accrual_input(
    category: str,
    request: Request,
    period: str = Query("Sep-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category '{category}'.")
    path = _paths(period, current_user.id)[category]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Input file not found.")
    path.unlink()
    metadata = _read_metadata(period, current_user.id)
    metadata.pop(category, None)
    _metadata_path(period, current_user.id).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    _audit(db, request, current_user, "ACCRUAL_INPUT_DELETED", f"Removed {category} input for {period}.")
    return {"status": "success", "message": f"Removed {CATEGORIES[category]} for {period}."}


@accrual_entry_router.post("/load-sample")
async def load_accrual_sample(
    request: Request,
    period: str = Query("Sep-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    if _period_folder(period).upper() != "SEP26":
        raise HTTPException(
            status_code=400,
            detail="The bundled sample workbooks are for Sep-26 only. Upload workbooks for other periods.",
        )
    missing = [name for name in SAMPLE_FILES.values() if not (SAMPLE_DIR / name).is_file()]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Sample input workbook(s) not found: {', '.join(missing)}",
        )
    metadata = _read_metadata(period, current_user.id)
    try:
        for category, filename in SAMPLE_FILES.items():
            path = SAMPLE_DIR / filename
            metadata[category] = _save_file(
                category,
                path,
                period,
                filename,
                current_user.id,
                current_user.full_name or current_user.email or "Unknown",
            )
    except OSError as exc:
        logger.exception("Could not load sample accrual dataset")
        raise HTTPException(status_code=500, detail="Unable to load the sample input workbooks.") from exc

    _audit(db, request, current_user, "ACCRUAL_SAMPLE_LOADED", f"Loaded sample accrual inputs for {period}.")
    return {"status": "success", "categories_loaded": list(SAMPLE_FILES)}


@accrual_entry_router.post("/generate")
async def generate_accrual_report(
    request: Request,
    period: str = Query("Sep-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    paths = _paths(period, current_user.id)
    missing = [CATEGORIES[category] for category, path in paths.items() if not path.is_file()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Upload all required workbooks before generating the report: {', '.join(missing)}.",
        )
    filename = f"Accrual_Entry_Report_{_period_folder(period)}.xlsx"
    output_path = OUTPUT_DIR / str(current_user.id) / _period_folder(period) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = generate_accrual_entry_report(
            payment_path=paths["payment_details"],
            prior_accrual_path=paths["prior_accrual"],
            account_analysis_path=paths["account_analysis"],
            period=period,
            output_path=output_path,
        )
    except AccrualReportInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to generate accrual report for %s", period)
        raise HTTPException(status_code=500, detail=f"Accrual report generation failed: {exc}") from exc

    _audit(
        db,
        request,
        current_user,
        "ACCRUAL_REPORT_GENERATED",
        f"Generated {filename} for {period} using the three uploaded source workbooks.",
    )
    return {"status": "success", **result}


@accrual_entry_router.get("/download")
async def download_accrual_report(
    filename: str,
    period: str = Query("Sep-26"),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    if Path(filename).name != filename or not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Invalid report filename.")
    expected = f"Accrual_Entry_Report_{_period_folder(period)}.xlsx"
    if filename != expected:
        raise HTTPException(status_code=400, detail="Report filename does not match the selected period.")
    path = OUTPUT_DIR / str(current_user.id) / _period_folder(period) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found. Generate it before downloading.")
    return FileResponse(path, filename=filename, media_type=EXCEL_MEDIA_TYPE)


@accrual_entry_router.post("/reset")
async def reset_accrual_entry_data(
    request: Request,
    period: str = Query("Sep-26"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Reset all uploaded source files and generated reports for the current user and period."""
    folder = _period_folder(period)
    upload_folder = UPLOAD_DIR / str(current_user.id) / folder
    output_folder = OUTPUT_DIR / str(current_user.id) / folder

    deleted_items = []
    for target_dir in [upload_folder, output_folder]:
        if target_dir.exists():
            for f in target_dir.glob("*.xlsx"):
                f.unlink(missing_ok=True)
                deleted_items.append(f.name)

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Reset",
        module=MODULE,
        description=f"Reset Accrual Entry Report uploads and output for period {period}.",
        request=request,
    )

    return {
        "message": f"Accrual Entry data for {period} has been reset to the initial state.",
        "deleted": deleted_items,
    }

