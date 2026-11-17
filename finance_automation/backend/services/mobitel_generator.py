"""
Generates the 10-slide Mobitel PowerPoint deck from MobitelData.
"""
import copy
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from pptx import Presentation
from pptx.oxml.ns import qn

from services.board_pack_classifier import _norm
from services.mobitel_reader import MobitelData, FinancialLineItem
from utils.logger import logger

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "board_pack_templates" / "mobitel_template.pptx"


def _round(value: float, places: int = 0) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def format_amount(value: Optional[float], decimals: int = 0, fmt: str = "", is_var: bool = False) -> str:
    if value is None:
        return ""
    if value == 0:
        return "-"

    # Preserve 2 decimal places when specified in source format (for actuals/prior year, not variance)
    if not is_var and (decimals > 0 or (".00" in fmt)):
        rounded = round(abs(value), 2)
        text = f"{rounded:,.2f}"
        if value < 0:
            return f"({text})"
        return text

    # Standard integer formatting
    rounded = round(abs(value))
    text = f"{rounded:,.0f}"

    if value < 0:
        if rounded == 0:
            if fmt == "0":
                return "0"
            return "(0)"
        return f"({text})"
    return text


def format_pct(value: Optional[float], decimals: int = 0) -> str:
    if value is None:
        return "-"
    if value == 0 or abs(value) < 0.00001:
        return "-"
    scaled = round(abs(value) * 100, decimals)
    text = f"{scaled:.{decimals}f}%"
    return f"({text})" if value < 0 else text


def format_count(value: Optional[int]) -> str:
    if value is None:
        return ""
    if value == 0:
        return "-"
    text = f"{abs(value):,}"
    return f"({text})" if value < 0 else text


def _set_cell_text(cell, text: Optional[str], align: Optional[str] = "r", clear_only: bool = False):
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

    if text is None or text == "" or clear_only:
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


def _table(slide):
    for shape in slide.shapes:
        if shape.has_table:
            return shape.table
    return None


def _find_item_by_label(items: List[FinancialLineItem], target_label: str) -> Optional[FinancialLineItem]:
    target_norm = _norm(target_label)
    if not target_norm:
        return None

    # 1. Exact match first
    for it in items:
        if _norm(it.label) == target_norm:
            return it

    # 2. Specialized distinctions: Net Interest Cost vs Interest Cost
    if target_norm == "netinterestcost":
        for it in items:
            if "netinterestcost" in _norm(it.label):
                return it
        return None

    if target_norm == "interestcost":
        for it in items:
            it_n = _norm(it.label)
            if "interestcost" in it_n and "net" not in it_n:
                return it
        return None

    # 3. Substring match only for length >= 4
    for it in items:
        item_norm = _norm(it.label)
        if len(item_norm) >= 4 and len(target_norm) >= 4:
            if item_norm in target_norm or target_norm in item_norm:
                return it
    return None


def _fill_pnl_table(table, items: List[FinancialLineItem], has_col1_empty: bool, data: MobitelData):
    """
    Fills P&L breakdown table (Revenue, Direct Costs, S&M, Admin, Other Costs).
    """
    col_offset = 1 if has_col1_empty else 0

    # Fill data rows starting at row 2
    for r_idx in range(2, len(table.rows)):
        row_lbl = table.cell(r_idx, 0).text.strip()
        if not row_lbl:
            continue
        matched = _find_item_by_label(items, row_lbl)
        if not matched:
            continue

        # Month Act, LY, Vari, Vari%
        _set_cell_text(table.cell(r_idx, 1 + col_offset), format_amount(matched.month_act, fmt=matched.month_act_fmt))
        _set_cell_text(table.cell(r_idx, 2 + col_offset), format_amount(matched.month_ly, fmt=matched.month_ly_fmt))
        _set_cell_text(table.cell(r_idx, 3 + col_offset), format_amount(matched.month_var, fmt=matched.month_var_fmt, is_var=True))
        _set_cell_text(table.cell(r_idx, 4 + col_offset), format_pct(matched.month_pct, 0))

        # YTD Act, LY, Vari, Vari%
        _set_cell_text(table.cell(r_idx, 6 + col_offset), format_amount(matched.ytd_act, fmt=matched.ytd_act_fmt))
        _set_cell_text(table.cell(r_idx, 7 + col_offset), format_amount(matched.ytd_ly, fmt=matched.ytd_ly_fmt))
        _set_cell_text(table.cell(r_idx, 8 + col_offset), format_amount(matched.ytd_var, fmt=matched.ytd_var_fmt, is_var=True))
        _set_cell_text(table.cell(r_idx, 9 + col_offset), format_pct(matched.ytd_pct, 0))


def populate_mobitel_presentation(prs: Presentation, data: MobitelData):
    """Populates an open mobitel presentation with MobitelData."""
    slides = prs.slides

    # Slide 1: Title – update subtitle text while preserving bold/blue/size formatting
    s1 = slides[0]
    for shape in s1.shapes:
        if shape.has_text_frame:
            text = shape.text_frame.text
            if "YTD" in text or "202" in text:
                # Preserve run-level formatting by updating text nodes directly
                new_text = f"YTD {data.month_label} {data.current_year}"
                tf = shape.text_frame
                # Flatten all runs in para[0] into a single run with preserved rPr
                para = tf.paragraphs[0]
                runs = para.runs
                if runs:
                    # Keep the first run's rPr (bold, color, size) and clear the rest
                    first_run = runs[0]
                    first_run.text = new_text
                    # Remove any extra runs
                    for extra_run in list(para._p.findall(qn("a:r")))[1:]:
                        para._p.remove(extra_run)
                else:
                    # Fallback: just set text (may lose formatting, but rare)
                    tf.paragraphs[0]._p  # ensure para exists
                    shape.text_frame.text = new_text

    # Slide 2: Revenue (11 cols: col 1 is empty)
    s2 = slides[1]
    t2 = _table(s2)
    if t2:
        _set_cell_text(t2.cell(0, 2), f"Month - {data.month_label}", align="ctr")
        _set_cell_text(t2.cell(0, 7), f"YTD-{data.month_label}", align="ctr")
        _set_cell_text(t2.cell(1, 2), str(data.current_year), align="ctr")
        _set_cell_text(t2.cell(1, 3), str(data.previous_year), align="ctr")
        _set_cell_text(t2.cell(1, 7), str(data.current_year), align="ctr")
        _set_cell_text(t2.cell(1, 8), str(data.previous_year), align="ctr")
        _fill_pnl_table(t2, data.revenue_items, has_col1_empty=True, data=data)

    # Slide 3: Direct Costs (11 cols: col 1 is empty)
    s3 = slides[2]
    t3 = _table(s3)
    if t3:
        _set_cell_text(t3.cell(0, 2), f"Month - {data.month_label}", align="ctr")
        _set_cell_text(t3.cell(0, 7), f"YTD {data.month_label}", align="ctr")
        _set_cell_text(t3.cell(1, 2), str(data.current_year), align="ctr")
        _set_cell_text(t3.cell(1, 3), str(data.previous_year), align="ctr")
        _set_cell_text(t3.cell(1, 7), str(data.current_year), align="ctr")
        _set_cell_text(t3.cell(1, 8), str(data.previous_year), align="ctr")
        _fill_pnl_table(t3, data.direct_cost_items, has_col1_empty=True, data=data)

    # Slide 4: Sales & Marketing (10 cols: col 1 has data)
    s4 = slides[3]
    t4 = _table(s4)
    if t4:
        _set_cell_text(t4.cell(0, 1), f"Month -{data.month_label}", align="ctr")
        _set_cell_text(t4.cell(0, 6), f"YTD-{data.month_label}", align="ctr")
        _set_cell_text(t4.cell(1, 1), str(data.current_year), align="ctr")
        _set_cell_text(t4.cell(1, 2), str(data.previous_year), align="ctr")
        _set_cell_text(t4.cell(1, 6), str(data.current_year), align="ctr")
        _set_cell_text(t4.cell(1, 7), str(data.previous_year), align="ctr")
        _fill_pnl_table(t4, data.sm_items, has_col1_empty=False, data=data)

    # Slide 5: Administrative Expenditure (10 cols: col 1 has data)
    s5 = slides[4]
    t5 = _table(s5)
    if t5:
        _set_cell_text(t5.cell(0, 1), f"Month -{data.month_label}", align="ctr")
        _set_cell_text(t5.cell(0, 6), f"YTD {data.month_label} {data.short_year}", align="ctr")
        _set_cell_text(t5.cell(1, 1), str(data.current_year), align="ctr")
        _set_cell_text(t5.cell(1, 2), str(data.previous_year), align="ctr")
        _set_cell_text(t5.cell(1, 6), str(data.current_year), align="ctr")
        _set_cell_text(t5.cell(1, 7), str(data.previous_year), align="ctr")
        _fill_pnl_table(t5, data.admin_items, has_col1_empty=False, data=data)

    # Slide 6: Other Costs / Net Profit Impact (10 cols: col 1 has data)
    s6 = slides[5]
    t6 = _table(s6)
    if t6:
        _set_cell_text(t6.cell(0, 1), f"Month -{data.month_label}", align="ctr")
        _set_cell_text(t6.cell(0, 6), f"YTD {data.month_label} {data.short_year}", align="ctr")
        _set_cell_text(t6.cell(1, 1), str(data.current_year), align="ctr")
        _set_cell_text(t6.cell(1, 2), str(data.previous_year), align="ctr")
        _set_cell_text(t6.cell(1, 6), str(data.current_year), align="ctr")
        _set_cell_text(t6.cell(1, 7), str(data.previous_year), align="ctr")
        _fill_pnl_table(t6, data.other_cost_items, has_col1_empty=False, data=data)

    # Slide 7: Balance Sheet (3 cols)
    s7 = slides[6]
    t7 = _table(s7)
    if t7:
        _set_cell_text(t7.cell(0, 1), data.bs_current_header, align="ctr")
        _set_cell_text(t7.cell(0, 2), data.bs_prev_header, align="ctr")
        for r_idx in range(1, len(t7.rows)):
            row_lbl = t7.cell(r_idx, 0).text.strip()
            norm_r = _norm(row_lbl)
            if not norm_r:
                # Blank separator row: keep cells completely blank
                _set_cell_text(t7.cell(r_idx, 1), "", clear_only=True)
                _set_cell_text(t7.cell(r_idx, 2), "", clear_only=True)
                continue
            for it in data.balance_sheet_items:
                norm_it = _norm(it.label)
                if norm_it == norm_r or (len(norm_it) >= 4 and len(norm_r) >= 4 and (norm_it in norm_r or norm_r in norm_it)):
                    _set_cell_text(t7.cell(r_idx, 1), format_amount(it.current))
                    _set_cell_text(t7.cell(r_idx, 2), format_amount(it.previous))
                    break

    # Slide 8: Cash Flow Statement (3 cols)
    s8 = slides[7]
    t8 = _table(s8)
    if t8:
        _set_cell_text(t8.cell(0, 1), data.cf_current_header, align="ctr")
        _set_cell_text(t8.cell(0, 2), data.cf_prev_header, align="ctr")
        for r_idx in range(1, len(t8.rows)):
            row_lbl = t8.cell(r_idx, 0).text.strip()
            norm_r = _norm(row_lbl)
            if not norm_r:
                _set_cell_text(t8.cell(r_idx, 1), "", clear_only=True)
                _set_cell_text(t8.cell(r_idx, 2), "", clear_only=True)
                continue
            for it in data.cash_flow_items:
                norm_it = _norm(it.label)
                if norm_it == norm_r or (len(norm_it) >= 4 and len(norm_r) >= 4 and (norm_it in norm_r or norm_r in norm_it)):
                    _set_cell_text(t8.cell(r_idx, 1), format_amount(it.current))
                    _set_cell_text(t8.cell(r_idx, 2), format_amount(it.previous))
                    break

    # Slide 9: Subscribers (5 cols)
    s9 = slides[8]
    t9 = _table(s9)
    if t9:
        _set_cell_text(t9.cell(0, 2), str(data.current_year), align="ctr")
        _set_cell_text(t9.cell(0, 4), str(data.previous_year), align="ctr")
        _set_cell_text(t9.cell(1, 2), data.month_label, align="ctr")
        _set_cell_text(t9.cell(1, 4), data.month_label, align="ctr")

        prepaid = data.subscribers.get("prepaid")
        if prepaid and prepaid[0] is not None:
            _set_cell_text(t9.cell(3, 2), format_count(prepaid[0]), align="ctr")
            _set_cell_text(t9.cell(3, 4), format_count(prepaid[1]), align="ctr")

        postpaid = data.subscribers.get("postpaid")
        if postpaid and postpaid[0] is not None:
            _set_cell_text(t9.cell(5, 2), format_count(postpaid[0]), align="ctr")
            _set_cell_text(t9.cell(5, 4), format_count(postpaid[1]), align="ctr")

    # Slide 10: ARPU (5 cols)
    s10 = slides[9]
    t10 = _table(s10)
    if t10:
        _set_cell_text(t10.cell(0, 2), str(data.current_year), align="ctr")
        _set_cell_text(t10.cell(0, 4), str(data.previous_year), align="ctr")
        _set_cell_text(t10.cell(1, 2), data.month_label, align="ctr")
        _set_cell_text(t10.cell(1, 4), data.month_label, align="ctr")

        prepaid_arpu = data.arpu.get("prepaid")
        if prepaid_arpu:
            _set_cell_text(t10.cell(3, 2), format_amount(prepaid_arpu[0]))
            _set_cell_text(t10.cell(3, 4), format_amount(prepaid_arpu[1]))

        postpaid_arpu = data.arpu.get("postpaid")
        if postpaid_arpu:
            _set_cell_text(t10.cell(5, 2), format_amount(postpaid_arpu[0]))
            _set_cell_text(t10.cell(5, 4), format_amount(postpaid_arpu[1]))

        blended_arpu = data.arpu.get("blended")
        if blended_arpu:
            _set_cell_text(t10.cell(7, 2), format_amount(blended_arpu[0]))
            _set_cell_text(t10.cell(7, 4), format_amount(blended_arpu[1]))


def generate_mobitel_deck(data: MobitelData, output_dir: str) -> str:
    """Generates the 10-slide Mobitel presentation and returns its file path."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Mobitel template missing at {TEMPLATE_PATH}")

    prs = Presentation(str(TEMPLATE_PATH))
    populate_mobitel_presentation(prs, data)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"Mobitel_Performance_{data.month_label}_{data.current_year}_{uuid.uuid4().hex[:8]}.pptx"
    out_path = out_dir / filename
    prs.save(str(out_path))
    logger.info(f"Generated Mobitel presentation: {out_path}")
    return str(out_path)
