"""
Unified Board Pack Service.

Orchestrates multi-section generation:
  1. Board Pack (9 slides)
  2. Ratio Report (2 slides)
  3. Mobitel (10 slides)
  4. Telecom Services (9 slides)

Identifies files by structure, validates all required inputs for selected sections,
generates individual section decks, and combines them into one final deck in the exact
required order.
"""
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from pptx import Presentation

from services.board_pack_classifier import classify_file, check_section_requirements
from services.board_pack_combiner import combine_presentations
from services.board_pack_generator import generate_board_pack
from services.board_pack_history import load_snapshot, save_snapshot
from services.board_pack_reader import read_board_pack_workbook
from services.board_pack_slides_generator import generate_board_pack_slides
from services.board_pack_slides_reader import read_board_pack_slides_workbook
from services.mobitel_generator import generate_mobitel_deck
from services.mobitel_reader import read_mobitel_workbook
from services.telecom_services_generator import generate_telecom_services_deck
from services.telecom_services_reader import read_telecom_services_inputs

logger = logging.getLogger(__name__)


def inspect_files(staged_files: List[Tuple[str, Path]]) -> List[Dict[str, Any]]:
    """Inspects staged files and returns their structural classification."""
    results = []
    for original_name, path in staged_files:
        info = classify_file(path)
        info["original_filename"] = original_name
        info["filename"] = original_name  # user-facing
        results.append(info)
    return results


def generate_unified_pack(
    staged_files: List[Tuple[str, Path]],
    selected_sections: List[str],
    user_output_dir: Path,
    legacy_history_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Validates and generates the board pack for selected sections.
    Combines them into a single presentation in the required order.
    """
    if not selected_sections:
        raise ValueError("At least one section must be selected.")

    # 1. Classify all files
    classified = inspect_files(staged_files)
    req_status = check_section_requirements(selected_sections, classified)

    if not req_status["all_ready"]:
        missing_msg = "; ".join(req_status["missing"])
        raise ValueError(f"Missing required inputs for selected sections: {missing_msg}")

    # Map roles to staged paths
    role_file_map: Dict[str, Path] = {}
    for orig_name, p in staged_files:
        for c in classified:
            if c["original_filename"] == orig_name and c["valid"]:
                for r in c["roles"]:
                    if r not in role_file_map:
                        role_file_map[r] = p

    temp_gen_dir = Path(tempfile.mkdtemp(prefix="board_pack_gen_"))
    section_decks: List[Tuple[str, Presentation]] = []
    all_sheets_used: List[str] = []
    all_files_used: List[str] = []
    all_warnings: List[str] = []
    detected_period = ("Oct", 2026)

    try:
        # Section 1: Board Pack (9 slides)
        if "board_pack" in selected_sections:
            bp_file = role_file_map["board_pack_excel"]
            all_files_used.append(bp_file.name)
            history_dir = user_output_dir / "history"

            def previous_snapshot(period):
                snapshot = load_snapshot(history_dir, period)
                if snapshot is None and legacy_history_dir:
                    snapshot = load_snapshot(legacy_history_dir, period)
                return snapshot

            data_bp = read_board_pack_workbook(str(bp_file), previous_snapshot)
            all_sheets_used.extend(data_bp.sheets_used)
            all_warnings.extend(data_bp.warnings)
            detected_period = (data_bp.period.month_name, data_bp.period.year)

            bp_out = generate_board_pack(data_bp, str(temp_gen_dir))
            save_snapshot(history_dir, data_bp.period, data_bp.snapshot)
            section_decks.append(("board_pack", Presentation(bp_out)))

        # Section 2: Ratio Report (2 slides)
        if "ratio_report" in selected_sections:
            ratio_file = role_file_map["ratio_excel"]
            all_files_used.append(ratio_file.name)
            data_ratio = read_board_pack_slides_workbook(str(ratio_file))
            all_sheets_used.extend(data_ratio.sheets_used)
            detected_period = (data_ratio.period_month, data_ratio.period_year)

            ratio_out = generate_board_pack_slides(data_ratio, str(temp_gen_dir))
            section_decks.append(("ratio_report", Presentation(ratio_out)))

        # Section 3: Mobitel (10 slides)
        if "mobitel" in selected_sections:
            mob_file = role_file_map["mobitel_excel"]
            all_files_used.append(mob_file.name)
            data_mob = read_mobitel_workbook(str(mob_file))
            all_sheets_used.extend(data_mob.sheets_used)
            all_warnings.extend(data_mob.warnings)
            detected_period = (data_mob.month_label, data_mob.current_year)

            mob_out = generate_mobitel_deck(data_mob, str(temp_gen_dir))
            section_decks.append(("mobitel", Presentation(mob_out)))

        # Section 4: Telecom Services (9 slides)
        if "telecom_services" in selected_sections:
            info_file = role_file_map["telecom_info_excel"]
            pl_file = role_file_map.get("telecom_pl_excel")
            bscf_file = role_file_map.get("telecom_bscf_pptx")

            data_ts = read_telecom_services_inputs(
                info_excel_path=str(info_file),
                pl_excel_path=str(pl_file) if pl_file else None,
                bscf_pptx_path=str(bscf_file) if bscf_file else None,
            )
            all_sheets_used.extend(data_ts.sheets_used)
            all_files_used.extend(data_ts.files_used)
            all_warnings.extend(data_ts.warnings)
            detected_period = (data_ts.month_label, data_ts.current_year)

            ts_out = generate_telecom_services_deck(data_ts, str(temp_gen_dir))
            section_decks.append(("telecom_services", Presentation(ts_out)))

        # Combine all generated section presentations in the required order
        final_path, total_slides, sections_included = combine_presentations(
            section_decks=section_decks,
            period_month=detected_period[0],
            period_year=detected_period[1],
            output_dir=str(user_output_dir),
        )

        return {
            "status": "success",
            "filename": Path(final_path).name,
            "period": f"{detected_period[0]} {detected_period[1]}",
            "slide_count": total_slides,
            "sections_generated": sections_included,
            "sheets_used": list(dict.fromkeys(all_sheets_used)),
            "files_used": list(dict.fromkeys(all_files_used)),
            "warnings": all_warnings,
        }

    finally:
        # Cleanup temporary generation folder
        try:
            import shutil
            shutil.rmtree(temp_gen_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Failed to remove temp dir {temp_gen_dir}: {e}")
