from importlib.resources import files
import datetime
import hashlib
import os
import json
import re
import time
import uuid
import shutil
from pathlib import Path
import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Depends, Request, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database.connection import get_db, SessionLocal
from app.auth.jwt_handler import get_admin_user, get_current_active_user
from app.models.user_and_log import (
    FinancialTBRecord,
    PLRevenueRecord,
    ReportJob,
    UploadedFinanceFile,
    User,
)
from app.services.audit_logger import log_audit
from utils.logger import logger
from config import settings
from models import UploadedFiles, ReportResponse, RevenueSummary
from services.pl_reader import read_pl_workbook
from services.validators import (
    validate_uploaded_files,
    validate_mapping_workbook,
    validate_budget_workbook,
    validate_trial_balance,
)
from services.file_reader import (
    read_current_year_tb,
    read_previous_year_tb,
    detect_tb_month_and_year,
)
from services.mapping_engine import MappingEngine
from services.tb_processor import process_trial_balance
from services.budget_processor import BudgetProcessor
from services.calculations import calculate_revenue
from services.ppt_generator import generate_pptx

router = APIRouter(prefix="/api", tags=["finance"])

uploaded_files_store: dict = {}
report_jobs: dict = {}
unmapped_jobs: dict = {}


def _sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _persist_tb_data(
    db: Session,
    session_id: str,
    user_id: int,
    current_report_month: str,
    current_report_year: int,
    previous_report_month: str,
    previous_report_year: int,
    file_paths: dict,
    current_tb_df,
    previous_tb_df,
):
    """Persist mapped TB rows without changing the DataFrames used for reporting."""
    file_data = (
        ("tb_current", current_tb_df),
        ("tb_previous", previous_tb_df),
    )
    new_current_tb_processed = False
    try:
        for file_type, tb_df in file_data:
            period_month, period_year = (
                (current_report_month, current_report_year)
                if file_type == "tb_current"
                else (previous_report_month, previous_report_year)
            )
            file_path = Path(file_paths[file_type])
            file_hash = _sha256_file(file_path)
            duplicate_file = (
                db.query(UploadedFinanceFile)
                .filter(UploadedFinanceFile.file_hash == file_hash)
                .first()
            )
            if duplicate_file is not None:
                logger.info(
                    "Exact duplicate TB file already exists: "
                    f"hash={file_hash}, file_type={duplicate_file.file_type}, "
                    f"uploaded_file_id={duplicate_file.id}"
                )
                continue

            uploaded_file = (
                db.query(UploadedFinanceFile)
                .filter(
                    UploadedFinanceFile.session_id == session_id,
                    UploadedFinanceFile.file_type == file_type,
                )
                .first()
            )

            if uploaded_file is None:
                original_filename = file_path.name.split("__", 1)[-1]
                uploaded_file = UploadedFinanceFile(
                    session_id=session_id,
                    user_id=user_id,
                    file_type=file_type,
                    original_filename=original_filename,
                    file_hash=file_hash,
                    period_month=period_month,
                    period_year=period_year,
                    file_size=file_path.stat().st_size if file_path.exists() else None,
                )
                db.add(uploaded_file)
                db.flush()

            existing_row_indexes = {
                row_index
                for (row_index,) in db.query(FinancialTBRecord.row_index)
                .filter(FinancialTBRecord.uploaded_file_id == uploaded_file.id)
                .all()
            }

            fields = (
                "gl_code",
                "description",
                "flexfield",
                "cost_center",
                "location",
                "business_line",
                "product",
                "account",
                "technology",
                "intercompany",
                "project",
                "beginning_balance",
                "period_activity",
                "ending_balance",
                "revenue_category",
                "sub_category",
            )
            for row_index, row in enumerate(tb_df.to_dict("records"), start=1):
                if row_index in existing_row_indexes:
                    continue
                values = {
                    field: row.get(field) if field in row else None for field in fields
                }
                values = {
                    field: None if pd.isna(value) else value
                    for field, value in values.items()
                }
                db.add(
                    FinancialTBRecord(
                        uploaded_file_id=uploaded_file.id,
                        user_id=user_id,
                        period_month=period_month,
                        period_year=period_year,
                        row_index=row_index,
                        **values,
                    )
                )

            db.flush()
            uploaded_file.status = "processed"
            uploaded_file.processed_at = datetime.datetime.utcnow()
            if file_type == "tb_current":
                new_current_tb_processed = True

        db.commit()

        # Trigger background forecasting model retraining ONLY if a new valid current-year tb_current file was processed
        if new_current_tb_processed:
            try:
                from app.services.revenue_forecasting_trainer import trigger_background_retraining
                trigger_background_retraining()
                logger.info(f"Triggered automatic model retraining for new current-year TB file (session={session_id})")
            except Exception as e:
                logger.warning(f"Could not trigger background model retraining: {e}")

            try:
                from app.services.anomaly_detection_service import trigger_background_anomaly_analysis
                trigger_background_anomaly_analysis()
                logger.info(f"Triggered automatic anomaly detection for new current-year TB file (session={session_id})")
            except Exception as e:
                logger.warning(f"Could not trigger background anomaly analysis: {e}")
    except Exception:
        db.rollback()
        logger.exception(f"Failed to persist TB data for session {session_id}")
        raise


def _db_save_job(session_id: str, status: str, result: dict | None = None):
    """Upsert a report job row in the database (visible to all workers)."""
    db = SessionLocal()
    try:
        row = db.query(ReportJob).filter(ReportJob.session_id == session_id).first()
        if row:
            row.status = status
            row.result_json = json.dumps(result) if result is not None else None
        else:
            row = ReportJob(
                session_id=session_id,
                status=status,
                result_json=json.dumps(result) if result is not None else None,
            )
            db.add(row)
        db.commit()
    except Exception as exc:
        logger.warning(f"Could not persist job to DB for {session_id}: {exc}")
    finally:
        db.close()


def _db_load_job(session_id: str) -> dict | None:
    """Load a report job row from the database. Returns None if not found."""
    db = SessionLocal()
    try:
        row = db.query(ReportJob).filter(ReportJob.session_id == session_id).first()
        if row and row.result_json:
            return json.loads(row.result_json)
        if row and row.status == "processing":
            return {"status": "processing", "message": "Report generation in progress."}
        return None
    except Exception as exc:
        logger.warning(f"Could not load job from DB for {session_id}: {exc}")
        return None
    finally:
        db.close()


DEFAULT_FILES_DIR = settings.TEMPLATE_DIR / "defaults"
DEFAULT_FILES_DIR.mkdir(parents=True, exist_ok=True)


def _default_file_path(file_type: str) -> Path:
    if file_type not in {"budget", "mapping"}:
        raise HTTPException(status_code=400, detail="file_type must be 'budget' or 'mapping'.")
    matches = sorted(DEFAULT_FILES_DIR.glob(f"default_{file_type}.*"))
    return matches[-1] if matches else DEFAULT_FILES_DIR / f"default_{file_type}.xlsx"


def _default_file_info(file_type: str) -> dict:
    path = _default_file_path(file_type)
    return {
        f"default_{file_type}_active": path.exists(),
        f"default_{file_type}_filename": path.name if path.exists() else None,
    }


def _restore_session_files(session_id: str) -> dict | None:
    session_dir = settings.UPLOAD_DIR / session_id
    if not session_dir.exists() or not session_dir.is_dir():
        return None

    file_paths = {}
    for label in ["tb_current", "tb_previous", "budget", "mapping"]:
        matches = sorted(session_dir.glob(f"{label}__*"))
        if matches:
            file_paths[label] = str(matches[-1])

    for label in ["budget", "mapping"]:
        if label not in file_paths:
            default_path = _default_file_path(label)
            if default_path.exists():
                file_paths[label] = str(default_path)

    if "tb_current" not in file_paths or "tb_previous" not in file_paths:
        return None

    uploaded_files_store[session_id] = file_paths
    logger.info(f"Restored upload session {session_id} from disk")
    return file_paths


def _get_session_files(session_id: str) -> dict | None:
    return uploaded_files_store.get(session_id) or _restore_session_files(session_id)


def _validate_complete_session(session_id: str) -> dict:
    file_paths = _get_session_files(session_id)
    if not file_paths:
        raise HTTPException(
            status_code=400,
            detail=(
                "Upload session expired or files are not available on this server. "
                "Please upload the files again and generate the report."
            ),
        )

    missing_labels = [
        label
        for label in ["tb_current", "tb_previous", "budget", "mapping"]
        if label not in file_paths or not Path(file_paths[label]).exists()
    ]
    if missing_labels:
        raise HTTPException(
            status_code=400,
            detail=(
                "Upload session is incomplete. Missing files: "
                f"{', '.join(missing_labels)}. Please upload the files again."
            ),
        )

    return file_paths


def _build_report_for_session(
    session_id: str,
    db: Session,
    user_id: int,
    user_name: str,
) -> ReportResponse:
    start_time = time.time()
    file_paths = _validate_complete_session(session_id)
    logger.info(f"Starting report generation for session {session_id}")

    report_month, report_year = detect_tb_month_and_year(file_paths["tb_current"])
    if not report_month or not report_year:
        raise HTTPException(
            status_code=400,
            detail="Could not detect month and year from Trial Balance filename. "
            "Please ensure the filename contains a month abbreviation and year.",
        )
    previous_report_month, previous_report_year = detect_tb_month_and_year(
        file_paths["tb_previous"]
    )
    logger.info(f"Report period: {report_month} {report_year}")

    logger.info("Loading mapping rules...")
    mapping_engine = MappingEngine()
    mapping_engine.load_mapping(file_paths["mapping"])

    logger.info("Reading current year Trial Balance...")
    cy_tb_df = read_current_year_tb(file_paths["tb_current"])
    if cy_tb_df.empty:
        raise HTTPException(
            status_code=400,
            detail="Current Year Trial Balance contains no valid data rows.",
        )

    logger.info("Mapping current year TB rows...")
    cy_tb_df = mapping_engine.map_tb_rows(cy_tb_df)
    mapped_count = (cy_tb_df["revenue_category"] != "").sum()
    unmapped_count = (cy_tb_df["revenue_category"] == "").sum()
    cy_unmapped_df = mapping_engine.get_unmapped_report()
    logger.info(f"CY TB: {mapped_count} mapped, {unmapped_count} unmapped")

    logger.info("Reading previous year Trial Balance...")
    py_tb_df = read_previous_year_tb(file_paths["tb_previous"])
    if py_tb_df.empty:
        logger.warning("Previous Year TB is empty, proceeding without PY data")
        import pandas as pd

        py_tb_df = pd.DataFrame(columns=cy_tb_df.columns)

    logger.info("Mapping previous year TB rows...")
    py_tb_df = mapping_engine.map_tb_rows(py_tb_df)
    py_unmapped_df = mapping_engine.get_unmapped_report()

    _persist_tb_data(
        db=db,
        session_id=session_id,
        user_id=user_id,
        current_report_month=report_month,
        current_report_year=report_year,
        previous_report_month=previous_report_month,
        previous_report_year=previous_report_year,
        file_paths=file_paths,
        current_tb_df=cy_tb_df,
        previous_tb_df=py_tb_df,
    )

    file_paths["cy_unmapped_df"] = cy_unmapped_df
    file_paths["py_unmapped_df"] = py_unmapped_df
    file_paths["report_month"] = report_month
    file_paths["report_year"] = report_year

    session_dir = settings.UPLOAD_DIR / session_id
    if session_dir.exists():
        try:
            cy_unmapped_df.to_csv(session_dir / "cy_unmapped.csv", index=False)
            py_unmapped_df.to_csv(session_dir / "py_unmapped.csv", index=False)
            (session_dir / "report_meta.json").write_text(
                json.dumps({"report_month": report_month, "report_year": report_year}),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Failed to persist unmapped DataFrames to disk: {e}")

    logger.info("Processing current year TB data...")
    cy_tb_data = process_trial_balance(cy_tb_df)

    logger.info("Processing previous year TB data...")
    py_tb_data = process_trial_balance(py_tb_df)

    logger.info("Loading budget data...")
    budget_proc = BudgetProcessor()
    budget_proc.load_budget(file_paths["budget"], report_month, report_year)

    logger.info("Calculating revenue...")
    revenue_results = calculate_revenue(cy_tb_data, py_tb_data, budget_proc)

    logger.info("Generating PowerPoint presentation...")
    ppt_path = generate_pptx(
        revenue_results,
        report_month,
        report_year,
        str(settings.OUTPUT_DIR),
    )

    elapsed = round(time.time() - start_time, 2)
    filename = Path(ppt_path).name

    logger.info(f"Report generated successfully in {elapsed}s: {filename}")

    log_audit(
        db=db,
        action="Report Generation",
        module="Finance",
        description=f"Generated PowerPoint report. Filename: {filename}, Month: {report_month}, Year: {report_year}, Mapped: {mapped_count}, Unmapped: {unmapped_count}",
        user_id=user_id,
        user_name=user_name,
    )

    # Compute Mapped vs Unmapped revenue totals for Revenue Summary Table
    divisor = getattr(settings, "TB_TO_MN_DIVISOR", 1_000_000)
    mapped_mask = (cy_tb_df["revenue_category"] != "") & (cy_tb_df["revenue_category"].notna())
    unmapped_mask = ~mapped_mask

    mapped_month = float(-cy_tb_df[mapped_mask]["period_activity"].sum() / divisor) if mapped_mask.any() else 0.0
    mapped_ytd = float(-cy_tb_df[mapped_mask]["ending_balance"].sum() / divisor) if mapped_mask.any() else 0.0

    unmapped_month = float(-cy_tb_df[unmapped_mask]["period_activity"].sum() / divisor) if unmapped_mask.any() else 0.0
    unmapped_ytd = float(-cy_tb_df[unmapped_mask]["ending_balance"].sum() / divisor) if unmapped_mask.any() else 0.0

    # Retrieve PL Revenue reference from database for this specific period (strictly matching period)
    pl_record = (
        db.query(PLRevenueRecord)
        .filter(
            PLRevenueRecord.period_month.ilike(f"%{report_month[:3]}%"),
            PLRevenueRecord.period_year == int(report_year),
        )
        .order_by(PLRevenueRecord.id.desc())
        .first()
    )

    pl_month_rev = pl_record.month_revenue if pl_record else None
    pl_ytd_rev = pl_record.ytd_revenue if pl_record else None

    rev_summary = RevenueSummary(
        period_month=report_month,
        period_year=int(report_year),
        mapped_month=round(mapped_month, 2),
        mapped_ytd=round(mapped_ytd, 2),
        unmapped_month=round(unmapped_month, 2),
        unmapped_ytd=round(unmapped_ytd, 2),
        pl_month_revenue=pl_month_rev,
        pl_ytd_revenue=pl_ytd_rev,
    )

    return ReportResponse(
        status="success",
        filename=filename,
        unmapped_count=unmapped_count,
        total_mapped=mapped_count,
        processing_time_seconds=elapsed,
        report_month=report_month,
        report_year=report_year,
        message=f"Report generated for {report_month} {report_year}. "
        f"{mapped_count} records mapped, {unmapped_count} unmapped.",
        revenue_summary=rev_summary,
    )


def _run_report_job(session_id: str, user_id: int, user_name: str):
    db = SessionLocal()
    try:
        result = _build_report_for_session(session_id, db, user_id, user_name)
        job_data = result.model_dump()
        report_jobs[session_id] = job_data
        # Persist to DB so other workers can read the full result
        _db_save_job(session_id, "success", job_data)
    except HTTPException as e:
        detail = e.detail
        if isinstance(detail, dict) and "errors" in detail:
            message = ", ".join(detail["errors"])
        else:
            message = str(detail)
        logger.error(f"Report job failed for session {session_id}: {message}")
        error_data = {"status": "error", "message": message}
        report_jobs[session_id] = error_data
        _db_save_job(session_id, "error", error_data)
    except Exception as e:
        logger.exception(f"Report job failed for session {session_id}: {e}")
        error_data = {
            "status": "error",
            "message": f"Report generation failed: {str(e)}",
        }
        report_jobs[session_id] = error_data
        _db_save_job(session_id, "error", error_data)
    finally:
        db.close()


@router.post("/upload")
async def upload_files(
    request: Request,
    tb_current: UploadFile = File(...),
    tb_previous: UploadFile = File(...),
    budget: UploadFile | None = File(None),
    mapping: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    logger.info(f"User {current_user.email} is uploading files")

    session_id = str(uuid.uuid4())[:8]
    session_dir = settings.UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    file_paths = {}
    files = {
        "tb_current": tb_current,
        "tb_previous": tb_previous,
    }
    if budget is not None:
        files["budget"] = budget
    if mapping is not None:
        files["mapping"] = mapping

    for label, upload_file in files.items():
        ext = Path(upload_file.filename).suffix.lower()

    # Allow TXT only for Trial Balance files
        if label in ["tb_current", "tb_previous"]:
            allowed_extensions = {".xlsx", ".xls", ".txt"}
        else:
            allowed_extensions = {".xlsx", ".xls"}

        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type for {label}: {ext}. Allowed: {', '.join(sorted(allowed_extensions))}",
        )

        save_path = session_dir / f"{label}__{upload_file.filename}"

        with open(save_path, "wb") as f:
            content = await upload_file.read()
            f.write(content)

        file_paths[label] = str(save_path)
        logger.info(f"Saved {label}: {upload_file.filename} -> {save_path}")

    for label in ["budget", "mapping"]:
        if label not in file_paths:
            default_path = _default_file_path(label)
            if default_path.exists():
                file_paths[label] = str(default_path)
                logger.info(f"Using default {label} workbook: {default_path}")

    validation = validate_uploaded_files(
        file_paths.get("tb_current"),
        file_paths.get("tb_previous"),
        file_paths.get("budget"),
        file_paths.get("mapping"),
    )

    if not validation.is_valid:
        raise HTTPException(status_code=400, detail={"errors": validation.errors})

    tb_val = validate_trial_balance(file_paths["tb_current"], "Current Year")
    if not tb_val.is_valid:
        raise HTTPException(status_code=400, detail={"errors": tb_val.errors})

    py_val = validate_trial_balance(file_paths["tb_previous"], "Previous Year")
    if not py_val.is_valid:
        raise HTTPException(status_code=400, detail={"errors": py_val.errors})

    bud_val = validate_budget_workbook(file_paths["budget"])
    if not bud_val.is_valid:
        raise HTTPException(status_code=400, detail={"errors": bud_val.errors})

    map_val = validate_mapping_workbook(file_paths["mapping"])
    if not map_val.is_valid:
        raise HTTPException(status_code=400, detail={"errors": map_val.errors})

    uploaded_files_store[session_id] = file_paths

    log_audit(
        db=db,
        action="File Upload",
        module="Finance",
        description=f"Uploaded files for processing. Session ID: {session_id}, Files: TB Current={tb_current.filename}, TB Previous={tb_previous.filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request
    )

    return {
        "status": "success",
        "session_id": session_id,
        "files": {
            "tb_current": tb_current.filename,
            "tb_previous": tb_previous.filename,
            "budget": budget.filename if budget else Path(file_paths["budget"]).name,
            "mapping": mapping.filename if mapping else Path(file_paths["mapping"]).name,
        },
        "warnings": validation.warnings,
    }


@router.post("/upload-pl")
async def upload_pl_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    logger.info(f"User {current_user.email} is uploading PL workbook: {file.filename}")
    ext = Path(file.filename).suffix.lower()
    if ext not in {".xlsx", ".xls"}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type for PL workbook: {ext}. Allowed: .xlsx, .xls",
        )

    pl_dir = settings.UPLOAD_DIR / "pl"
    pl_dir.mkdir(parents=True, exist_ok=True)

    session_id = str(uuid.uuid4())[:8]
    temp_save_path = pl_dir / f"temp_{session_id}_{file.filename}"

    content = await file.read()
    with open(temp_save_path, "wb") as f:
        f.write(content)

    # Validate and parse PL workbook dynamically
    try:
        pl_data = read_pl_workbook(temp_save_path)
    except Exception as e:
        if temp_save_path.exists():
            temp_save_path.unlink(missing_ok=True)
        logger.error(f"PL workbook parsing failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid PL Excel Workbook structure: {str(e)}",
        )

    file_hash = _sha256_file(temp_save_path)
    final_filename = f"pl_{pl_data['month']}_{pl_data['year']}_{file.filename}"
    final_save_path = pl_dir / final_filename

    shutil.move(str(temp_save_path), str(final_save_path))

    # Record in UploadedFinanceFile
    uploaded_file = (
        db.query(UploadedFinanceFile)
        .filter(UploadedFinanceFile.file_hash == file_hash)
        .first()
    )
    if uploaded_file is None:
        uploaded_file = UploadedFinanceFile(
            session_id=session_id,
            user_id=current_user.id,
            file_type="pl_revenue",
            original_filename=file.filename,
            file_hash=file_hash,
            period_month=pl_data["month"],
            period_year=pl_data["year"],
            file_size=final_save_path.stat().st_size if final_save_path.exists() else None,
            status="processed",
            processed_at=datetime.datetime.utcnow(),
        )
        db.add(uploaded_file)
        db.flush()

    # Upsert into PLRevenueRecord
    pl_record = (
        db.query(PLRevenueRecord)
        .filter(
            PLRevenueRecord.period_month == pl_data["month"],
            PLRevenueRecord.period_year == pl_data["year"],
        )
        .first()
    )
    if not pl_record:
        pl_record = PLRevenueRecord(
            uploaded_file_id=uploaded_file.id if uploaded_file else None,
            user_id=current_user.id,
            period_month=pl_data["month"],
            period_year=pl_data["year"],
            month_revenue=pl_data["month_revenue"],
            ytd_revenue=pl_data["ytd_revenue"],
            source_filename=file.filename,
        )
        db.add(pl_record)
    else:
        if uploaded_file:
            pl_record.uploaded_file_id = uploaded_file.id
        pl_record.user_id = current_user.id
        pl_record.month_revenue = pl_data["month_revenue"]
        pl_record.ytd_revenue = pl_data["ytd_revenue"]
        pl_record.source_filename = file.filename
        pl_record.created_at = datetime.datetime.utcnow()

    db.commit()

    log_audit(
        db=db,
        action="PL File Upload",
        module="Finance",
        description=f"Uploaded PL workbook: {file.filename}, Period: {pl_data['month']} {pl_data['year']}, Month Revenue: {pl_data['month_revenue']:,.2f}, YTD Revenue: {pl_data['ytd_revenue']:,.2f}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request,
    )

    return {
        "status": "success",
        "filename": file.filename,
        "period_month": pl_data["month"],
        "period_year": pl_data["year"],
        "month_revenue": pl_data["month_revenue"],
        "ytd_revenue": pl_data["ytd_revenue"],
        "message": f"PL workbook for {pl_data['month']} {pl_data['year']} successfully uploaded and verified.",
    }


@router.get("/pl-revenue")
async def get_pl_revenue(
    period_month: str | None = Query(None),
    period_year: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(PLRevenueRecord)
    if period_month:
        query = query.filter(PLRevenueRecord.period_month.ilike(f"%{period_month[:3]}%"))
    if period_year:
        query = query.filter(PLRevenueRecord.period_year == int(period_year))

    if period_month or period_year:
        record = query.order_by(PLRevenueRecord.id.desc()).first()
    else:
        # Default on initial dashboard load with no active report: return latest uploaded PL
        record = db.query(PLRevenueRecord).order_by(PLRevenueRecord.id.desc()).first()

    if not record:
        return {
            "status": "not_found",
            "data": None,
            "message": "No PL revenue record found for the requested period.",
        }

    return {
        "status": "success",
        "data": {
            "period_month": record.period_month,
            "period_year": record.period_year,
            "month_revenue": record.month_revenue,
            "ytd_revenue": record.ytd_revenue,
            "source_filename": record.source_filename,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        },
    }


@router.get("/admin/config")
async def get_admin_config(current_user: User = Depends(get_current_active_user)):
    return {
        **_default_file_info("budget"),
        **_default_file_info("mapping"),
    }


@router.post("/admin/upload-default")
async def upload_default_file(
    request: Request,
    file_type: str = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    if file_type not in {"budget", "mapping"}:
        raise HTTPException(status_code=400, detail="file_type must be 'budget' or 'mapping'.")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Default files must be Excel workbooks.")

    target_path = DEFAULT_FILES_DIR / f"default_{file_type}{ext}"
    for old_path in DEFAULT_FILES_DIR.glob(f"default_{file_type}.*"):
        old_path.unlink(missing_ok=True)

    with open(target_path, "wb") as f:
        content = await file.read()
        f.write(content)

    validation = (
        validate_budget_workbook(str(target_path))
        if file_type == "budget"
        else validate_mapping_workbook(str(target_path))
    )
    if not validation.is_valid:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail={"errors": validation.errors})

    log_audit(
        db=db,
        action="Default File Upload",
        module="Finance Admin",
        description=f"Uploaded default {file_type} workbook: {file.filename}",
        user_id=admin.id,
        user_name=admin.full_name,
        request=request,
    )

    return {
        "status": "success",
        "file_type": file_type,
        "filename": target_path.name,
        "warnings": validation.warnings,
    }


@router.post("/generate")
async def generate_report(
    background_tasks: BackgroundTasks,
    session_id: str = "",
    current_user: User = Depends(get_current_active_user)
):
    if not session_id:
        raise HTTPException(
            status_code=400, detail="Invalid or missing session_id. Upload files first."
        )

    _validate_complete_session(session_id)
    existing_job = report_jobs.get(session_id)
    if existing_job:
        return existing_job

    # Mark as processing in DB (visible to other workers) and launch background task
    _db_save_job(session_id, "processing")
    report_jobs[session_id] = {
        "status": "processing",
        "message": "Report generation started.",
    }
    background_tasks.add_task(
        _run_report_job,
        session_id,
        current_user.id,
        current_user.full_name,
    )

    return report_jobs[session_id]


@router.get("/report-status/{session_id}")
async def get_report_status(
    session_id: str,
    current_user: User = Depends(get_current_active_user)
):
    # 1. Check in-memory (same worker — fastest path)
    job = report_jobs.get(session_id)
    if job and job.get("status") in ("success", "error"):
        return job

    # 2. Query the database (works across all workers and restarts)
    db_result = _db_load_job(session_id)
    if db_result:
        if db_result.get("status") in ("success", "error"):
            # Cache in this worker's memory for future polls
            report_jobs[session_id] = db_result
        return db_result

    # 3. If in-memory shows "processing" but DB has nothing yet, keep polling
    if job:
        return job

    # 4. Truly unknown session — tell client to keep waiting (do NOT return fake success)
    return {"status": "processing", "message": "Waiting for report generation to start."}


@router.get("/download/{filename}")
async def download_report(
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    file_path = settings.OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file not found.")

    log_audit(
        db=db,
        action="Download Report",
        module="Finance",
        description=f"Downloaded report PowerPoint file: {filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request
    )

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


def _get_or_compute_unmapped_dfs(session_id: str, file_paths: dict):
    import pandas as pd
    session_dir = settings.UPLOAD_DIR / session_id
    cy_unmapped = file_paths.get("cy_unmapped_df")
    py_unmapped = file_paths.get("py_unmapped_df")
    report_month = file_paths.get("report_month", "")
    report_year = file_paths.get("report_year", "")

    meta_file = session_dir / "report_meta.json"
    cy_csv = session_dir / "cy_unmapped.csv"
    py_csv = session_dir / "py_unmapped.csv"

    if (cy_unmapped is None or py_unmapped is None) and cy_csv.exists() and py_csv.exists():
        try:
            cy_unmapped = pd.read_csv(cy_csv).fillna("")
            py_unmapped = pd.read_csv(py_csv).fillna("")
            file_paths["cy_unmapped_df"] = cy_unmapped
            file_paths["py_unmapped_df"] = py_unmapped
        except Exception as e:
            logger.warning(f"Error loading unmapped CSVs for session {session_id}: {e}")

    if (not report_month or not report_year) and meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            report_month = meta.get("report_month", "")
            report_year = meta.get("report_year", "")
            file_paths["report_month"] = report_month
            file_paths["report_year"] = report_year
        except Exception:
            pass

    if cy_unmapped is None or py_unmapped is None or not report_month or not report_year:
        logger.info(f"Re-generating unmapped DataFrames on the fly for session {session_id}")
        tb_current_path = file_paths.get("tb_current")
        tb_previous_path = file_paths.get("tb_previous")
        mapping_path = file_paths.get("mapping")

        if not tb_current_path or not tb_previous_path:
            return None, None, "", ""

        report_month, report_year = detect_tb_month_and_year(tb_current_path)

        mapping_engine = MappingEngine()
        if mapping_path and os.path.exists(mapping_path):
            mapping_engine.load_mapping(mapping_path)

        cy_tb_df = read_current_year_tb(tb_current_path)
        if not cy_tb_df.empty:
            cy_tb_df = mapping_engine.map_tb_rows(cy_tb_df)
            cy_unmapped = mapping_engine.get_unmapped_report()
        else:
            cy_unmapped = pd.DataFrame()

        py_tb_df = read_previous_year_tb(tb_previous_path)
        if not py_tb_df.empty:
            py_tb_df = mapping_engine.map_tb_rows(py_tb_df)
            py_unmapped = mapping_engine.get_unmapped_report()
        else:
            py_unmapped = pd.DataFrame()

        file_paths["cy_unmapped_df"] = cy_unmapped
        file_paths["py_unmapped_df"] = py_unmapped
        file_paths["report_month"] = report_month
        file_paths["report_year"] = report_year

        if session_dir.exists():
            try:
                cy_unmapped.to_csv(cy_csv, index=False)
                py_unmapped.to_csv(py_csv, index=False)
                meta_file.write_text(json.dumps({"report_month": report_month, "report_year": report_year}), encoding="utf-8")
            except Exception:
                pass

    return cy_unmapped, py_unmapped, report_month, report_year


_FLEXFIELD_9SEG_REGEX = re.compile(
    r"\b(\d{2}\.\d{1,5}\.\d{1,4}\.\d{1,4}\.\d{1,5}\.\d{5,7}\.\d{1,4}\.\d{1,4}\.\d{1,5})\b"
)


def _is_valid_9_segment_flexfield(val) -> bool:
    if not val or not isinstance(val, str):
        return False
    parts = val.strip().split(".")
    return len(parts) == 9 and all(p.strip().isdigit() for p in parts)


def _resolve_row_segments(r: dict) -> dict:
    raw_flex = str(r.get("flexfield") or "").strip()
    raw_desc = str(r.get("description") or "").strip()

    flex_str = None
    # Priority 1: First use existing flexfield if valid 9-segment
    if _is_valid_9_segment_flexfield(raw_flex):
        flex_str = raw_flex
    else:
        # Priority 2: Extract valid 9-segment flexfield from Description if present
        m = _FLEXFIELD_9SEG_REGEX.search(raw_desc)
        if m:
            flex_str = m.group(1)

    clean_desc = raw_desc
    if flex_str:
        if flex_str in clean_desc:
            clean_desc = clean_desc.replace(flex_str, "").strip().rstrip(" -_.")
        segs = flex_str.split(".")
        cost_center = segs[1].zfill(4)
        location = segs[2]
        business_line = segs[3]
        product = segs[4]
        account = segs[5]
        technology = segs[6]
        intercompany = segs[7]
        project = segs[8]
    else:
        cc = str(r.get("cost_center") or "").strip()
        cost_center = cc.zfill(4) if (cc and cc.isdigit()) else cc
        location = str(r.get("location") or "").strip()
        business_line = str(r.get("business_line") or "").strip()
        product = str(r.get("product") or "").strip()
        account = str(r.get("account") or "").strip()
        technology = str(r.get("technology") or "").strip()
        intercompany = str(r.get("intercompany") or "").strip()
        project = str(r.get("project") or "").strip()
        flex_str = raw_flex

    gl_code = str(r.get("gl_code") or "").strip()
    if (not gl_code or gl_code in ["0", "nan"]) and account:
        gl_code = account

    return {
        "gl_code": gl_code,
        "description": clean_desc,
        "flexfield": flex_str,
        "cost_center": cost_center,
        "location": location,
        "business_line": business_line,
        "product": product,
        "account": account,
        "technology": technology,
        "intercompany": intercompany,
        "project": project,
    }


def _write_summary_and_detail_sheets(
    writer, cy_unmapped, py_unmapped, report_month, report_year
):
    import pandas as pd
    import re as _re
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    cy_count = len(cy_unmapped) if not cy_unmapped.empty else 0
    py_count = len(py_unmapped) if not py_unmapped.empty else 0

    def _num(df, col):
        return pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0)

    def _fmt_pa(val):
        if val == 0:
            return "0"
        sign = "+" if val > 0 else ""
        return f"{sign}{val:,.0f}"

    def _categorize_reason(reason, account=None):
        if reason.startswith("International filter:"):
            m = _re.search(r"BL (\d+)", reason)
            bl = m.group(1) if m else "?"
            # Only genuine core international service accounts belong to International BL Filter
            # Standard genuine international accounts: 412101, 412201, 412801, 413122, 415101
            # If a row was rejected by the International catch-all because its Business Line is
            # not an International BL and it does not match another specific unmapped issue category,
            # it should remain in the general Other unmapped category.
            intl_genuine_accounts = {"412101", "412201", "412801", "413122", "415101"}
            acct_str = str(account or "").strip()
            if acct_str in intl_genuine_accounts:
                return "International BL Filter", bl, reason
            else:
                return "Other", bl, reason
        if reason.startswith("Equipment Sales filter:"):
            m = _re.search(r"Account (\d+)", reason)
            acct = m.group(1) if m else "?"
            return "Equipment Sales Cleanup", acct, reason
        if reason.startswith("GL ") and "not covered" in reason:
            m = _re.search(r"GL (\d+)", reason)
            acct = m.group(1) if m else "?"
            return "GL Account Not Covered", acct, reason
        if "Product" in reason and "outside" in reason:
            m = _re.search(r"Product (\d+).*GL (\d+)", reason)
            key = f"P{m.group(1)}_GL{m.group(2)}" if m else reason[:30]
            return "Product Range Gap", key, reason
        if "BL" in reason and "outside" in reason:
            m = _re.search(r"BL (\d+)", reason)
            bl = m.group(1) if m else "?"
            return "BL Range Gap", bl, reason
        return "Other", reason[:40], reason

    def _get_category_info(issue_name: str, issue_key: str, sample_reason: str, sample_row: dict = None):
        gl_code = ""
        product_code = ""
        bl_code = ""
        if sample_row:
            gl_code = str(sample_row.get("gl_code") or "").strip()
            product_code = str(sample_row.get("product") or "").strip()
            bl_code = str(sample_row.get("business_line") or "").strip()

        if not gl_code and issue_key and issue_key.isdigit() and len(issue_key) >= 6:
            gl_code = issue_key

        if issue_name == "GL Account Not Covered":
            gl_str = f"[{gl_code}]" if gl_code else "[GL_Code]"
            desc = "This General Ledger account recorded revenue activity in the Trial Balance but is completely missing from your master mapping rules."
            action = f"Open 'Revenue Mapping Workbook' -> Navigate to 'Code Mapping' sheet -> Append GL Code {gl_str} and assign its appropriate Revenue Category."
            target_seg = "account"
        elif issue_name == "Product Range Gap":
            gl_str = f"[{gl_code}]" if gl_code else "[GL_Code]"
            prod_str = f"[{product_code}]" if product_code else "[Product_Code]"
            desc = f"The GL account is mapped, but Product Segment {prod_str} falls outside the mapped Product Range defined for this account."
            action = f"Open 'Revenue Mapping Workbook' -> Locate GL Code {gl_str} -> Extend the Start/End Product Range to include Product {prod_str}."
            target_seg = "product"
        elif issue_name == "BL Range Gap":
            gl_str = f"[{gl_code}]" if gl_code else "[GL_Code]"
            bl_str = f"[{bl_code}]" if bl_code else "[BL_Code]"
            desc = f"Business Line Segment {bl_str} is not covered under the mapped ranges for this GL account."
            action = f"Open 'Revenue Mapping Workbook' -> Locate GL Code {gl_str} -> Update Business Line range to cover code {bl_str}."
            target_seg = "business_line"
        elif issue_name in ["International BL Filter", "Equipment Sales Cleanup"] or "Filter" in issue_name:
            bl_str = f"[{bl_code}]" if bl_code else "[BL_Code]"
            gl_str = f"[{gl_code}]" if gl_code else "[GL_Code]"
            desc = "The row hit a domain-specific filter rule (e.g., Equipment Sales/International) and was bypassed by standard category logic."
            action = f"Review domain filter rules in 'Revenue Mapping Workbook' -> Confirm if Business Line {bl_str} or Account {gl_str} requires dedicated override classification."
            target_seg = "business_line" if issue_name == "International BL Filter" else "account"
        else:
            desc = "Unmapped combination of GL Account, Product, and Business Line segments in the Code Mapping workbook."
            action = "Open 'Revenue Mapping Workbook' -> Check 'Code Mapping' sheet -> Ensure GL, Product, and Business Line segments cover this row."
            target_seg = "account"

        return {
            "finance_explanation": desc,
            "how_to_fix": action,
            "target_segment": target_seg,
        }

    _DARK_BLUE = "1F3864"
    _MED_BLUE = "2E75B6"
    _LIGHT_BLUE = "D6E4F0"
    _WHITE = "FFFFFF"
    _LIGHT_GRAY = "F2F2F2"
    _RED = "C00000"
    _AMBER_FILL = "FFF2CC"
    _AMBER_TEXT = "7F6000"

    hdr_font = Font(name="Calibri", bold=True, color=_WHITE, size=11)
    hdr_fill = PatternFill(start_color=_MED_BLUE, end_color=_MED_BLUE, fill_type="solid")
    hdr_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    title_font = Font(name="Calibri", bold=True, color=_WHITE, size=14)
    title_fill = PatternFill(start_color=_DARK_BLUE, end_color=_DARK_BLUE, fill_type="solid")

    subtitle_font = Font(name="Calibri", bold=True, color=_DARK_BLUE, size=11)

    total_font = Font(name="Calibri", bold=True, size=11)
    total_fill = PatternFill(start_color=_LIGHT_BLUE, end_color=_LIGHT_BLUE, fill_type="solid")

    data_font = Font(name="Calibri", size=10)
    alt_fill = PatternFill(start_color=_LIGHT_GRAY, end_color=_LIGHT_GRAY, fill_type="solid")

    amber_fill = PatternFill(start_color=_AMBER_FILL, end_color=_AMBER_FILL, fill_type="solid")
    amber_font = Font(name="Calibri", bold=True, color=_AMBER_TEXT, size=10)

    thin_border = Border(
        left=Side(style="thin", color="BFBFBF"),
        right=Side(style="thin", color="BFBFBF"),
        top=Side(style="thin", color="BFBFBF"),
        bottom=Side(style="thin", color="BFBFBF"),
    )

    def _auto_width(ws, min_width=10, max_width=65):
        for col_cells in ws.columns:
            col_letter = get_column_letter(col_cells[0].column)
            lengths = [len(str(cell.value)) for cell in col_cells[:100] if cell.value is not None]
            if lengths:
                w = min(max(max(lengths) + 2, min_width), max_width)
                ws.column_dimensions[col_letter].width = w

    def _style_header_row(ws, row_num, num_cols):
        for c in range(1, num_cols + 1):
            cell = ws.cell(row=row_num, column=c)
            cell.font = hdr_font
            cell.fill = hdr_fill
            cell.alignment = hdr_align
            cell.border = thin_border

    def _style_data_rows(ws, start_row, end_row, num_cols):
        # Limit row styling loop to first 500 rows to prevent gateway timeouts on massive datasets
        max_styled_row = min(end_row, start_row + 500)
        for r in range(start_row, max_styled_row + 1):
            is_alt = (r - start_row) % 2 == 1
            for c in range(1, num_cols + 1):
                cell = ws.cell(row=r, column=c)
                cell.font = data_font
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                if is_alt and cell.fill.fill_type != "solid":
                    cell.fill = alt_fill

    def _style_total_row(ws, row_num, num_cols):
        for c in range(1, num_cols + 1):
            cell = ws.cell(row=row_num, column=c)
            cell.font = total_font
            cell.fill = total_fill
            cell.border = thin_border

    if cy_unmapped.empty and py_unmapped.empty:
        ws = writer.book.create_sheet("SUMMARY")
        ws.append([f"Unmapped Rows Analysis - {report_month} {report_year}"])
        ws.append(["No unmapped rows found."])
        return

    all_parts = []
    if not cy_unmapped.empty:
        cy = cy_unmapped.copy()
        cy["_source"] = "CY"
        all_parts.append(cy)
    if not py_unmapped.empty:
        py = py_unmapped.copy()
        py["_source"] = "PY"
        all_parts.append(py)
    combined = pd.concat(all_parts, ignore_index=True)
    combined["period_activity"] = _num(combined, "period_activity")
    combined["ending_balance"] = _num(combined, "ending_balance")

    def _apply_categorization(row):
        r_dict = row.to_dict() if hasattr(row, "to_dict") else dict(row)
        acct = _resolve_row_segments(r_dict)["account"]
        reason = str(r_dict.get("unmapped_reason") or "")
        return _categorize_reason(reason, acct)

    categorized = combined.apply(_apply_categorization, axis=1)
    combined["_issue_name"] = [c[0] for c in categorized]
    combined["_issue_key"] = [c[1] for c in categorized]
    combined["_issue_reason"] = [c[2] for c in categorized]

    issue_types = (
        combined.groupby("_issue_name")
        .agg(
            CY_PA=("period_activity", "sum"),
            CY_Rows=("_source", lambda x: (x == "CY").sum()),
            PY_Rows=("_source", lambda x: (x == "PY").sum()),
            Sample_Reason=("_issue_reason", "first"),
            Sample_Flexfield=("flexfield", "first"),
            Sample_Desc=("description", "first"),
            Sample_GL=("gl_code", "first"),
            Sample_Product=("product", "first"),
            Sample_BL=("business_line", "first"),
        )
        .reset_index()
    )
    issue_types["abs_CY_PA"] = issue_types["CY_PA"].abs()
    issue_types = issue_types.sort_values("abs_CY_PA", ascending=False).drop(
        columns=["abs_CY_PA"]
    )
    issue_types = issue_types.reset_index(drop=True)
    issue_types.index = issue_types.index + 1
    issue_types.index.name = "Issue #"

    priority_map = {
        "International BL Filter": "HIGH",
        "Equipment Sales Cleanup": "HIGH",
        "GL Account Not Covered": "MEDIUM",
        "Product Range Gap": "MEDIUM",
        "BL Range Gap": "LOW",
        "Other": "LOW",
    }

    # ----------------------------------------------------
    # SUMMARY SHEET GENERATION
    # ----------------------------------------------------
    ws_summary = writer.book.create_sheet("SUMMARY", 0)

    ws_summary.append([f"Unmapped Rows Finance Action Guide - {report_month} {report_year}"])
    ws_summary.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)
    title_cell = ws_summary.cell(row=1, column=1)
    title_cell.font = title_font
    title_cell.fill = title_fill
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws_summary.append([
        f"CY Total Unmapped: {cy_count} rows ({_fmt_pa(combined[combined['_source']=='CY']['period_activity'].sum())} Rs. PA) | "
        f"PY Total Unmapped: {py_count} rows | Follow step-by-step instructions below to update Revenue Mapping Workbook."
    ])
    ws_summary.merge_cells(start_row=2, start_column=1, end_row=2, end_column=9)
    sub_cell = ws_summary.cell(row=2, column=1)
    sub_cell.font = subtitle_font
    sub_cell.alignment = Alignment(horizontal="left", vertical="center")

    ws_summary.append([])

    summary_headers = [
        "Issue #",
        "Unmapped Category",
        "Detail Sheet",
        "CY Rows",
        "CY PA (Rs.)",
        "PY Rows",
        "Finance Description",
        "How to Fix (Workbook Guide)",
        "Priority",
    ]
    ws_summary.append(summary_headers)
    _style_header_row(ws_summary, 4, len(summary_headers))

    total_cy_pa = 0
    total_cy_rows = 0
    total_py_rows = 0
    data_start = 5
    for idx, row in issue_types.iterrows():
        priority = priority_map.get(row["_issue_name"], "LOW")
        sheet_label = f"{idx}. {row['_issue_name']}"
        sample_raw = {
            "gl_code": row.get("Sample_GL", ""),
            "product": row.get("Sample_Product", ""),
            "business_line": row.get("Sample_BL", ""),
            "flexfield": row.get("Sample_Flexfield", ""),
            "description": row.get("Sample_Desc", ""),
        }
        sample_dict = _resolve_row_segments(sample_raw)
        info = _get_category_info(
            row["_issue_name"], row["_issue_name"], row["Sample_Reason"], sample_dict
        )

        ws_summary.append([
            idx,
            row["_issue_name"],
            sheet_label,
            int(row["CY_Rows"]),
            _fmt_pa(row["CY_PA"]),
            int(row["PY_Rows"]),
            info["finance_explanation"],
            info["how_to_fix"],
            priority,
        ])
        
        # Make Detail Sheet name clickable
        link_cell = ws_summary.cell(row=ws_summary.max_row, column=3)
        link_cell.hyperlink = f"#'{sheet_label}'!A1"
        link_cell.style = "Hyperlink"
        
        
        total_cy_pa += row["CY_PA"]
        total_cy_rows += int(row["CY_Rows"])
        total_py_rows += int(row["PY_Rows"])

    data_end = data_start + len(issue_types) - 1
    _style_data_rows(ws_summary, data_start, data_end, len(summary_headers))

    for r in range(data_start, data_end + 1):
        prio_cell = ws_summary.cell(row=r, column=9)
        if prio_cell.value == "HIGH":
            prio_cell.font = Font(name="Calibri", bold=True, color=_RED, size=10)

    ws_summary.append([])
    total_row_num = data_end + 2
    ws_summary.append([
        "TOTAL",
        "",
        "",
        total_cy_rows,
        _fmt_pa(total_cy_pa),
        total_py_rows,
        "",
        "",
        "",
    ])
    _style_total_row(ws_summary, total_row_num, len(summary_headers))

    ws_summary.append([
        f"Current Generated Total Revenue YTD includes these unmapped amounts. "
        f"Total unmapped CY PA: {_fmt_pa(total_cy_pa)} Rs."
    ])
    _auto_width(ws_summary)

    ws_summary.column_dimensions["A"].width = 10
    ws_summary.column_dimensions["B"].width = 28
    ws_summary.column_dimensions["C"].width = 28
    ws_summary.column_dimensions["D"].width = 12
    ws_summary.column_dimensions["E"].width = 18
    ws_summary.column_dimensions["F"].width = 12
    ws_summary.column_dimensions["G"].width = 50
    ws_summary.column_dimensions["H"].width = 65
    ws_summary.column_dimensions["I"].width = 12
    
    # Keep summary header visible while scrolling
    ws_summary.freeze_panes = "A5"

    # ----------------------------------------------------
    # DETAIL SHEETS GENERATION (FAST SINGLE PASS)
    # ----------------------------------------------------
    detail_cols = [
        "Source",
        "GL Code",
        "Description",
        "Flexfield",
        "Cost Center",
        "Location",
        "Business Line",
        "Product",
        "Account",
        "Technology",
        "Intercompany",
        "Project",
        "Beginning Balance",
        "Period Activity",
        "Ending Balance",
        "Suggested Fix / Required Action",
        "Unmapped Reason",
    ]

    align_center = Alignment(vertical="center", wrap_text=True)

    for issue_idx, it_row in issue_types.iterrows():
        issue_name = it_row["_issue_name"]
        type_df = combined[combined["_issue_name"] == issue_name]
        cy_type = type_df[type_df["_source"] == "CY"]
        py_type = type_df[type_df["_source"] == "PY"]
        cy_type_pa = cy_type["period_activity"].sum()
        cy_type_rows = len(cy_type)
        py_type_rows = len(py_type)

        records = type_df.to_dict("records")
        sample_row_dict = _resolve_row_segments(records[0]) if records else {}
        cat_info = _get_category_info(issue_name, issue_name, sample_row_dict.get("unmapped_reason", ""), sample_row_dict)
        target_seg = cat_info["target_segment"]

        sheet_label = f"{issue_idx}. {issue_name}"
        ws = writer.book.create_sheet(sheet_label)

        # Header Callout Banner Block
        ws.append([f"ISSUE RESOLUTION GUIDE: {issue_idx}. {issue_name}"])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=17)
        c1 = ws.cell(row=1, column=1)
        c1.font = title_font
        c1.fill = title_fill
        c1.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 28

        ws.append([f"EXPLANATION: {cat_info['finance_explanation']}"])
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=17)
        c2 = ws.cell(row=2, column=1)
        c2.font = Font(name="Calibri", bold=True, color=_DARK_BLUE, size=10)
        c2.fill = PatternFill(start_color=_LIGHT_BLUE, end_color=_LIGHT_BLUE, fill_type="solid")
        c2.alignment = Alignment(horizontal="left", vertical="center")

        ws.append([f"ACTION REQUIRED: {cat_info['how_to_fix']}"])
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=17)
        c3 = ws.cell(row=3, column=1)
        c3.font = Font(name="Calibri", bold=True, color="7F6000", size=10)
        c3.fill = amber_fill

        ws.append([
            f"IMPACT METRICS: CY Total: {cy_type_rows} rows ({_fmt_pa(cy_type_pa)} Rs. PA) | "
            f"PY Total: {py_type_rows} rows | Amber highlighted segment columns indicate the unmapped criteria."
        ])
        ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=17)
        c4 = ws.cell(row=4, column=1)
        c4.font = Font(name="Calibri", italic=True, size=10)
        c4.fill = alt_fill

        ws.append([])
        ws.append(detail_cols)
        hdr_r = ws.max_row
        ws.auto_filter.ref = ws.dimensions
        for c in range(1, len(detail_cols) + 1):
            cell = ws.cell(row=hdr_r, column=c)
            cell.font = hdr_font
            cell.fill = hdr_fill
            cell.alignment = hdr_align
            cell.border = thin_border
            
            # Keep detail sheet headers visible
        ws.freeze_panes = "A7"
        
        # Enable filters on the header row
        ws.auto_filter.ref = f"A{hdr_r}:Q{hdr_r}"

        # --- fast bulk write: append all data rows first ---
        all_rows = []
        for row_i, r in enumerate(records):
            resolved = _resolve_row_segments(r)
            gl_val = resolved["gl_code"]
            prod_val = resolved["product"]
            bl_val = resolved["business_line"]
            cc_val = resolved["cost_center"]
            tech_val = resolved["technology"]

            if issue_name == "GL Account Not Covered":
                row_fix = f"Open 'Revenue Mapping Workbook' -> 'Code Mapping' sheet -> Add GL Account {gl_val} and assign Revenue Category"
            elif issue_name == "Product Range Gap":
                row_fix = f"Open 'Revenue Mapping Workbook' -> 'Code Mapping' sheet -> Extend Product Range for GL Account {gl_val} to include Product {prod_val}"
            elif issue_name == "BL Range Gap":
                row_fix = f"Open 'Revenue Mapping Workbook' -> 'Code Mapping' sheet -> Update Business Line Range for GL Account {gl_val} to include BL {bl_val}"
            elif issue_name == "International BL Filter":
                row_fix = f"Review International BL rule in 'Revenue Mapping Workbook' for Business Line {bl_val} / Account {gl_val}"
            elif issue_name == "Equipment Sales Cleanup":
                row_fix = f"Review Equipment Sales account rule in 'Revenue Mapping Workbook' for Account {gl_val}"
            else:
                row_fix = f"Open 'Revenue Mapping Workbook' -> 'Code Mapping' sheet -> Update rule for GL {gl_val}, Product {prod_val}, BL {bl_val}"

            reason_val = str(r.get("unmapped_reason") or "").strip()
            if (
                "fewer than 9 segments" in reason_val
                or not reason_val
                or "Product , BL" in reason_val
                or reason_val.endswith("GL ")
                or (issue_name == "Other" and reason_val.startswith("International filter:"))
            ):
                reason_val = f"No rule matches GL {gl_val}, CC {cc_val}, Product {prod_val}, Tech {tech_val}, BL {bl_val}"

            all_rows.append([
                r.get("_source", ""),
                gl_val,
                resolved["description"],
                resolved["flexfield"],
                cc_val,
                resolved["location"],
                bl_val,
                prod_val,
                resolved["account"],
                tech_val,
                resolved["intercompany"],
                resolved["project"],
                _fmt_pa(r.get("beginning_balance", 0)),
                _fmt_pa(r.get("period_activity", 0)),
                _fmt_pa(r.get("ending_balance", 0)),
                row_fix,
                reason_val,
            ])

        data_row_start = hdr_r + 1
        for row_data in all_rows:
            ws.append(row_data)

        data_row_end = ws.max_row

        # Apply base styling to ALL data rows in one pass (cap at 500 for speed)
        _style_data_rows(ws, data_row_start, min(data_row_end, data_row_start + 499), len(detail_cols))

        # Targeted amber highlighting on special columns only (pre-built objects, no per-cell new allocations)
        _amber_fill_obj = amber_fill
        _amber_font_obj = amber_font
        _yellow_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
        amber_cols = []
        if target_seg == "account":
            amber_cols = [2, 9]
        elif target_seg == "product":
            amber_cols = [8]
        elif target_seg == "business_line":
            amber_cols = [7]

        for r_num in range(data_row_start, data_row_end + 1):
            for col_i in amber_cols:
                cell = ws.cell(row=r_num, column=col_i)
                cell.fill = _amber_fill_obj
                cell.font = _amber_font_obj
            # Unmapped Reason column (col 17) always gets yellow fill
            ws.cell(row=r_num, column=17).fill = _yellow_fill



        ws.append([])
        ws.append([
            "TOTAL",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            _fmt_pa(type_df["beginning_balance"].sum() if "beginning_balance" in type_df.columns else 0),
            _fmt_pa(cy_type_pa),
            _fmt_pa(type_df["ending_balance"].sum() if "ending_balance" in type_df.columns else 0),
            "",
            "",
        ])
        tot_r = ws.max_row
        for c in range(1, len(detail_cols) + 1):
            cell = ws.cell(row=tot_r, column=c)
            cell.font = total_font
            cell.fill = total_fill
            cell.border = thin_border

        # Set column dimensions directly
        ws.column_dimensions["A"].width = 10
        ws.column_dimensions["B"].width = 16
        ws.column_dimensions["C"].width = 30
        ws.column_dimensions["D"].width = 40
        ws.column_dimensions["E"].width = 12
        ws.column_dimensions["F"].width = 10
        ws.column_dimensions["G"].width = 14
        ws.column_dimensions["H"].width = 12
        ws.column_dimensions["I"].width = 14
        ws.column_dimensions["J"].width = 12
        ws.column_dimensions["K"].width = 14
        ws.column_dimensions["L"].width = 10
        ws.column_dimensions["M"].width = 18
        ws.column_dimensions["N"].width = 18
        ws.column_dimensions["O"].width = 18
        ws.column_dimensions["P"].width = 75
        ws.column_dimensions["Q"].width = 50

    # Ensure '2. Other' detail sheet is always created even if 0 rows in Other category
    if not any("Other" in s for s in writer.book.sheetnames):
        other_sheet_label = "2. Other"
        ws_other = writer.book.create_sheet(other_sheet_label)

        # Header Callout Banner Block
        ws_other.append(["ISSUE RESOLUTION GUIDE: 2. Other"])
        ws_other.merge_cells(start_row=1, start_column=1, end_row=1, end_column=17)
        c1 = ws_other.cell(row=1, column=1)
        c1.font = title_font
        c1.fill = title_fill
        c1.alignment = Alignment(horizontal="center", vertical="center")
        ws_other.row_dimensions[1].height = 28

        ws_other.append(["EXPLANATION: Unmapped combination of GL Account, Product, and Business Line segments in the Code Mapping workbook."])
        ws_other.merge_cells(start_row=2, start_column=1, end_row=2, end_column=17)
        c2 = ws_other.cell(row=2, column=1)
        c2.font = Font(name="Calibri", bold=True, color=_DARK_BLUE, size=10)
        c2.fill = PatternFill(start_color=_LIGHT_BLUE, end_color=_LIGHT_BLUE, fill_type="solid")
        c2.alignment = Alignment(horizontal="left", vertical="center")

        ws_other.append(["ACTION REQUIRED: Open 'Revenue Mapping Workbook' -> Check 'Code Mapping' sheet -> Ensure GL, Product, and Business Line segments cover this row."])
        ws_other.merge_cells(start_row=3, start_column=1, end_row=3, end_column=17)
        c3 = ws_other.cell(row=3, column=1)
        c3.font = Font(name="Calibri", bold=True, color="7F6000", size=10)
        c3.fill = amber_fill

        ws_other.append([
            "IMPACT METRICS: CY Total: 0 rows (0 Rs. PA) | PY Total: 0 rows | Amber highlighted segment columns indicate the unmapped criteria."
        ])
        ws_other.merge_cells(start_row=4, start_column=1, end_row=4, end_column=17)
        c4 = ws_other.cell(row=4, column=1)
        c4.font = Font(name="Calibri", italic=True, size=10)
        c4.fill = alt_fill

        ws_other.append([])
        ws_other.append(detail_cols)
        hdr_r = ws_other.max_row
        for c in range(1, len(detail_cols) + 1):
            cell = ws_other.cell(row=hdr_r, column=c)
            cell.font = hdr_font
            cell.fill = hdr_fill
            cell.alignment = hdr_align
            cell.border = thin_border

        ws_other.freeze_panes = "A7"
        ws_other.auto_filter.ref = f"A{hdr_r}:Q{hdr_r}"

        # Informative empty state row
        empty_row = [
            "",
            "",
            "No Other unmapped rows found for this reporting period",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "0",
            "0",
            "0",
            "No action required",
            "No unmapped rows in this category",
        ]
        ws_other.append(empty_row)
        msg_r = ws_other.max_row
        _style_data_rows(ws_other, msg_r, msg_r, len(detail_cols))
        ws_other.cell(row=msg_r, column=17).fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")

        ws_other.append([])
        ws_other.append([
            "TOTAL",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "0",
            "0",
            "0",
            "",
            "",
        ])
        tot_r = ws_other.max_row
        for c in range(1, len(detail_cols) + 1):
            cell = ws_other.cell(row=tot_r, column=c)
            cell.font = total_font
            cell.fill = total_fill
            cell.border = thin_border

        ws_other.column_dimensions["A"].width = 10
        ws_other.column_dimensions["B"].width = 16
        ws_other.column_dimensions["C"].width = 30
        ws_other.column_dimensions["D"].width = 40
        ws_other.column_dimensions["E"].width = 12
        ws_other.column_dimensions["F"].width = 10
        ws_other.column_dimensions["G"].width = 14
        ws_other.column_dimensions["H"].width = 12
        ws_other.column_dimensions["I"].width = 14
        ws_other.column_dimensions["J"].width = 12
        ws_other.column_dimensions["K"].width = 14
        ws_other.column_dimensions["L"].width = 10
        ws_other.column_dimensions["M"].width = 18
        ws_other.column_dimensions["N"].width = 18
        ws_other.column_dimensions["O"].width = 18
        ws_other.column_dimensions["P"].width = 75
        ws_other.column_dimensions["Q"].width = 50


def _run_unmapped_job(session_id: str, user_id: int, user_name: str):
    """Background worker: builds the unmapped Excel and stores result in unmapped_jobs."""
    import pandas as pd
    db = SessionLocal()
    try:
        file_paths = _get_session_files(session_id)
        if not file_paths:
            raise ValueError(
                "Upload session expired or files are not available. "
                "Please upload the files and generate the report again."
            )

        cy_unmapped, py_unmapped, report_month, report_year = _get_or_compute_unmapped_dfs(session_id, file_paths)

        if cy_unmapped is None or py_unmapped is None:
            raise ValueError("Unmapped data not available. Please generate the report first.")

        output_filename = f"Unmapped_Rows_{report_month}_{report_year}.xlsx"
        output_path = settings.OUTPUT_DIR / output_filename

        display_cols = [
            "gl_code", "description", "flexfield", "cost_center", "location",
            "business_line", "product", "account", "technology", "intercompany",
            "project", "beginning_balance", "period_activity", "ending_balance",
        ]

        with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
            if not cy_unmapped.empty:
                cy_resolved_rows = []
                for r in cy_unmapped.to_dict("records"):
                    res = _resolve_row_segments(r)
                    for col in ["beginning_balance", "period_activity", "ending_balance"]:
                        res[col] = r.get(col, 0)
                    cy_resolved_rows.append(res)
                cy_export = pd.DataFrame(cy_resolved_rows)
                cy_export = cy_export[[c for c in display_cols if c in cy_export.columns]]
                cy_export.to_excel(writer, sheet_name="CY Unmapped", index=False)
            else:
                pd.DataFrame(columns=display_cols).to_excel(writer, sheet_name="CY Unmapped", index=False)

            if not py_unmapped.empty:
                py_resolved_rows = []
                for r in py_unmapped.to_dict("records"):
                    res = _resolve_row_segments(r)
                    for col in ["beginning_balance", "period_activity", "ending_balance"]:
                        res[col] = r.get(col, 0)
                    py_resolved_rows.append(res)
                py_export = pd.DataFrame(py_resolved_rows)
                py_export = py_export[[c for c in display_cols if c in py_export.columns]]
                py_export.to_excel(writer, sheet_name="PY Unmapped", index=False)
            else:
                pd.DataFrame(columns=display_cols).to_excel(writer, sheet_name="PY Unmapped", index=False)

            _write_summary_and_detail_sheets(writer, cy_unmapped, py_unmapped, report_month, report_year)

        cy_count = len(cy_unmapped) if not cy_unmapped.empty else 0
        py_count = len(py_unmapped) if not py_unmapped.empty else 0
        logger.info(f"Unmapped report generated: {output_filename} (CY: {cy_count}, PY: {py_count})")

        log_audit(
            db=db,
            action="Unmapped Report Generation",
            module="Finance",
            description=f"Generated unmapped rows Excel report. Filename: {output_filename}, Month: {report_month}, Year: {report_year}, CY: {cy_count}, PY: {py_count}",
            user_id=user_id,
            user_name=user_name,
        )

        job_data = {
            "status": "success",
            "filename": output_filename,
            "cy_unmapped_count": cy_count,
            "py_unmapped_count": py_count,
        }
        unmapped_jobs[session_id] = job_data
        _db_save_job(f"unmapped_{session_id}", "success", job_data)

    except Exception as e:
        logger.exception(f"Unmapped job failed for session {session_id}: {e}")
        error_data = {"status": "error", "message": str(e)}
        unmapped_jobs[session_id] = error_data
        _db_save_job(f"unmapped_{session_id}", "error", error_data)
    finally:
        db.close()


@router.post("/generate-unmapped")
async def generate_unmapped_report(
    background_tasks: BackgroundTasks,
    session_id: str = Query(""),
    current_user: User = Depends(get_current_active_user)
):
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid or missing session_id. Generate report first.",
        )

    # Return cached result if already done
    existing = unmapped_jobs.get(session_id)
    if existing and existing.get("status") in ("success", "error"):
        return existing

    # Validate session files exist before enqueuing
    if not _get_session_files(session_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Upload session expired or files are not available on this server. "
                "Please upload the files and generate the report again."
            ),
        )

    # Already in progress?
    if existing and existing.get("status") == "processing":
        return existing

    _db_save_job(f"unmapped_{session_id}", "processing")
    unmapped_jobs[session_id] = {"status": "processing", "message": "Unmapped report generation started."}
    background_tasks.add_task(_run_unmapped_job, session_id, current_user.id, current_user.full_name)

    return unmapped_jobs[session_id]


@router.get("/unmapped-status/{session_id}")
async def get_unmapped_status(
    session_id: str,
    current_user: User = Depends(get_current_active_user)
):
    # Check in-memory first
    job = unmapped_jobs.get(session_id)
    if job and job.get("status") in ("success", "error"):
        return job

    # Fall back to DB (cross-worker)
    db_result = _db_load_job(f"unmapped_{session_id}")
    if db_result:
        if db_result.get("status") in ("success", "error"):
            unmapped_jobs[session_id] = db_result
        return db_result

    if job:
        return job

    return {"status": "processing", "message": "Waiting for unmapped report generation to start."}


@router.get("/download-unmapped/{filename}")
async def download_unmapped_report(
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    file_path = settings.OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Unmapped report file not found.")

    log_audit(
        db=db,
        action="Download Unmapped Rows",
        module="Finance",
        description=f"Downloaded unmapped rows Excel report: {filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request
    )

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/status")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}

