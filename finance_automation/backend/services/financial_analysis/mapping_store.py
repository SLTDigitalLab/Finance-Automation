"""
Keeps the current GL code mapping workbook. Uploading a new one replaces it;
it is validated before it is stored, so the stored file always reads.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from services.financial_analysis.mapping_reader import GLMapping, read_gl_mapping

MAPPING_FILE = "gl_mapping.xlsx"
META_FILE = "gl_mapping.json"


def save_mapping(store_dir: Path, upload_path: Path, original_filename: str, user_name: str = None) -> GLMapping:
    """Validates the workbook at `upload_path` and makes it the current mapping."""
    mapping = read_gl_mapping(upload_path)   # raises MappingFormatError
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    upload_path.replace(store_dir / MAPPING_FILE)
    meta = {
        "filename": original_filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uploaded_by": user_name,
    }
    (store_dir / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return mapping


def load_mapping(store_dir: Path) -> Optional[GLMapping]:
    path = Path(store_dir) / MAPPING_FILE
    return read_gl_mapping(path) if path.exists() else None


def mapping_info(store_dir: Path) -> Optional[Dict[str, object]]:
    meta_path = Path(store_dir) / META_FILE
    if not (Path(store_dir) / MAPPING_FILE).exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"filename": MAPPING_FILE}
