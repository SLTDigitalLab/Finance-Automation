"""
Keeps each month's SLTS YTD figures so the next month's board pack can work out
its month values (YTD this month less YTD last month). One JSON file per period.
"""
import json
from pathlib import Path
from typing import Dict, Optional

from services.board_pack_reader import Period
from utils.logger import logger


def _path(history_dir: Path, period: Period) -> Path:
    return Path(history_dir) / f"{period.year}-{period.month:02d}.json"


def load_snapshot(history_dir: Path, period: Period) -> Optional[Dict[str, object]]:
    path = _path(history_dir, period)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"Could not read board pack snapshot {path}: {exc}")
        return None


def save_snapshot(history_dir: Path, period: Period, snapshot: Dict[str, object]):
    path = _path(history_dir, period)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
