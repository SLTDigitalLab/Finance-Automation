"""Finance Board Pack API Routes"""
import logging
import re
import uuid
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
from services.board_pack_reader import BoardPackError, read_board_pack_workbook

logger = logging.getLogger(__name__)
board_pack_router = APIRouter(prefix="/api/board-pack", tags=["board-pack"])

UPLOAD_DIR = settings.UPLOAD_DIR / "board_pack"
OUTPUT_DIR = settings.OUTPUT_DIR / "board_pack"
FILENAME_PATTERN = re.compile(r"^Finance_Board_Pack_[A-Za-z]+_\d{4}_[0-9a-f]{8}\.pptx$")
ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}


def _build(file_path: Path):
    data = read_board_pack_workbook(str(file_path))
    output_path = generate_board_pack(data, str(OUTPUT_DIR))
    return data, Path(output_path)


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

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.MAX_FILE_SIZE_MB} MB.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    upload_path.write_bytes(content)

    try:
        data, output_path = await run_in_threadpool(_build, upload_path)
    except BoardPackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    file_path = OUTPUT_DIR / filename
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
