"""
CIP Reconciliation Store
Manages metadata, file paths, and storage for Use Case 4: CIP Reconciliation Report.
"""
from dataclasses import asdict, dataclass
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads" / "cip_reconciliation"
OUTPUT_DIR = BASE_DIR / "outputs" / "cip_reconciliation"
METADATA_FILE = UPLOAD_DIR / "metadata.json"

CATEGORIES = [
    "journal_details",
    "project_codes",
    "interfaced_cip",
    "subledger_detail",
    "opening_balances",
]

ACCOUNTS = ["111401", "111402", "111403", "111404", "111405", "111406"]


@dataclass
class CIPFileMeta:
    category: str
    filename: str
    original_name: str
    file_size: int
    uploaded_at: str
    uploaded_by: str
    period: str
    accounts_covered: List[str]
    user_id: Optional[int] = None


def _user_upload_dir(user_id: Optional[int] = None) -> Path:
    if user_id is not None:
        return UPLOAD_DIR / str(user_id)
    return UPLOAD_DIR


def _user_output_dir(user_id: Optional[int] = None) -> Path:
    if user_id is not None:
        return OUTPUT_DIR / str(user_id)
    return OUTPUT_DIR


def _meta_path(user_id: Optional[int] = None) -> Path:
    return _user_upload_dir(user_id) / "metadata.json"


def _ensure_dirs(user_id: Optional[int] = None):
    _user_upload_dir(user_id).mkdir(parents=True, exist_ok=True)
    _user_output_dir(user_id).mkdir(parents=True, exist_ok=True)


def load_metadata(user_id: Optional[int] = None) -> Dict[str, Any]:
    _ensure_dirs(user_id)
    meta_file = _meta_path(user_id)
    if not meta_file.exists():
        return {"files": {}, "current_period": "Jul-26"}
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning(f"Failed to read CIP metadata for user {user_id}: {exc}")
        return {"files": {}, "current_period": "Jul-26"}


def save_metadata(meta: Dict[str, Any], user_id: Optional[int] = None):
    _ensure_dirs(user_id)
    meta_file = _meta_path(user_id)
    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception as exc:
        logger.error(f"Failed to save CIP metadata for user {user_id}: {exc}")


def get_file_path(category: str, period: Optional[str] = None, user_id: Optional[int] = None) -> Optional[Path]:
    meta = load_metadata(user_id)
    period = period or meta.get("current_period", "Jul-26")
    file_info = meta.get("files", {}).get(period, {}).get(category)
    if file_info:
        stored_name = file_info.get("filename")
        if stored_name:
            p = _user_upload_dir(user_id) / period / stored_name
            if p.exists():
                return p

    # Fallback for opening_balances if not explicitly uploaded
    if category == "opening_balances":
        fallback = BASE_DIR.parent / "Input" / "CIP_Reconciliation_report" / "CIP reconciliation report_Jul26_output file.xlsx"
        if fallback.exists():
            return fallback

    return None


def save_uploaded_file(
    category: str,
    temp_path: Path,
    original_name: str,
    period: str,
    uploaded_by: str,
    accounts_covered: Optional[List[str]] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    _ensure_dirs(user_id)
    period_dir = _user_upload_dir(user_id) / period
    period_dir.mkdir(parents=True, exist_ok=True)

    dest_path = period_dir / f"{category}_{original_name}"
    shutil.copy2(temp_path, dest_path)

    file_size = dest_path.stat().st_size
    from datetime import datetime

    meta = load_metadata(user_id)
    if period not in meta["files"]:
        meta["files"][period] = {}

    file_meta = CIPFileMeta(
        category=category,
        filename=dest_path.name,
        original_name=original_name,
        file_size=file_size,
        uploaded_at=datetime.utcnow().isoformat(),
        uploaded_by=uploaded_by,
        period=period,
        accounts_covered=accounts_covered or ACCOUNTS,
        user_id=user_id,
    )

    meta["files"][period][category] = asdict(file_meta)
    meta["current_period"] = period
    save_metadata(meta, user_id)
    return asdict(file_meta)


def remove_file(category: str, period: str, user_id: Optional[int] = None) -> bool:
    meta = load_metadata(user_id)
    file_info = meta.get("files", {}).get(period, {}).get(category)
    if not file_info:
        return False

    stored_name = file_info.get("filename")
    if stored_name:
        p = _user_upload_dir(user_id) / period / stored_name
        if p.exists():
            try:
                p.unlink()
            except Exception as e:
                logger.warning(f"Could not remove {p}: {e}")

    meta["files"][period].pop(category, None)
    save_metadata(meta, user_id)
    return True


def get_status(period: Optional[str] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
    meta = load_metadata(user_id)
    period = period or meta.get("current_period", "Jul-26")
    period_files = meta.get("files", {}).get(period, {})

    categories_status = {}
    for cat in CATEGORIES:
        info = period_files.get(cat)
        if info:
            p = _user_upload_dir(user_id) / period / info.get("filename", "")
            exists = p.exists()
            categories_status[cat] = {
                "uploaded": exists,
                "filename": info.get("original_name"),
                "file_size": info.get("file_size"),
                "uploaded_at": info.get("uploaded_at"),
                "uploaded_by": info.get("uploaded_by"),
                "accounts_covered": info.get("accounts_covered", []),
            }
        else:
            categories_status[cat] = {
                "uploaded": False,
                "filename": None,
                "file_size": None,
                "uploaded_at": None,
                "uploaded_by": None,
                "accounts_covered": [],
            }

    # Opening balance is optional (defaults to reference sample or 0 if omitted)
    req_cats = ["journal_details", "project_codes", "interfaced_cip", "subledger_detail"]
    all_ready = all(categories_status[cat]["uploaded"] for cat in req_cats)

    return {
        "period": period,
        "categories": categories_status,
        "is_ready_for_reconciliation": all_ready,
    }

