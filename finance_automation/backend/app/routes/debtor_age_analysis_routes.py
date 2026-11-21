"""
Debtor Age Analysis Report API Routes
Use Case 6: Debtor Age Analysis Report
"""
import json
import logging
import os
import tempfile
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
import openpyxl
import xlrd
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
from services.supplier_net_aging_service import (
    CreditorAgingError,
    generate_creditor_aging_report,
    validate_creditor_netting_file,
    validate_erp_debtor_file,
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
ALLOWED_EXTENSIONS = {".xlsx", ".xls"}

OUTPUT_FILENAME = "SLT_Debtor_Age_Analysis_Report.xlsx"
SUPPLIER_NET_OUTPUT_FILENAME = "Creditor_Aging_Supplier_Net_Balance_Report.xlsx"
ALL_REPORTS_FILENAME = "Debtor_Creditor_Aging_Reports.zip"
GENERATION_SUMMARY_FILENAME = "generation_summary.json"
EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP_MEDIA_TYPE = "application/zip"


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
            detail=f"Only Excel files are accepted (.xlsx, .xls). Got: {ext!r}",
        )


def _check_size(content: bytes) -> None:
    limit = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds the {settings.MAX_FILE_SIZE_MB} MB upload limit.",
        )


def _stage_upload(content: bytes, filename: str, upload_dir: Path) -> Path:
    """Write an upload as XLSX so both legacy XLS and XLSX inputs are readable."""
    staged_path = upload_dir / f".upload-{uuid.uuid4().hex}.xlsx"
    if Path(filename or "").suffix.lower() != ".xls":
        staged_path.write_bytes(content)
        return staged_path

    workbook = None
    try:
        source = xlrd.open_workbook(file_contents=content)
        workbook = openpyxl.Workbook()
        workbook.remove(workbook.active)
        for source_sheet in source.sheets():
            worksheet = workbook.create_sheet(source_sheet.name)
            for row_index in range(source_sheet.nrows):
                values = []
                for column_index in range(source_sheet.ncols):
                    cell = source_sheet.cell(row_index, column_index)
                    value = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        value = xlrd.xldate.xldate_as_datetime(value, source.datemode)
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        value = bool(value)
                    elif cell.ctype == xlrd.XL_CELL_EMPTY:
                        value = None
                    elif cell.ctype == xlrd.XL_CELL_ERROR:
                        value = xlrd.error_text_from_code(value)
                    values.append(value)
                worksheet.append(values)
        workbook.save(staged_path)
        return staged_path
    except Exception as exc:
        staged_path.unlink(missing_ok=True)
        logger.warning("Could not normalize uploaded Excel workbook %s: %s", filename, exc)
        raise HTTPException(
            status_code=422,
            detail=f"Cannot read legacy Excel workbook: {exc}",
        ) from exc
    finally:
        if workbook is not None:
            workbook.close()


def _invalidate_combined_reports(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for filename in (
        OUTPUT_FILENAME,
        SUPPLIER_NET_OUTPUT_FILENAME,
        ALL_REPORTS_FILENAME,
        GENERATION_SUMMARY_FILENAME,
    ):
        (output_dir / filename).unlink(missing_ok=True)


def _debtor_report_date(path: Path) -> Optional[str]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        value = workbook["SLT_Debtor_Age_Analysis_Report_"].cell(2, 2).value
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value) if value is not None else None
    finally:
        workbook.close()


def _supplier_review_warnings(path: Path) -> list[str]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook["Reconciliation"]
        statuses = [
            row[4]
            for row in worksheet.iter_rows(min_row=20, values_only=True)
            if len(row) > 4
        ]
        warnings = []
        review_count = statuses.count("Matched - review mapping")
        debtor_only_count = statuses.count("Debtor only")
        creditor_only_count = statuses.count("Creditor only")
        if review_count:
            warnings.append(f"{review_count} supplier match(es) need mapping review.")
        if debtor_only_count or creditor_only_count:
            warnings.append(
                f"Unmatched suppliers: {debtor_only_count} debtor-only and "
                f"{creditor_only_count} creditor-only; see the Reconciliation report."
            )
        return warnings
    finally:
        workbook.close()

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@debtor_age_router.get("/status")
async def get_debtor_age_status(
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Return upload status and the latest unified report summary."""
    upload_dir = _user_upload_dir(current_user.id)
    output_dir = _user_output_dir(current_user.id)

    debtor_path  = upload_dir / "debtor_aging.xlsx"
    netting_path = upload_dir / "netting_report.xlsx"
    output_path  = output_dir / OUTPUT_FILENAME
    creditor_netting_path = upload_dir / "creditor_netting.xlsx"
    erp_debtor_path = upload_dir / "erp_debtor_aging.xlsx"
    supplier_net_output_path = output_dir / SUPPLIER_NET_OUTPUT_FILENAME
    all_reports_path = output_dir / ALL_REPORTS_FILENAME
    summary_path = output_dir / GENERATION_SUMMARY_FILENAME
    all_reports_ready = all(
        path.exists()
        for path in (
            output_path,
            supplier_net_output_path,
            all_reports_path,
            summary_path,
        )
    )
    generation_summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if all_reports_ready
        else None
    )

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
        "creditor_netting": {
            "uploaded": creditor_netting_path.exists(),
            "filename": creditor_netting_path.name if creditor_netting_path.exists() else None,
            "size": creditor_netting_path.stat().st_size if creditor_netting_path.exists() else None,
        },
        "erp_debtor_aging": {
            "uploaded": erp_debtor_path.exists(),
            "filename": erp_debtor_path.name if erp_debtor_path.exists() else None,
            "size": erp_debtor_path.stat().st_size if erp_debtor_path.exists() else None,
        },
        "creditor_report_ready": supplier_net_output_path.exists(),
        "creditor_report_filename": (
            SUPPLIER_NET_OUTPUT_FILENAME if supplier_net_output_path.exists() else None
        ),
        "all_reports_ready": all_reports_ready,
        "all_reports_filename": ALL_REPORTS_FILENAME if all_reports_ready else None,
        "generation_summary": generation_summary,
        "reports_outdated": all(
            path.exists() for path in (debtor_path, netting_path, erp_debtor_path)
        ) and not all_reports_ready,
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
    staged_path = _stage_upload(content, file.filename or "", upload_dir)

    # Validate workbook structure
    try:
        info = validate_debtor_aging_file(staged_path)
    except DebtorAgeAnalysisError as exc:
        staged_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))
    os.replace(staged_path, dest)
    _invalidate_combined_reports(_user_output_dir(current_user.id))

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
@debtor_age_router.post("/upload/shared-netting-report")
async def upload_shared_netting_report(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Upload the single AR/AP workbook shared by the debtor and creditor processes."""
    _check_ext(file.filename or "")
    content = await file.read()
    _check_size(content)

    upload_dir = _user_upload_dir(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / "netting_report.xlsx"
    staged_path = _stage_upload(content, file.filename or "", upload_dir)
    try:
        debtor_info = validate_netting_report_file(staged_path)
        creditor_info = validate_creditor_netting_file(staged_path)
        if not debtor_info["receivables_rows"]:
            raise DebtorAgeAnalysisError(
                "The netting workbook contains no Receivables transactions."
            )
    except (DebtorAgeAnalysisError, CreditorAgingError) as exc:
        staged_path.unlink(missing_ok=True)
        logger.warning(
            "Rejected shared AR/AP netting workbook for user %s (%s): %s",
            current_user.id,
            file.filename,
            exc,
        )
        raise HTTPException(status_code=422, detail=str(exc))
    os.replace(staged_path, dest)
    _invalidate_combined_reports(_user_output_dir(current_user.id))

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Upload",
        module=MODULE,
        description=f"Uploaded shared AR/AP netting report: {file.filename}",
        request=request,
    )
    return {
        "message": "Shared AR/AP netting report uploaded and validated for both processes.",
        "original_filename": file.filename,
        "sheets": debtor_info["sheets"],
        "receivables_rows": debtor_info["receivables_rows"],
        "payables_rows": creditor_info["payables_rows"],
        "currencies": creditor_info["currencies"],
        "file_size": len(content),
    }


@debtor_age_router.post("/upload/creditor-netting")
async def upload_creditor_netting(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Upload a payable netting report identified by its Excel headers."""
    _check_ext(file.filename or "")
    content = await file.read()
    _check_size(content)

    upload_dir = _user_upload_dir(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / "creditor_netting.xlsx"
    staged_path = _stage_upload(content, file.filename or "", upload_dir)
    try:
        info = validate_creditor_netting_file(staged_path)
    except CreditorAgingError as exc:
        staged_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))
    os.replace(staged_path, dest)
    _invalidate_combined_reports(_user_output_dir(current_user.id))

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Upload",
        module=MODULE,
        description=f"Uploaded creditor netting file: {file.filename}",
        request=request,
    )
    return {
        "message": "Creditor netting file uploaded and validated successfully.",
        "original_filename": file.filename,
        "payables_rows": info["payables_rows"],
        "currencies": info["currencies"],
        "file_size": len(content),
    }


@debtor_age_router.post("/upload/erp-debtor-aging")
async def upload_erp_debtor_aging(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Upload a debtor ERP aging report identified by its Excel headers."""
    _check_ext(file.filename or "")
    content = await file.read()
    _check_size(content)

    upload_dir = _user_upload_dir(current_user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / "erp_debtor_aging.xlsx"
    staged_path = _stage_upload(content, file.filename or "", upload_dir)
    try:
        info = validate_erp_debtor_file(staged_path)
    except CreditorAgingError as exc:
        staged_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))
    os.replace(staged_path, dest)
    _invalidate_combined_reports(_user_output_dir(current_user.id))

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Upload",
        module=MODULE,
        description=f"Uploaded debtor ERP aging file: {file.filename}",
        request=request,
    )
    return {
        "message": "Debtor ERP aging file uploaded and validated successfully.",
        "original_filename": file.filename,
        "report_date": info["report_date"].isoformat(),
        "currency": info["currency"],
        "transaction_rows": info["transaction_rows"],
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
        "shared-netting-report": "netting_report.xlsx",
        "creditor-netting": "creditor_netting.xlsx",
        "erp-debtor-aging": "erp_debtor_aging.xlsx",
    }
    if file_key not in key_map:
        raise HTTPException(status_code=400, detail=f"Unknown file key: {file_key!r}")

    upload_dir = _user_upload_dir(current_user.id)
    dest = upload_dir / key_map[file_key]
    if dest.exists():
        dest.unlink()
        _invalidate_combined_reports(_user_output_dir(current_user.id))
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


@debtor_age_router.post("/generate/creditor-aging")
async def generate_creditor_report(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Generate the creditor aging and supplier net balance workbook."""
    upload_dir = _user_upload_dir(current_user.id)
    creditor_netting_path = upload_dir / "creditor_netting.xlsx"
    erp_debtor_path = upload_dir / "erp_debtor_aging.xlsx"
    if not creditor_netting_path.exists():
        raise HTTPException(status_code=400, detail="Creditor netting file has not been uploaded.")
    if not erp_debtor_path.exists():
        raise HTTPException(status_code=400, detail="Debtor ERP aging file has not been uploaded.")

    output_dir = _user_output_dir(current_user.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / SUPPLIER_NET_OUTPUT_FILENAME
    try:
        result = await run_in_threadpool(
            generate_creditor_aging_report,
            creditor_netting_path,
            erp_debtor_path,
            output_path,
        )
    except CreditorAgingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error generating creditor aging report: %s", exc)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Generate",
        module=MODULE,
        description=f"Generated {SUPPLIER_NET_OUTPUT_FILENAME}",
        request=request,
    )
    return {
        "message": "Creditor Aging and Supplier-wise Net Balance Report generated successfully.",
        "filename": SUPPLIER_NET_OUTPUT_FILENAME,
        "file_size": output_path.stat().st_size,
        "report_date": result["report_date"].isoformat(),
        "currency": result["currency"],
        "debtor_total": str(result["debtor_total"]),
        "creditor_total": str(result["creditor_total"]),
        "net_total": str(result["net_total"]),
    }


@debtor_age_router.get("/download/creditor-aging")
async def download_creditor_report(
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    output_path = _user_output_dir(current_user.id) / SUPPLIER_NET_OUTPUT_FILENAME
    if not output_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Creditor aging report has not been generated yet.",
        )
    return FileResponse(
        path=str(output_path),
        filename=SUPPLIER_NET_OUTPUT_FILENAME,
        media_type=EXCEL_MEDIA_TYPE,
    )


@debtor_age_router.post("/generate/all")
async def generate_all_reports(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Run both aging processes from the three unified input workbooks."""
    upload_dir = _user_upload_dir(current_user.id)
    debtor_path = upload_dir / "debtor_aging.xlsx"
    netting_path = upload_dir / "netting_report.xlsx"
    erp_debtor_path = upload_dir / "erp_debtor_aging.xlsx"
    missing = [
        label
        for label, path in (
            ("Debtor Aging workbook", debtor_path),
            ("shared SLT AR/AP Netting Report workbook", netting_path),
            ("SLT Debtor Age Analysis ERP Report", erp_debtor_path),
        )
        if not path.exists()
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Upload all required workbooks before generating reports: {', '.join(missing)}.",
        )

    output_dir = _user_output_dir(current_user.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    _invalidate_combined_reports(output_dir)

    with tempfile.TemporaryDirectory(prefix="aging-", dir=str(output_dir)) as temp_dir:
        staged_dir = Path(temp_dir)
        debtor_output = staged_dir / OUTPUT_FILENAME
        creditor_output = staged_dir / SUPPLIER_NET_OUTPUT_FILENAME
        try:
            await run_in_threadpool(
                generate_debtor_age_analysis,
                debtor_path,
                netting_path,
                debtor_output,
            )
        except DebtorAgeAnalysisError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Debtor Aging process failed: {exc}",
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error generating Debtor Aging report: %s", exc)
            raise HTTPException(
                status_code=500,
                detail=f"Debtor Aging process failed: {exc}",
            ) from exc

        try:
            creditor_result = await run_in_threadpool(
                generate_creditor_aging_report,
                netting_path,
                erp_debtor_path,
                creditor_output,
            )
        except CreditorAgingError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Creditor Aging process failed: {exc}",
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error generating Creditor Aging reports: %s", exc)
            raise HTTPException(
                status_code=500,
                detail=f"Creditor Aging process failed: {exc}",
            ) from exc

        warnings = _supplier_review_warnings(creditor_output)
        summary = {
            "debtor_process": {
                "status": "success",
                "report_count": 1,
                "report_date": _debtor_report_date(debtor_output),
                "reports": [OUTPUT_FILENAME],
            },
            "creditor_process": {
                "status": "success",
                "report_count": 3,
                "report_date": creditor_result["report_date"].isoformat(),
                "currency": creditor_result["currency"],
                "reports": [
                    "Creditor Aging Details",
                    "Supplier-wise Net Aging",
                    "Reconciliation",
                ],
            },
            "reconciliation": {
                "currency": creditor_result["currency"],
                "debtor_total": str(creditor_result["debtor_total"]),
                "creditor_total": str(creditor_result["creditor_total"]),
                "net_total": str(creditor_result["net_total"]),
            },
            "warnings": warnings,
            "output_files": [OUTPUT_FILENAME, SUPPLIER_NET_OUTPUT_FILENAME],
        }

        try:
            debtor_final = output_dir / OUTPUT_FILENAME
            creditor_final = output_dir / SUPPLIER_NET_OUTPUT_FILENAME
            os.replace(debtor_output, debtor_final)
            os.replace(creditor_output, creditor_final)

            zip_staged = staged_dir / ALL_REPORTS_FILENAME
            with zipfile.ZipFile(zip_staged, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(debtor_final, arcname=OUTPUT_FILENAME)
                archive.write(creditor_final, arcname=SUPPLIER_NET_OUTPUT_FILENAME)
            os.replace(zip_staged, output_dir / ALL_REPORTS_FILENAME)
            (output_dir / GENERATION_SUMMARY_FILENAME).write_text(
                json.dumps(summary, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            _invalidate_combined_reports(output_dir)
            logger.exception("Could not finalize combined aging reports: %s", exc)
            raise HTTPException(
                status_code=500,
                detail=f"Could not finalize combined aging reports: {exc}",
            ) from exc

    log_audit(
        db=db,
        user_id=current_user.id,
        user_name=current_user.full_name,
        action="Generate",
        module=MODULE,
        description="Generated all Debtor and Creditor Aging reports.",
        request=request,
    )
    return {
        "message": "Debtor and Creditor Aging reports generated successfully.",
        **summary,
        "filename": ALL_REPORTS_FILENAME,
    }


@debtor_age_router.get("/download/all")
async def download_all_reports(
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    """Download all latest debtor and creditor aging reports in one ZIP archive."""
    output_dir = _user_output_dir(current_user.id)
    zip_path = output_dir / ALL_REPORTS_FILENAME
    ready = all(
        path.exists()
        for path in (
            zip_path,
            output_dir / OUTPUT_FILENAME,
            output_dir / SUPPLIER_NET_OUTPUT_FILENAME,
            output_dir / GENERATION_SUMMARY_FILENAME,
        )
    )
    if not ready:
        raise HTTPException(
            status_code=404,
            detail="All reports are not ready or are outdated. Generate all reports again before downloading.",
        )
    return FileResponse(
        path=str(zip_path),
        filename=ALL_REPORTS_FILENAME,
        media_type=ZIP_MEDIA_TYPE,
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


