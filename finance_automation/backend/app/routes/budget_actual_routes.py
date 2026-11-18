from io import BytesIO
from pathlib import Path

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.models.user_and_log import User
from app.routes.use_case_routes import require_use_case
from services.budget_actual_variance_service import BudgetActualInputError, generate_budget_actual_report

router = APIRouter(prefix="/api/budget-actual", tags=["budget-actual-variance"])
USE_CASE = "use_case_7"
BASE_DIR = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = BASE_DIR / "files" / "Budget Vs Actuals October 2026.xlsx"
EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def read_excel(file: UploadFile, label: str) -> bytes:
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=400, detail=f"{label} must be an .xlsx or .xlsm workbook.")
    content = await file.read()
    try:
        openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True).close()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{label} is not a readable Excel workbook.") from exc
    return content


@router.post("/generate")
async def generate(
    budget: UploadFile = File(...),
    actual: UploadFile = File(...),
    mapping: UploadFile = File(...),
    current_user: User = Depends(require_use_case(USE_CASE)),
):
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail="The Budget vs Actual reference template is unavailable.")
    budget_content = await read_excel(budget, "Budget")
    actual_content = await read_excel(actual, "Actual")
    mapping_content = await read_excel(mapping, "Mapping")
    try:
        report, metrics = generate_budget_actual_report(
            TEMPLATE_PATH, budget_content, actual_content, mapping_content
        )
    except BudgetActualInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}") from exc
    filename = f"Budget_Vs_Actual_Variance_{metrics['year']}_{metrics['month']:02d}.xlsx"
    return StreamingResponse(
        BytesIO(report),
        media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
