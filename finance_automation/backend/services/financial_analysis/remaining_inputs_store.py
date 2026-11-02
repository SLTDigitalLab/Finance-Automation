"""
Stores and retrieves remaining financial input files (Mobitel Write-up DOCX and Group P&L Excel).
Files and their metadata are persisted under uploads/financial_analysis/remaining_inputs/.
"""
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger(__name__)

DEFAULT_STORE_DIR = settings.UPLOAD_DIR / "financial_analysis" / "remaining_inputs"
METADATA_FILE = "metadata.json"

VALID_FILE_TYPES = {"mobitel_writeup", "group_pl"}


def _normalize_type(file_type: str) -> str:
    norm = file_type.lower().replace("-", "_").strip()
    if norm not in VALID_FILE_TYPES:
        raise ValueError(f"Invalid file_type '{file_type}'. Must be one of: {sorted(VALID_FILE_TYPES)}")
    return norm


def _get_meta_path(store_dir: Path) -> Path:
    return store_dir / METADATA_FILE


def _load_metadata(store_dir: Path) -> Dict[str, Any]:
    meta_path = _get_meta_path(store_dir)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to read metadata at {meta_path}: {exc}")
        return {}


def _save_metadata(store_dir: Path, data: Dict[str, Any]) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    meta_path = _get_meta_path(store_dir)
    meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_file(
    file_type: str,
    path: Path,
    filename: str,
    uploader: Optional[str] = None,
    store_dir: Optional[Path] = None,
) -> Path:
    """
    Saves an uploaded remaining input file and updates persistence metadata.
    """
    normalized_type = _normalize_type(file_type)
    target_dir = Path(store_dir or DEFAULT_STORE_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    src_path = Path(path)
    ext = src_path.suffix.lower()
    dest_filename = f"{normalized_type}{ext}"
    dest_path = target_dir / dest_filename

    # If destination already exists, remove or replace
    if dest_path.resolve() != src_path.resolve():
        shutil.copy2(src_path, dest_path)

    metadata = _load_metadata(target_dir)
    metadata[normalized_type] = {
        "filename": filename,
        "stored_filename": dest_filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uploader": uploader,
        "size_bytes": dest_path.stat().st_size if dest_path.exists() else 0,
    }
    _save_metadata(target_dir, metadata)
    logger.info(f"Saved remaining input {normalized_type} to {dest_path}")
    return dest_path


def load_file(file_type: str, store_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Returns the Path to the stored file for `file_type` if it exists, else None.
    """
    try:
        normalized_type = _normalize_type(file_type)
    except ValueError:
        return None

    target_dir = Path(store_dir or DEFAULT_STORE_DIR)
    metadata = _load_metadata(target_dir)
    record = metadata.get(normalized_type)
    if not record:
        return None

    stored_filename = record.get("stored_filename")
    if stored_filename:
        file_path = target_dir / stored_filename
        if file_path.exists():
            return file_path

    # Fallback to scanning pattern
    for p in target_dir.glob(f"{normalized_type}.*"):
        if p.name != METADATA_FILE and p.is_file():
            return p

    return None


def delete_file(file_type: str, store_dir: Optional[Path] = None) -> bool:
    """
    Deletes the file and metadata entry for `file_type`.
    """
    normalized_type = _normalize_type(file_type)
    target_dir = Path(store_dir or DEFAULT_STORE_DIR)
    metadata = _load_metadata(target_dir)

    deleted = False
    record = metadata.pop(normalized_type, None)
    if record and record.get("stored_filename"):
        fpath = target_dir / record["stored_filename"]
        if fpath.exists():
            try:
                fpath.unlink()
                deleted = True
            except OSError as exc:
                logger.warning(f"Error deleting {fpath}: {exc}")

    # Remove any stray file with the type prefix
    for p in target_dir.glob(f"{normalized_type}.*"):
        if p.name != METADATA_FILE and p.is_file():
            try:
                p.unlink()
                deleted = True
            except OSError:
                pass

    _save_metadata(target_dir, metadata)
    return deleted


def get_status(store_dir: Optional[Path] = None) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Returns current status of uploaded remaining inputs:
    {
      "mobitel_writeup": {"filename": ..., "uploaded_at": ..., "uploader": ...} | None,
      "group_pl": {"filename": ..., "uploaded_at": ..., "uploader": ...} | None
    }
    """
    target_dir = Path(store_dir or DEFAULT_STORE_DIR)
    metadata = _load_metadata(target_dir)

    status: Dict[str, Optional[Dict[str, Any]]] = {
        "mobitel_writeup": None,
        "group_pl": None,
    }

    for f_type in VALID_FILE_TYPES:
        info = metadata.get(f_type)
        if info:
            # Check if file actually exists
            file_path = load_file(f_type, store_dir=target_dir)
            if file_path and file_path.exists():
                status[f_type] = {
                    "filename": info.get("filename"),
                    "uploaded_at": info.get("uploaded_at"),
                    "uploader": info.get("uploader"),
                    "size_bytes": info.get("size_bytes", file_path.stat().st_size),
                }
            else:
                # Metadata exists but file missing
                status[f_type] = None

    return status
