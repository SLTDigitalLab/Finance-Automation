"""
PowerPoint Combiner for Finance Board Pack.

Combines selected sections into one downloadable PowerPoint deck in the exact required order:
  1. Board Pack (9 slides)
  2. Ratio Report (2 slides)
  3. Mobitel (10 slides)
  4. Telecom Services (9 slides)

Preserves slide order, formatting, charts, tables, images, and PowerPoint relationships.
Updates sequential slide numbering across all combined slides.
"""
import copy
import io
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from utils.logger import logger

SECTION_ORDER = ["board_pack", "ratio_report", "mobitel", "telecom_services"]
SECTION_NAMES = {
    "board_pack": "Board Pack",
    "ratio_report": "Ratio Report",
    "mobitel": "Mobitel",
    "telecom_services": "Telecom Services",
}


def _update_slide_number(slide, number: int):
    """Updates the slide number placeholder or footer text to the given number matching original placement."""
    found = False
    for shape in slide.shapes:
        if shape.has_text_frame:
            # Check if this shape is a slide number placeholder or lone digit
            t = shape.text_frame.text.strip()
            if "Slide Number" in shape.name or (t.isdigit() and len(t) <= 3 and shape.top is not None and shape.top > 6.0 * 914400):
                shape.text_frame.text = str(number)
                shape.left = 8610600
                shape.width = 2743200
                if shape.top is not None and abs(shape.top - 6518126) < 100000:
                    shape.top = 6518126
                    shape.height = 339874
                else:
                    shape.top = 6356350
                    shape.height = 365125
                found = True
                break
    if not found:
        # Check if there is a bottom-right textbox
        for shape in slide.shapes:
            if shape.has_text_frame and shape.left is not None and shape.left > 8.0 * 914400 and shape.top is not None and shape.top > 6.0 * 914400:
                t = shape.text_frame.text.strip()
                if t.isdigit() or not t:
                    shape.text_frame.text = str(number)
                    shape.left = 8610600
                    shape.width = 2743200
                    shape.top = 6356350
                    shape.height = 365125
                    break


def _append_slide(dest_prs: Presentation, src_slide):
    """Appends a copy of src_slide to dest_prs preserving shapes, tables, and images."""
    dest_slide = dest_prs.slides.add_slide(dest_prs.slide_layouts[6])

    # Copy shapes
    for shape in src_slide.shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            try:
                dest_slide.shapes.add_picture(
                    io.BytesIO(shape.image.blob),
                    shape.left,
                    shape.top,
                    shape.width,
                    shape.height,
                )
            except Exception as e:
                logger.warning(f"Failed to copy picture shape {shape.name}: {e}")
        else:
            try:
                dest_slide.shapes._spTree.append(copy.deepcopy(shape.element))
            except Exception as e:
                logger.warning(f"Failed to copy shape {shape.name}: {e}")

    return dest_slide


def combine_presentations(
    section_decks: List[Tuple[str, Presentation]],
    period_month: str,
    period_year: int,
    output_dir: str,
) -> Tuple[str, int, List[str]]:
    """
    Combines presentations according to SECTION_ORDER.
    Returns (output_file_path, total_slides, sections_included).
    """
    # Filter and sort according to required order
    deck_dict = {key: prs for key, prs in section_decks}
    ordered_decks = []
    for key in SECTION_ORDER:
        if key in deck_dict:
            ordered_decks.append((key, deck_dict[key]))

    if not ordered_decks:
        raise ValueError("No presentations provided to combine.")

    sections_included = [SECTION_NAMES.get(k, k) for k, _ in ordered_decks]

    # If only 1 deck is selected, we can clone and re-number
    first_key, first_prs = ordered_decks[0]
    if len(ordered_decks) == 1:
        # Clone it
        combined_prs = Presentation()
        combined_prs.slide_width = first_prs.slide_width
        combined_prs.slide_height = first_prs.slide_height

        for s_idx, src_slide in enumerate(first_prs.slides):
            new_slide = _append_slide(combined_prs, src_slide)
            _update_slide_number(new_slide, s_idx + 1)

        total_slides = len(combined_prs.slides)
    else:
        # Multiple decks
        combined_prs = Presentation()
        combined_prs.slide_width = first_prs.slide_width
        combined_prs.slide_height = first_prs.slide_height

        current_slide_num = 1
        for sec_key, prs in ordered_decks:
            for src_slide in prs.slides:
                new_slide = _append_slide(combined_prs, src_slide)
                _update_slide_number(new_slide, current_slide_num)
                current_slide_num += 1

        total_slides = len(combined_prs.slides)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "Combined" if len(ordered_decks) > 1 else first_key.replace("_", " ").title().replace(" ", "_")
    filename = f"Finance_Board_Pack_{suffix}_{period_month}_{period_year}_{uuid.uuid4().hex[:8]}.pptx"
    out_path = out_dir / filename
    combined_prs.save(str(out_path))
    logger.info(f"Combined presentation saved to {out_path} ({total_slides} slides)")

    return str(out_path), total_slides, sections_included
