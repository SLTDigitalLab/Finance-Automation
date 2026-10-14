"""
Fills the Finance Board Pack PowerPoint template with figures from BoardPackData.

The template (board_pack_templates/board_pack_template.pptx) is the stakeholder's
own deck with empty table cells. Each empty cell already carries its font, size,
colour and bold setting, so values are written with that formatting and the
deck keeps its exact look.
"""
import copy
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Dict, Optional

from pptx import Presentation
from pptx.oxml.ns import qn

from services.board_pack_reader import LABEL_KEYS, BoardPackData, Period, _norm
from utils.logger import logger

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "board_pack_templates" / "board_pack_template.pptx"

# Template slide index (0-based) -> what fills it
EXEC_SLIDES = {0: "Group", 1: "SLT", 2: "Mobitel", 3: "SLTS"}
FIN_PAIR_SLIDES = {
    4: ("ytd", "SLT", "Group"),
    5: ("ytd", "SLT", "Mobitel"),
    7: ("month", "SLT", "Group"),
    8: ("month", "SLT", "Mobitel"),
}
FIN_SINGLE_SLIDE = 6  # SLT / Mobitel / SLTSL Amalgamated, YTD current year

# Executive Summary table columns
EXEC_COLUMNS = {
    2: ("month", "act"), 3: ("month", "bud"), 4: ("month", "var_bud"), 5: ("month", "pct_bud"),
    7: ("ytd", "act"), 8: ("ytd", "ly"), 9: ("ytd", "var_ly"), 10: ("ytd", "pct_ly"),
    11: ("ytd", "bud"), 12: ("ytd", "var_bud"), 13: ("ytd", "pct_bud"),
}
PCT_FIELDS = {"pct_bud", "pct_ly", "pct"}


# ─── Number formatting (matches the board pack: 1,234  (18)  -6.00%  #DIV/0!) ──

def _round(value: float, places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def format_amount(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if value == 0:
        return "0"
    rounded = _round(abs(value), 0)
    text = f"{rounded:,.0f}"
    return f"({text})" if value < 0 else text


def format_pct(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    rounded = _round(value * 100, 2)
    if rounded == 0 and value < 0:
        return "-0.00%"
    return f"{rounded:.2f}%"


def _format(metric: str, field: str, value) -> str:
    if field in PCT_FIELDS or metric.endswith("_margin"):
        return format_pct(value)
    return format_amount(value)


# ─── Cell writing ────────────────────────────────────────────────────────────

def _set_cell_text(cell, text: str):
    """Replaces the cell text with a single run that uses the cell's own formatting."""
    tx_body = cell._tc.txBody
    paragraphs = tx_body.findall(qn("a:p"))
    p = paragraphs[0]
    for extra in paragraphs[1:]:
        tx_body.remove(extra)

    end_rpr = p.find(qn("a:endParaRPr"))
    first_run = p.find(qn("a:r"))
    source = first_run.find(qn("a:rPr")) if first_run is not None else end_rpr

    for child in list(p):
        if child.tag in (qn("a:r"), qn("a:br"), qn("a:fld")):
            p.remove(child)
    if not text:
        return

    # Some template cells are left-aligned; numbers read best right-aligned.
    p_pr = p.get_or_add_pPr()
    if p_pr.get("algn") != "ctr":
        p_pr.set("algn", "r")

    run = p.makeelement(qn("a:r"), {})
    if source is not None:
        rpr = copy.deepcopy(source)
        rpr.tag = qn("a:rPr")
        sz = rpr.get("sz")
        if sz is not None and int(sz) > 1200:
            rpr.set("sz", "1200")
        run.append(rpr)
    else:
        rpr = run.makeelement(qn("a:rPr"), {"sz": "1200"})
        run.append(rpr)
    t = run.makeelement(qn("a:t"), {})
    t.text = text
    run.append(t)
    if end_rpr is not None:
        end_sz = end_rpr.get("sz")
        if end_sz is not None and int(end_sz) > 1200:
            end_rpr.set("sz", "1200")
        end_rpr.addprevious(run)
    else:
        p.append(run)


def _table(slide):
    for shape in slide.shapes:
        if shape.has_table:
            return shape.table
    raise ValueError("Template slide has no table")


def _fill_rows(table, fill_row: Callable[[str, int], None]):
    for r in range(len(table.rows)):
        key = LABEL_KEYS.get(_norm(table.cell(r, 0).text))
        if key:
            fill_row(key, r)


def _data_start_row(table) -> int:
    for r in range(len(table.rows)):
        if LABEL_KEYS.get(_norm(table.cell(r, 0).text)):
            return r
    return len(table.rows)


# ─── Period relabelling ──────────────────────────────────────────────────────

def _relabel_period(prs, period: Period):
    """Rewrites the template's Aug'26 period labels for the uploaded month."""
    tpl = Period(8, 2026)  # period the template was authored for
    prev_tpl = tpl.previous_month
    replacements = {
        f"{prev_tpl.month_name}'{prev_tpl.year % 100:02d}": period.previous_month.label,
        tpl.label: period.label,
        tpl.previous_year.label: period.previous_year.label,
        str(tpl.year): str(period.year),
        str(tpl.year - 1): str(period.year - 1),
        tpl.month_name: period.month_name,
    }
    # One pass, longest token first, so a replaced value is never replaced again
    pattern = re.compile("|".join(
        rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])" for k in sorted(replacements, key=len, reverse=True)
    ))

    def rewrite(text_frame):
        for paragraph in text_frame.paragraphs:
            for run in paragraph.runs:
                new = pattern.sub(lambda m: replacements[m.group(0)], run.text)
                if new != run.text:
                    run.text = new

    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_table:
                table = shape.table
                for r in range(_data_start_row(table)):
                    for c in range(len(table.columns)):
                        rewrite(table.cell(r, c).text_frame)


# ─── Slide fillers ───────────────────────────────────────────────────────────

def _fill_exec_slide(slide, values: Dict[str, Dict[str, Dict[str, object]]]):
    table = _table(slide)

    def fill(metric: str, r: int):
        for c, (block, field) in EXEC_COLUMNS.items():
            if metric in values[block]:
                _set_cell_text(table.cell(r, c), _format(metric, field, values[block][metric].get(field)))

    _fill_rows(table, fill)


def _fill_slts_slide(slide, slts: Dict[str, Optional[float]]):
    """Legacy filler kept for backward compatibility; SLTS now uses _fill_exec_slide."""
    pass


def _fill_fin_pair_slide(slide, left: Dict, right: Dict):
    table = _table(slide)
    fields = ["cur", "prev", "var", "pct"]

    def fill(metric: str, r: int):
        for i, field in enumerate(fields):
            _set_cell_text(table.cell(r, 1 + i), _format(metric, field, left[metric].get(field)))
            _set_cell_text(table.cell(r, 5 + i), _format(metric, field, right[metric].get(field)))

    _fill_rows(table, fill)


def _fill_fin_single_slide(slide, entities: list):
    table = _table(slide)

    def fill(metric: str, r: int):
        for i, values in enumerate(entities):
            _set_cell_text(table.cell(r, 1 + i), _format(metric, "cur", values[metric].get("cur")))

    _fill_rows(table, fill)


# ─── Entry point ─────────────────────────────────────────────────────────────

def generate_board_pack(data: BoardPackData, output_dir: str, template_path: Optional[Path] = None) -> str:
    template = Path(template_path or TEMPLATE_PATH)
    if not template.exists():
        raise FileNotFoundError(f"Board pack template not found at {template}")

    prs = Presentation(str(template))
    slides = list(prs.slides)

    for index, entity in EXEC_SLIDES.items():
        _fill_exec_slide(slides[index], data.exec[entity])
    for index, (block, left, right) in FIN_PAIR_SLIDES.items():
        _fill_fin_pair_slide(slides[index], data.fin[block][left], data.fin[block][right])
    ytd = data.fin["ytd"]
    _fill_fin_single_slide(slides[FIN_SINGLE_SLIDE], [ytd["SLT"], ytd["Mobitel"], ytd["SLTS"]])

    _relabel_period(prs, data.period)

    filename = (
        f"Finance_Board_Pack_{data.period.month_name}_{data.period.year}_{uuid.uuid4().hex[:8]}.pptx"
    )
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    logger.info(f"Board pack saved to: {output_path}")
    return str(output_path)
