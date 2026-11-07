"""
Remaining Financial Inputs API Routes for Financial Analysis module.
Handles upload, retrieval, and status for Mobitel Management Write-up (.docx)
and Group Financial P&L (.xlsx).
"""
import logging
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.user_and_log import User
from app.routes.use_case_routes import require_use_case
from app.services.audit_logger import log_audit
from config import settings
from services.financial_analysis import remaining_inputs_store
from services.financial_analysis.group_pl_reader import GroupPLReader
from services.financial_analysis.mobitel_writeup_reader import MobitelWriteupReader
from services.financial_analysis.validation_dashboard import build_validation_dashboard

logger = logging.getLogger(__name__)

USE_CASE = "financial_analysis"
MODULE = "Financial Analysis - Remaining Inputs"

remaining_inputs_router = APIRouter(
    prefix="/api/financial-analysis/remaining-inputs",
    tags=["remaining-inputs"],
)

ALLOWED_DOCX = {".docx"}
ALLOWED_EXCEL = {".xlsx", ".xls", ".xlsm"}


def _user_store_dir(user_id: int) -> Path:
    return settings.UPLOAD_DIR / "financial_analysis" / str(user_id) / "remaining_inputs"


async def _save_temp_upload(file: UploadFile, allowed_exts: set) -> Tuple[Path, str]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type for {file.filename}. Allowed extensions: {', '.join(allowed_exts)}",
        )

    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"{file.filename} exceeds {settings.MAX_FILE_SIZE_MB} MB limit.",
        )

    temp_dir = Path(tempfile.gettempdir())
    temp_path = temp_dir / f"upload_{file.filename}"
    temp_path.write_bytes(content)
    return temp_path, file.filename or "uploaded_file"


@remaining_inputs_router.post("/upload/mobitel-writeup")
async def upload_mobitel_writeup(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Uploads and validates a Mobitel Management Write-up (.docx) file."""
    temp_path, orig_filename = await _save_temp_upload(file, ALLOWED_DOCX)

    try:
        # Validate readability first
        reader = MobitelWriteupReader()
        writeup = await run_in_threadpool(reader.read, temp_path)

        # Save to store
        user_name = current_user.full_name if current_user else "System"
        store_dir = _user_store_dir(current_user.id)
        saved_path = remaining_inputs_store.save_file(
            file_type="mobitel_writeup",
            path=temp_path,
            filename=orig_filename,
            uploader=user_name,
            store_dir=store_dir,
            user_id=current_user.id,
        )
    except Exception as exc:
        logger.exception(f"Failed to read/save Mobitel Write-up: {exc}")
        raise HTTPException(status_code=422, detail=f"Failed to process Mobitel Write-up: {exc}") from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    log_audit(
        db=db,
        action="Upload Mobitel Write-up",
        module=MODULE,
        description=f"Uploaded Mobitel Write-up: {orig_filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request,
    )

    return {
        "status": "success",
        "file_type": "mobitel_writeup",
        "filename": orig_filename,
        "sections_detected": list(writeup.raw_sections.keys()),
        "has_exec_summary": bool(writeup.exec_summary),
        "has_section_a": bool(writeup.section_a_yoy),
        "has_section_b": bool(writeup.section_b_qoq),
        "has_section_c": bool(writeup.section_c_ytd),
        "has_section_d": bool(writeup.section_d_budget),
        "warnings": writeup.warnings,
    }


@remaining_inputs_router.post("/upload/group-pl")
async def upload_group_pl(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Uploads and validates a Group Financial P&L (.xlsx) file."""
    temp_path, orig_filename = await _save_temp_upload(file, ALLOWED_EXCEL)

    try:
        # Validate readability first
        reader = GroupPLReader()
        pl_data = await run_in_threadpool(reader.read, temp_path)

        # Save to store
        user_name = current_user.full_name if current_user else "System"
        store_dir = _user_store_dir(current_user.id)
        saved_path = remaining_inputs_store.save_file(
            file_type="group_pl",
            path=temp_path,
            filename=orig_filename,
            uploader=user_name,
            store_dir=store_dir,
            user_id=current_user.id,
        )
    except Exception as exc:
        logger.exception(f"Failed to read/save Group P&L: {exc}")
        raise HTTPException(status_code=422, detail=f"Failed to process Group P&L: {exc}") from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    log_audit(
        db=db,
        action="Upload Group P&L",
        module=MODULE,
        description=f"Uploaded Group P&L workbook: {orig_filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request,
    )

    mobitel_figures = pl_data.entities.get("Mobitel")
    group_figures = pl_data.entities.get("Group")

    return {
        "status": "success",
        "file_type": "group_pl",
        "filename": orig_filename,
        "entities_found": list(pl_data.entities.keys()),
        "periods": pl_data.periods,
        "mobitel_revenue_current": mobitel_figures.revenue_current if mobitel_figures else None,
        "group_revenue_current": group_figures.revenue_current if group_figures else None,
        "warnings": pl_data.warnings,
    }


@remaining_inputs_router.get("/status")
def get_remaining_inputs_status(
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Returns current upload status and validation overview for remaining inputs."""
    store_dir = _user_store_dir(current_user.id)
    uploads = remaining_inputs_store.get_status(store_dir=store_dir)

    # If files exist, generate validation dashboard
    mob_path = remaining_inputs_store.load_file("mobitel_writeup", store_dir=store_dir)
    grp_path = remaining_inputs_store.load_file("group_pl", store_dir=store_dir)

    mob_data = None
    if mob_path and mob_path.exists():
        try:
            mob_data = MobitelWriteupReader().read(mob_path)
        except Exception as exc:
            logger.warning(f"Could not parse stored mobitel writeup for user {current_user.id}: {exc}")

    grp_data = None
    if grp_path and grp_path.exists():
        try:
            grp_data = GroupPLReader().read(grp_path)
        except Exception as exc:
            logger.warning(f"Could not parse stored group pl for user {current_user.id}: {exc}")

    dashboard = build_validation_dashboard(analysis=None, mobitel_writeup=mob_data, group_pl_data=grp_data)

    return {
        "uploads": uploads,
        "validation": dashboard.to_dict(),
    }


@remaining_inputs_router.delete("/{file_type}")
def delete_remaining_input(
    file_type: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Deletes an uploaded remaining input file."""
    norm_type = file_type.lower().replace("-", "_").strip()
    if norm_type not in ("mobitel_writeup", "group_pl"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file_type '{file_type}'. Must be 'mobitel_writeup' or 'group_pl'.",
        )

    store_dir = _user_store_dir(current_user.id)
    deleted = remaining_inputs_store.delete_file(norm_type, store_dir=store_dir)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"No file found to delete for '{file_type}'.",
        )

    log_audit(
        db=db,
        action="Delete Remaining Input",
        module=MODULE,
        description=f"Deleted remaining input: {norm_type}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request,
    )

    return {
        "status": "success",
        "deleted": deleted,
        "uploads": remaining_inputs_store.get_status(store_dir=store_dir),
    }
