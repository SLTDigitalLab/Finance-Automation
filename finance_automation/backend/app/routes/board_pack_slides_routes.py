"""API for generating the independent two-slide Ratio and Balance Sheet deck."""
import logging
import errno
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
from services.board_pack_slides_generator import generate_board_pack_slides
from services.board_pack_slides_reader import BoardPackSlidesError, read_board_pack_slides_workbook

logger = logging.getLogger(__name__)
board_pack_slides_router = APIRouter(prefix="/api/board-pack-slides", tags=["board-pack-slides"])

_APP_DATA_DIR = Path(
    os.environ.get(
        "LOCALAPPDATA",
        os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")),
    )
)
_DEFAULT_OUTPUT_DIR = _APP_DATA_DIR / "FinanceAutomation" / "outputs" / "board_pack_slides"
OUTPUT_DIR = Path(os.environ.get("FINANCE_BOARD_PACK_SLIDES_OUTPUT_DIR", _DEFAULT_OUTPUT_DIR))
FILENAME_PATTERN = re.compile(
    r"^Finance_Board_Pack_Slides_(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)_"
    r"\d{4}_[0-9a-f]{8}\.pptx$"
)
ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}


def _build(file_path: Path, user_output_dir: Path):
    data = read_board_pack_slides_workbook(str(file_path))
    output_path = generate_board_pack_slides(data, str(user_output_dir))
    return data, Path(output_path)


def _stage_upload(file: UploadFile, ext: str) -> Path:
    """Stage uploads in the system temp directory instead of persistent output storage."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=ext, prefix="board_pack_slides_", delete=False
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
        logger.error("Board-pack slide storage is full: %s", exc)
        return HTTPException(
            status_code=507,
            detail="Server storage is full. Free disk space and try again.",
        )
    return HTTPException(status_code=500, detail=f"Unable to store the uploaded workbook: {exc}")


@board_pack_slides_router.post("/generate")
async def generate_board_pack_slides_report(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case("board_pack")),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload the Ratio and Balance Sheet Excel file (.xlsx or .xlsm).")

    try:
        upload_path = await run_in_threadpool(_stage_upload, file, ext)
    except OSError as exc:
        raise _storage_error(exc) from exc

    user_output_dir = OUTPUT_DIR / str(current_user.id)
    try:
        data, output_path = await run_in_threadpool(_build, upload_path, user_output_dir)
    except BoardPackSlidesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise _storage_error(exc) from exc
        logger.exception("Ratio and Balance Sheet slide storage failed")
        raise HTTPException(status_code=500, detail=f"Failed to save the generated PowerPoint: {exc}") from exc
    except Exception as exc:
        logger.exception("Ratio and Balance Sheet slide generation failed")
        raise HTTPException(status_code=500, detail=f"Failed to generate the two-slide PowerPoint: {exc}") from exc
    finally:
        upload_path.unlink(missing_ok=True)

    log_audit(
        db=db,
        action="Report Generation",
        module="Finance Board Pack Slides",
        description=f"Generated Ratio and Balance Sheet slides for {data.period_month} {data.period_year} from {file.filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request,
    )

    return {
        "status": "success",
        "filename": output_path.name,
        "period": f"{data.period_month} {data.period_year}",
        "source_file": file.filename,
        "sheets_used": data.sheets_used,
        "slide_count": 2,
    }


@board_pack_slides_router.get("/download/{filename}")
async def download_board_pack_slides(
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_use_case("board_pack")),
):
    if not FILENAME_PATTERN.match(filename):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    file_path = OUTPUT_DIR / str(current_user.id) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PowerPoint file not found. Generate it again.")

    log_audit(
        db=db,
        action="Download Report",
        module="Finance Board Pack Slides",
        description=f"Downloaded Ratio and Balance Sheet slides: {filename}",
        user_id=current_user.id,
        user_name=current_user.full_name,
        request=request,
    )
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
