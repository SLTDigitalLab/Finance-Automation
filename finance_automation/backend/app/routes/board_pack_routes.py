"""Finance Board Pack API Routes"""
import errno
import logging
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models.user_and_log import User
from app.routes.use_case_routes import require_use_case
from app.services.audit_logger import log_audit
from config import settings
from services.board_pack_generator import generate_board_pack
from services.board_pack_history import load_snapshot, save_snapshot
from services.board_pack_reader import BoardPackError, read_board_pack_workbook

logger = logging.getLogger(__name__)
board_pack_router = APIRouter(prefix="/api/board-pack", tags=["board-pack"])

_APP_DATA_DIR = Path(
    os.environ.get(
        "LOCALAPPDATA",
        os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")),
    )
)
_DEFAULT_OUTPUT_DIR = _APP_DATA_DIR / "FinanceAutomation" / "outputs" / "board_pack"
OUTPUT_DIR = Path(os.environ.get("FINANCE_BOARD_PACK_OUTPUT_DIR", _DEFAULT_OUTPUT_DIR))
LEGACY_OUTPUT_DIR = settings.OUTPUT_DIR / "board_pack"
HISTORY_DIR = OUTPUT_DIR / "history"
FILENAME_PATTERN = re.compile(r"^Finance_Board_Pack_[A-Za-z]+_\d{4}_[0-9a-f]{8}\.pptx$")
ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}


def _build(file_path: Path, user_output_dir: Path):
    user_output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = user_output_dir / "history"
    legacy_history_dir = LEGACY_OUTPUT_DIR / str(user_output_dir.name) / "history"

    def previous_snapshot(period):
        snapshot = load_snapshot(history_dir, period)
        if snapshot is None and history_dir != legacy_history_dir:
            snapshot = load_snapshot(legacy_history_dir, period)
        return snapshot

    data = read_board_pack_workbook(str(file_path), previous_snapshot)
    output_path = generate_board_pack(data, str(user_output_dir))
    save_snapshot(history_dir, data.period, data.snapshot)
    return data, Path(output_path)


def _stage_upload(file: UploadFile, ext: str) -> Path:
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=ext, prefix="board_pack_", delete=False
        ) as staged_file:
            temp_path = Path(staged_file.name)
            total_bytes = 0
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
                    raise HTTPException(
                        status_code=400,
                        detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB.",
                    )
                staged_file.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="The uploaded Excel file is empty.")
        return temp_path
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _storage_error(exc: OSError) -> HTTPException:
    if exc.errno == errno.ENOSPC:
        logger.error("Board-pack storage is full: %s", exc)
        return HTTPException(
            status_code=507,
            detail="Server storage is full. Free disk space and try again.",
        )
    return HTTPException(status_code=500, detail=f"Unable to store the uploaded workbook: {exc}")


@board_pack_router.post("/generate")
async def generate_board_pack_report(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case("board_pack")),
):
    """
    Builds the Finance Board Pack PowerPoint from the monthly Sub workings workbook.

    Uses the first two visible tabs (INCOME Amalg YTD, BD Slides-SLT-Mobtel-Grp)
    plus the SLTSL tab for the SLTS slide.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload the Sub workings Excel file (.xlsx or .xlsm).")

    try:
        upload_path = await run_in_threadpool(_stage_upload, file, ext)
    except OSError as exc:
        raise _storage_error(exc) from exc

    user_out_dir = OUTPUT_DIR / str(current_user.id)
    try:
        data, output_path = await run_in_threadpool(_build, upload_path, user_out_dir)
    except BoardPackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise _storage_error(exc) from exc
        logger.exception("Board pack storage failed")
        raise HTTPException(status_code=500, detail=f"Failed to save the generated board pack: {exc}") from exc
    except Exception as exc:
        logger.exception(f"Board pack generation failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to generate the board pack: {exc}") from exc
    finally:
        upload_path.unlink(missing_ok=True)

    log_audit(
        db=db,
        action="Report Generation",
        module="Finance Board Pack",
        description=f"Generated Finance Board Pack for {data.period.label} from {file.filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request,
    )

    return {
        "status": "success",
        "filename": output_path.name,
        "period": data.period.label,
        "source_file": file.filename,
        "sheets_used": data.sheets_used,
        "slide_count": 9,
        "warnings": data.warnings,
    }


@board_pack_router.get("/download/{filename}")
async def download_board_pack(
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case("board_pack")),
):
    if not FILENAME_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    file_path = (OUTPUT_DIR / str(current_user.id)) / filename
    if not file_path.exists():
        file_path = (LEGACY_OUTPUT_DIR / str(current_user.id)) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Board pack file not found. Generate it again.")

    log_audit(
        db=db,
        action="Download Report",
        module="Finance Board Pack",
        description=f"Downloaded Finance Board Pack: {filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request,
    )

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
