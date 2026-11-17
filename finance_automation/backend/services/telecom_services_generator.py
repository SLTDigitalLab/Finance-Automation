"""
Generates the 9-slide Telecom Services (SLTS) PowerPoint deck.
"""
import copy
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn

from services.board_pack_classifier import _norm
from services.telecom_services_reader import TelecomServicesData, SLTSLineItem
from utils.logger import logger

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "board_pack_templates" / "telecom_services_template.pptx"


def _round(value: float, places: int = 0) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def format_amount(value: Optional[float]) -> str:
    if value is None:
        return ""
    if value == 0 or abs(value) < 0.0001:
        return "-"
    rounded = _round(abs(value), 0)
    text = f"{rounded:,.0f}"
    return f"({text})" if value < 0 else text


def format_pct(value: Optional[float], decimals: int = 0) -> str:
    if value is None:
        return ""
    if value == 0 or abs(value) < 0.00001:
        return "-"
    scaled = _round(abs(value) * 100, decimals)
    text = f"{scaled:.{decimals}f}%"
    return f"({text})" if value < 0 else text


def _set_cell_text(cell, text: str, align: str = "r"):
    """Sets cell text while preserving cell formatting."""
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
    if text == "" or text is None:
        return

    p_pr = p.get_or_add_pPr()
    if align:
        p_pr.set("algn", align)

    run = p.makeelement(qn("a:r"), {})
    if source is not None:
        rpr = copy.deepcopy(source)
        rpr.tag = qn("a:rPr")
        run.append(rpr)
    else:
        rpr = run.makeelement(qn("a:rPr"), {"sz": "1200"})
        run.append(rpr)
    t = run.makeelement(qn("a:t"), {})
    t.text = text
    run.append(t)
    if end_rpr is not None:
        end_rpr.addprevious(run)
    else:
        p.append(run)


def _update_ytd_header_cell(cell, year: int):
    """
    Updates only the year text in a two-paragraph 'YEAR\\nYTD' header cell,
    preserving the original two-paragraph structure and all run formatting.
    The template already stores '2025' in para[0] and 'YTD' in para[1].
    """
    tx_body = cell._tc.txBody
    paragraphs = tx_body.findall(qn("a:p"))
    if not paragraphs:
        return
    # Update the first paragraph's run text to the new year
    p0 = paragraphs[0]
    runs = p0.findall(qn("a:r"))
    if runs:
        t_elem = runs[0].find(qn("a:t"))
        if t_elem is not None:
            t_elem.text = str(year)
    # Second paragraph ('YTD') stays unchanged — only the year changes


def _table(slide):
    for shape in slide.shapes:
        if shape.has_table:
            return shape.table
    return None


def _find_item_by_label(items: List[SLTSLineItem], target_label: str) -> Optional[SLTSLineItem]:
    target_norm = _norm(target_label)
    if not target_norm:
        return None

    # 1. Exact match first
    for it in items:
        if _norm(it.label) == target_norm:
            return it

    # 2. Known abbreviations / aliases mapping
    abbrev_map = {
        "serviceintegration": ["si", "serviceintegration"],
        "outsideplant": ["osp", "outsideplant"],
        "peotv": ["peotv", "peo"],
        "digitalservices": ["ds", "digitalsolution", "digitalsolutions", "digitalservices"],
        "digitalsolution": ["ds", "digitalsolution", "digitalsolutions", "digitalservices"],
        "totalsellingexpenditure": ["total", "totalsellingexpenditure"],
        "totalothercosts": ["total", "totalothercosts"],
        "netimpact": ["netimpact"],
        "depreciationandamortization": ["depreciationandamortization"],
        "netinterestincomecost": ["netinterestincomecost", "netinterestincome/cost", "netinterestcost"],
        "exchangegainloss": ["exchangegainloss", "exchange(gain)/loss", "exchangegain/(loss)"],
        "otherincome": ["otherincome"],
        "incometax": ["incometax"],
        "pbt": ["pbt"],
        "total": ["total"],
    }
    if target_norm in abbrev_map:
        allowed = abbrev_map[target_norm]
        for it in items:
            it_n = _norm(it.label)
            if it_n in allowed:
                return it

    # 3. Substring match only for distinct words with len >= 4
    for it in items:
        it_n = _norm(it.label)
        if len(it_n) >= 4 and len(target_norm) >= 4:
            if it_n in target_norm or target_norm in it_n:
                return it

    return None


def _fill_slts_table(table, items: List[SLTSLineItem], is_other_costs: bool = False):
    """
    Fills SLTS 8-column table:
    Col 0: Label
    Col 2: Act
    Col 3: Bud
    Col 4: Vari / Favourable (Adverse)
    Col 5: %
    Col 7: LY Act
    """
    for r_idx in range(2, len(table.rows)):
        row_lbl = table.cell(r_idx, 0).text.strip()
        if not row_lbl:
            continue
        matched = _find_item_by_label(items, row_lbl)
        if not matched:
            continue

        _set_cell_text(table.cell(r_idx, 2), format_amount(matched.act))
        _set_cell_text(table.cell(r_idx, 3), format_amount(matched.bud))

        norm_lbl = _norm(row_lbl)

        if is_other_costs:
            # Slide 16: Favourable/(Adverse) presentation rules
            if norm_lbl in ("depreciationandamortization", "totalothercosts", "incometax"):
                # Cost/Expense items: Favourable when Budget > Actual
                if matched.act is not None and matched.bud is not None:
                    var = matched.bud - matched.act
                    _set_cell_text(table.cell(r_idx, 4), format_amount(var))
                    if norm_lbl == "totalothercosts":
                        # Blank percentage for Total other costs as required
                        _set_cell_text(table.cell(r_idx, 5), "")
                    else:
                        pct = (var / matched.bud) if matched.bud else None
                        _set_cell_text(table.cell(r_idx, 5), format_pct(pct, 0))
                else:
                    _set_cell_text(table.cell(r_idx, 4), format_amount(matched.var))
                    _set_cell_text(table.cell(r_idx, 5), format_pct(matched.var_pct, 0))
            elif norm_lbl == "otherincome":
                # Other income: Var is 0 -> '-', % is '0%'
                _set_cell_text(table.cell(r_idx, 4), format_amount(matched.var))
                if matched.var is not None and abs(matched.var) < 0.001:
                    _set_cell_text(table.cell(r_idx, 5), "0%")
                else:
                    _set_cell_text(table.cell(r_idx, 5), format_pct(matched.var_pct, 0))
            elif norm_lbl == "netimpact":
                # Net Impact (Profit): Favourable when Actual > Budget
                var = matched.act - matched.bud if (matched.act is not None and matched.bud is not None) else matched.var
                _set_cell_text(table.cell(r_idx, 4), format_amount(var))
                # For favourable profit impact, % is positive
                pct = abs(matched.var_pct) if matched.var_pct is not None else (var / matched.bud if matched.bud else None)
                _set_cell_text(table.cell(r_idx, 5), format_pct(pct, 0))
            elif norm_lbl == "pbt":
                _set_cell_text(table.cell(r_idx, 4), format_amount(matched.var))
                _set_cell_text(table.cell(r_idx, 5), format_pct(matched.var_pct, 0))
            else:
                _set_cell_text(table.cell(r_idx, 4), format_amount(matched.var))
                _set_cell_text(table.cell(r_idx, 5), format_pct(matched.var_pct, 0))
        else:
            _set_cell_text(table.cell(r_idx, 4), format_amount(matched.var))
            _set_cell_text(table.cell(r_idx, 5), format_pct(matched.var_pct, 0))

        _set_cell_text(table.cell(r_idx, 7), format_amount(matched.ly_act))


def _copy_table_contents(src_table, dest_table):
    """Copies all cell contents from src_table into dest_table preserving alignment."""
    for r in range(min(len(src_table.rows), len(dest_table.rows))):
        for c in range(min(len(src_table.columns), len(dest_table.columns))):
            src_cell = src_table.cell(r, c)
            text = src_cell.text.strip()
            if text:
                # Column 0 is always left-aligned to avoid labels overflowing numeric columns
                if c == 0:
                    align = "l"
                else:
                    align = "ctr"
                    if src_cell.text_frame.paragraphs:
                        src_p = src_cell.text_frame.paragraphs[0]
                        if src_p.alignment == PP_ALIGN.LEFT:
                            align = "l"
                        elif src_p.alignment == PP_ALIGN.RIGHT:
                            align = "r"
                        elif src_p.alignment == PP_ALIGN.CENTER:
                            align = "ctr"
                _set_cell_text(dest_table.cell(r, c), text, align=align)


def populate_telecom_services_presentation(prs: Presentation, data: TelecomServicesData):
    """Populates an open Telecom Services presentation with TelecomServicesData."""
    slides = prs.slides

    # Slide 1: Title – update subtitle text while preserving bold/blue/size formatting
    s1 = slides[0]
    for shape in s1.shapes:
        if shape.has_text_frame:
            text = shape.text_frame.text
            if "YTD" in text or "202" in text:
                new_text = f"YTD {data.month_label} {data.current_year}"
                tf = shape.text_frame
                para = tf.paragraphs[0]
                runs = para.runs
                if runs:
                    first_run = runs[0]
                    first_run.text = new_text
                    for extra_run in list(para._p.findall(qn("a:r")))[1:]:
                        para._p.remove(extra_run)
                else:
                    shape.text_frame.text = new_text

    # Slide 2: Revenue (SLTS)
    s2 = slides[1]
    t2 = _table(s2)
    if t2:
        _set_cell_text(t2.cell(0, 2), f"YTD {data.month_label} '{data.short_year}", align="ctr")
        _update_ytd_header_cell(t2.cell(0, 7), data.previous_year)
        _fill_slts_table(t2, data.revenue_items)

    # Slide 3: Direct Costs (SLTS)
    s3 = slides[2]
    t3 = _table(s3)
    if t3:
        _set_cell_text(t3.cell(0, 2), f"YTD – {data.month_label} '{data.short_year}", align="ctr")
        _update_ytd_header_cell(t3.cell(0, 7), data.previous_year)
        _fill_slts_table(t3, data.direct_cost_items)

    # Slide 4: Sales & Marketing Costs (SLTS)
    s4 = slides[3]
    t4 = _table(s4)
    if t4:
        _set_cell_text(t4.cell(0, 2), f"YTD - {data.month_label} '{data.short_year}", align="ctr")
        _update_ytd_header_cell(t4.cell(0, 7), data.previous_year)
        _fill_slts_table(t4, data.sm_items)

    # Slide 5: Administrative Costs (SLTS)
    s5 = slides[4]
    t5 = _table(s5)
    if t5:
        _set_cell_text(t5.cell(0, 2), f"YTD - {data.month_label} '{data.short_year}", align="ctr")
        _update_ytd_header_cell(t5.cell(0, 7), data.previous_year)
        _fill_slts_table(t5, data.admin_items)

    # Slide 6: Other Costs/Income Impact to Net Profit (SLTS)
    s6 = slides[5]
    t6 = _table(s6)
    if t6:
        _set_cell_text(t6.cell(0, 2), f"YTD {data.month_label} '{data.short_year}", align="ctr")
        _update_ytd_header_cell(t6.cell(0, 7), data.previous_year)
        _fill_slts_table(t6, data.other_cost_items, is_other_costs=True)

    # Slide 7 & 8: Balance Sheet & Cash Flow (from uploaded BS/CF PPTX)
    if data.bscf_pptx_path and Path(data.bscf_pptx_path).exists():
        try:
            prs_bscf = Presentation(data.bscf_pptx_path)
            if len(prs_bscf.slides) >= 2:
                # Slide 1 -> Slide 7
                src_t1 = _table(prs_bscf.slides[0])
                dest_t1 = _table(slides[6])
                if src_t1 and dest_t1:
                    _copy_table_contents(src_t1, dest_t1)

                # Slide 2 -> Slide 8
                src_t2 = _table(prs_bscf.slides[1])
                dest_t2 = _table(slides[7])
                if src_t2 and dest_t2:
                    _copy_table_contents(src_t2, dest_t2)
        except Exception as e:
            logger.warning(f"Failed to copy BS/CF tables from uploaded presentation: {e}")

    # Slide 9: Active Subscribers (SLTS)
    s9 = slides[8]
    t9 = _table(s9)
    if t9:
        _set_cell_text(t9.cell(0, 2), f"{data.current_year} - {data.month_label}", align="ctr")
        _set_cell_text(t9.cell(0, 4), f"{data.previous_year} - {data.month_label}", align="ctr")


def generate_telecom_services_deck(data: TelecomServicesData, output_dir: str) -> str:
    """Generates the 9-slide Telecom Services deck and returns its file path."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Telecom Services template missing at {TEMPLATE_PATH}")

    prs = Presentation(str(TEMPLATE_PATH))
    populate_telecom_services_presentation(prs, data)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"Telecom_Services_Performance_{data.month_label}_{data.current_year}_{uuid.uuid4().hex[:8]}.pptx"
    out_path = out_dir / filename
    prs.save(str(out_path))
    logger.info(f"Generated Telecom Services presentation: {out_path}")
    return str(out_path)
