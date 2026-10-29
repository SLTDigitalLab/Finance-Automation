"""
Stores FA budget workbooks and parsed figures per period on disk.
Multiple month-wise budget files can be uploaded and stored simultaneously.
Uploading a budget for an existing period replaces that period's data.
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from services.financial_analysis.budget_reader import (
    BudgetFormatError,
    FABudget,
    read_fa_budget,
)
from services.financial_analysis.periods import Period
from utils.logger import logger


def _meta_filename(period: Period) -> str:
    return f"budget_{period.year}_{period.month:02d}.json"


def _xlsx_filename(period: Period) -> str:
    return f"budget_{period.year}_{period.month:02d}.xlsx"


def save_budget_file(
    store_dir: Path,
    upload_path: Path,
    original_filename: str,
    user_name: Optional[str] = None,
    ytd_cumulate: bool = False,
) -> List[Dict]:
    """
    Validates the workbook at `upload_path` and stores it by period.
    Returns a list of status dictionaries for each period stored.
    """
    budget = read_fa_budget(upload_path, ytd_cumulate=ytd_cumulate)
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict] = []

    # Case 1: Specific month-end period detected (e.g. YTD June 26.xlsx)
    if budget.period:
        period = budget.period
        json_path = store_dir / _meta_filename(period)
        xlsx_path = store_dir / _xlsx_filename(period)
        existed = json_path.exists()

        if upload_path.resolve() != xlsx_path.resolve():
            shutil.copy2(upload_path, xlsx_path)
        meta = {
            "year": period.year,
            "month": period.month,
            "label": period.label,
            "filename": original_filename,
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "uploaded_by": user_name,
            "lines_count": len(budget.lines) if budget.lines else len(budget.accounts),
            "operating_cost_ytd": budget.total_operating_cost.get("ytd"),
            "lines": budget.lines,
            "summary": budget.summary,
            "accounts": {acc: bal.ytd for acc, bal in budget.accounts.items()} if budget.accounts else {},
            "warnings": budget.warnings,
        }
        json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        results.append({
            "filename": original_filename,
            "status": "replaced" if existed else "loaded",
            "period": period.label,
            "year": period.year,
            "month": period.month,
            "lines_count": meta["lines_count"],
            "operating_cost_ytd": meta["operating_cost_ytd"],
            "warnings": budget.warnings,
        })
        logger.info(f"{'Replaced' if existed else 'Stored'} budget for {period.label} from {original_filename}")

    # Case 2: Multi-month annual workbook (Jan..Dec columns)
    elif budget.months_loaded and budget.year:
        year = budget.year
        # Also save the annual file copy
        annual_xlsx = store_dir / f"budget_{year}.xlsx"
        shutil.copy2(upload_path, annual_xlsx)

        for month in budget.months_loaded:
            period = Period(year, month)
            json_path = store_dir / _meta_filename(period)
            existed = json_path.exists()

            month_accounts = {}
            for acc, bal in budget.accounts.items():
                if month in bal.ytd:
                    month_accounts[acc] = bal.ytd[month]

            meta = {
                "year": period.year,
                "month": period.month,
                "label": period.label,
                "filename": original_filename,
                "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "uploaded_by": user_name,
                "lines_count": len(month_accounts),
                "operating_cost_ytd": None,
                "lines": {},
                "accounts": month_accounts,
                "warnings": budget.warnings,
            }
            json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            results.append({
                "filename": original_filename,
                "status": "replaced" if existed else "loaded",
                "period": period.label,
                "year": period.year,
                "month": period.month,
                "lines_count": len(month_accounts),
                "warnings": budget.warnings,
            })
        logger.info(f"Stored annual budget for {year} ({len(budget.months_loaded)} months) from {original_filename}")

    else:
        raise BudgetFormatError(f"{original_filename}: Could not determine the budget period or year.")

    return results


def list_budgets(store_dir: Path) -> List[Dict]:
    """Return all stored budget periods, sorted newest period first."""
    store_dir = Path(store_dir)
    if not store_dir.exists():
        return []

    budgets = []
    for json_path in store_dir.glob("budget_*.json"):
        if json_path.name == "fa_budget.json":
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            budgets.append({
                "year": data.get("year"),
                "month": data.get("month"),
                "label": data.get("label") or Period(data["year"], data["month"]).label,
                "filename": data.get("filename"),
                "uploaded_at": data.get("uploaded_at"),
                "uploaded_by": data.get("uploaded_by"),
                "lines_count": data.get("lines_count", 0),
                "operating_cost_ytd": data.get("operating_cost_ytd"),
                "warnings": data.get("warnings", []),
            })
        except (OSError, ValueError, KeyError):
            continue

    # Sort descending by (year, month)
    budgets.sort(key=lambda b: (b.get("year", 0), b.get("month", 0)), reverse=True)
    return budgets


def load_budget(store_dir: Path, period: Period) -> Optional[Dict]:
    """Load budget data for a specific period, or None if not found."""
    json_path = Path(store_dir) / _meta_filename(period)
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete_budget(store_dir: Path, year: int, month: int) -> bool:
    """Delete the budget stored for a specific (year, month). Returns True if deleted."""
    store_dir = Path(store_dir)
    try:
        period = Period(year, month)
    except ValueError:
        return False

    json_path = store_dir / _meta_filename(period)
    xlsx_path = store_dir / _xlsx_filename(period)

    deleted = False
    if json_path.exists():
        json_path.unlink()
        deleted = True
    if xlsx_path.exists():
        xlsx_path.unlink()
        deleted = True

    return deleted


def clear_all_budgets(store_dir: Path) -> int:
    """Remove all stored budgets. Returns count of deleted files."""
    store_dir = Path(store_dir)
    if not store_dir.exists():
        return 0
    count = 0
    for p in store_dir.glob("budget_*.*"):
        p.unlink(missing_ok=True)
        count += 1
    return count
