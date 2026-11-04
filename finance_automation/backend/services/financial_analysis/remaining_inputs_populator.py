"""
Populates Mobitel and Group financial sections in the Financial Analysis Report DOCX.

This module enriches the financial analysis report with:
  1. Mobitel narrative commentary — from MobitelWriteup (DOCX)
  2. Group figures (cols 1-4) in tables 4, 6, 8 — from GroupPLData (Excel)
  3. SLT PLC figures (cols 6-9 in tables 4, 6, 8 and tables 5, 7, 9) — from Telecom in GroupPLData (Excel)
  4. Mobitel figures (cols 11-14 in tables 4, 6, 8) — from Mobitel in GroupPLData (Excel)

CRITICAL ENTITY & ROUNDING RULES:
  - Figures are displayed in rounded LKR Mn.
  - Variance LKR = round(Current) - round(Prior). This ensures cross-table mathematical consistency.
  - Variance % = (Variance LKR) / abs(round(Prior)).
"""
from __future__ import annotations

import copy
import logging
import re
from typing import List, Optional

from docx import Document
from docx.oxml.ns import qn

from services.financial_analysis.group_pl_reader import (
    EntityData, EntityFigures, GroupPLData, PeriodBlock,
)
from services.financial_analysis.mobitel_writeup_reader import MobitelWriteup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text / XML helpers
# ---------------------------------------------------------------------------

def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _cells(tr) -> list:
    return tr.findall(qn("w:tc"))


def _set_text_in_para(p, text: str):
    runs = list(p.iter(qn("w:r")))
    keep = next((r for r in runs if r.find(qn("w:t")) is not None), runs[0] if runs else None)
    for r in runs:
        if r is not keep:
            r.getparent().remove(r)
    if keep is None:
        keep = p.makeelement(qn("w:r"), {})
        p.append(keep)
    for child in list(keep):
        if child.tag != qn("w:rPr"):
            keep.remove(child)
    t_el = keep.makeelement(qn("w:t"), {})
    t_el.text = text
    t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    keep.append(t_el)



FAVOURABLE, UNFAVOURABLE = "00B050", "EE0000"

_AFTER_COLOR = {qn(f"w:{tag}") for tag in (
    "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText",
    "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath")}


def _set_color(tc, color: Optional[str]):
    """Colours every run in the cell; None leaves the text in the default colour."""
    for p in tc.findall(qn("w:p")):
        p_pr = p.find(qn("w:pPr"))
        if p_pr is not None:
            p_rpr = p_pr.find(qn("w:rPr"))
            if p_rpr is not None:
                p_col = p_rpr.find(qn("w:color"))
                if p_col is not None:
                    p_rpr.remove(p_col)
    for r in tc.iter(qn("w:r")):
        r_pr = r.find(qn("w:rPr"))
        if r_pr is None:
            r_pr = r.makeelement(qn("w:rPr"), {})
            r.insert(0, r_pr)
        existing = r_pr.find(qn("w:color"))
        if existing is not None:
            r_pr.remove(existing)
        if color:
            el = r_pr.makeelement(qn("w:color"), {qn("w:val"): color})
            after = next((c for c in r_pr if c.tag in _AFTER_COLOR), None)
            if after is not None:
                after.addprevious(el)
            else:
                r_pr.append(el)


def _favour_color(diff: Optional[float], cost: bool = False, min_abs: float = 1e-6) -> Optional[str]:
    if diff is None or abs(diff) < min_abs:
        return None
    return FAVOURABLE if (diff < 0 if cost else diff > 0) else UNFAVOURABLE

def _set_cell_text(tc, value: str):
    paras = tc.findall(qn("w:p"))
    if paras:
        _set_text_in_para(paras[0], value)


def _money(value: Optional[float]) -> str:
    """Format a monetary value (LKR Mn) as a string with comma separators."""
    if value is None:
        return "-"
    rounded = round(value)
    text = f"{abs(rounded):,.0f}"
    return f"({text})" if rounded < 0 else text


def _pct(value: Optional[float]) -> str:
    """Format a percentage value."""
    if value is None:
        return "N/A"
    pct = value * 100
    text = f"{abs(pct):.1f}%"
    return f"({text})" if pct < 0 else text


# ---------------------------------------------------------------------------
# Row label -> PeriodBlock attribute mapping
# ---------------------------------------------------------------------------

_ROW_TO_ATTR = {
    "revenue":               "revenue",
    "opex":                  "opex",
    "ebitda":                "ebitda",
    "operatingprofit":       "ebit",
    "operatingprofitloss":   "ebit",
    "pbt":                   "pbt",
    "profitbeforetax":       "pbt",
    "pat":                   "npat",
    "profitaftertax":        "npat",
    "netprofitfortheperiod": "npat",
    "netprofit":             "npat",
}


# ---------------------------------------------------------------------------
# Per-section period configuration
# ---------------------------------------------------------------------------

# section_type -> (current_block_attr, prior_block_attr)
_SECTION_PERIODS = {
    "section_a": ("q_current", "q_prior"),
    "section_b": ("q_current", "q_prev"),
    "section_c": ("ytd_current", "ytd_prior"),
}

_TABLE_SECTION = {
    4: "section_a",
    6: "section_b",
    8: "section_c",
}

_SLT_TABLE_SECTION = {
    5: "section_a",
    7: "section_b",
    9: "section_c",
}


# ---------------------------------------------------------------------------
# Core table-filling function
# ---------------------------------------------------------------------------

def _fill_table_for_entity(
    tbl_el,
    col_current: int,
    col_prior: int,
    col_var_lkr: int,
    col_var_pct: int,
    current_block: PeriodBlock,
    prior_block: PeriodBlock,
    warnings: List[str],
):
    """
    Fill one entity's columns in a table.
    Computes exact displayed variance: round(current) - round(prior).
    """
    rows = tbl_el.findall(qn("w:tr"))
    for tr in rows[2:]:   # skip header rows
        cells = _cells(tr)
        if not cells:
            continue
        label = _norm(_text(cells[0]))
        attr = _ROW_TO_ATTR.get(label)
        if attr is None:
            continue

        raw_cur = getattr(current_block, attr, None)
        raw_pri = getattr(prior_block, attr, None)

        if raw_cur is None and raw_pri is None:
            continue

        cur_rnd = round(raw_cur) if raw_cur is not None else None
        pri_rnd = round(raw_pri) if raw_pri is not None else None

        # Displayed variance = rounded current - rounded prior
        var_lkr = (cur_rnd - pri_rnd) if (cur_rnd is not None and pri_rnd is not None) else None
        var_pct = (var_lkr / abs(pri_rnd)) if (var_lkr is not None and pri_rnd) else None

        n = len(cells)
        col = _favour_color(var_lkr, cost=(label == "opex")) if var_lkr is not None else None
        if n > col_current and cur_rnd is not None:
            _set_cell_text(cells[col_current], _money(cur_rnd))
        if n > col_prior and pri_rnd is not None:
            _set_cell_text(cells[col_prior], _money(pri_rnd))
        if n > col_var_lkr and var_lkr is not None:
            _set_cell_text(cells[col_var_lkr], _money(var_lkr))
            _set_color(cells[col_var_lkr], col)
        if n > col_var_pct and var_pct is not None:
            _set_cell_text(cells[col_var_pct], _pct(var_pct))
            _set_color(cells[col_var_pct], col)


def populate_group_tables(
    doc: Document,
    group_pl_data: GroupPLData,
    warnings: List[str],
):
    """
    Fills Group figures (cols 1-4), SLT PLC figures (cols 6-9), and Mobitel figures (cols 11-14)
    in the 15-column Group tables (doc.tables indices 4, 6, 8), as well as SLT PLC 5-column
    tables (indices 5, 7, 9) using the authoritative Telecom column.
    """
    group_ed   = group_pl_data.entity_data.get("Group")
    telecom_ed = group_pl_data.entity_data.get("Telecom")
    mobitel_ed = group_pl_data.entity_data.get("Mobitel")

    if not group_ed and not mobitel_ed:
        warnings.append("Neither 'Group' nor 'Mobitel' entity found in GroupPLData.")
        return

    # 1. Populate 15-col Group tables (4, 6, 8)
    for tbl_idx, section_type in _TABLE_SECTION.items():
        if tbl_idx >= len(doc.tables):
            continue

        tbl_el = doc.tables[tbl_idx]._element
        first_rows = tbl_el.findall(qn("w:tr"))
        if not first_rows:
            continue
        sample_cells = _cells(first_rows[0])
        if len(sample_cells) < 10:
            continue

        cur_blk_attr, pri_blk_attr = _SECTION_PERIODS[section_type]

        # Fill Group entity (cols 1, 2, 3, 4)
        if group_ed:
            _fill_table_for_entity(
                tbl_el,
                col_current=1, col_prior=2, col_var_lkr=3, col_var_pct=4,
                current_block=getattr(group_ed, cur_blk_attr),
                prior_block=getattr(group_ed, pri_blk_attr),
                warnings=warnings,
            )

        # Fill SLT PLC (Telecom) entity (cols 6, 7, 8, 9)
        if telecom_ed:
            _fill_table_for_entity(
                tbl_el,
                col_current=6, col_prior=7, col_var_lkr=8, col_var_pct=9,
                current_block=getattr(telecom_ed, cur_blk_attr),
                prior_block=getattr(telecom_ed, pri_blk_attr),
                warnings=warnings,
            )

        # Fill Mobitel entity (cols 11, 12, 13, 14)
        if mobitel_ed:
            _fill_table_for_entity(
                tbl_el,
                col_current=11, col_prior=12, col_var_lkr=13, col_var_pct=14,
                current_block=getattr(mobitel_ed, cur_blk_attr),
                prior_block=getattr(mobitel_ed, pri_blk_attr),
                warnings=warnings,
            )

    # 2. Populate SLT PLC 5-col tables (5, 7, 9)
    if telecom_ed:
        for tbl_idx, section_type in _SLT_TABLE_SECTION.items():
            if tbl_idx >= len(doc.tables):
                continue
            tbl_el = doc.tables[tbl_idx]._element
            cur_blk_attr, pri_blk_attr = _SECTION_PERIODS[section_type]
            _fill_table_for_entity(
                tbl_el,
                col_current=1, col_prior=2, col_var_lkr=3, col_var_pct=4,
                current_block=getattr(telecom_ed, cur_blk_attr),
                prior_block=getattr(telecom_ed, pri_blk_attr),
                warnings=warnings,
            )


# ---------------------------------------------------------------------------
# Mobitel narrative population
# ---------------------------------------------------------------------------

def _find_mobitel_subsection(doc: Document, section_norm_key: str, search_start: int = 0):
    paras = doc.paragraphs
    n = len(paras)

    sec_idx = -1
    for i in range(search_start, n):
        if section_norm_key in _norm(paras[i].text):
            sec_idx = i
            break
    if sec_idx == -1:
        return -1, n

    mob_idx = -1
    for i in range(sec_idx, n):
        if _norm(paras[i].text) == "mobitel":
            mob_idx = i
            break
    if mob_idx == -1:
        return -1, n

    end_idx = n
    stop_norms = {"sltplc", "liquidityandoperatingcashflow"}
    for i in range(mob_idx + 1, n):
        t = _norm(paras[i].text)
        if t in stop_norms:
            end_idx = i
            break
        raw = paras[i].text.strip()
        if len(raw) < 120 and (
            "performanceof" in t or t.startswith("key") or t.startswith("annex")
        ):
            end_idx = i
            break

    return mob_idx, end_idx


def _populate_mobitel_paragraphs(
    doc: Document,
    section_norm_key: str,
    narrative: str,
    section_label: str,
    warnings: List[str],
    search_start: int = 0,
) -> int:
    if not narrative:
        return -1

    mob_idx, end_idx = _find_mobitel_subsection(doc, section_norm_key, search_start)
    if mob_idx == -1:
        warnings.append(
            f"Mobitel sub-section not found in '{section_label}'. Narrative not populated."
        )
        return -1

    paras = doc.paragraphs
    target_paras = [
        paras[k] for k in range(mob_idx + 1, end_idx)
        if paras[k].text.strip()
    ]

    chunks = [c.strip() for c in narrative.split("\n\n") if c.strip()]
    if not chunks:
        return mob_idx

    # Update existing paragraphs or append new ones
    for i, chunk in enumerate(chunks):
        if i < len(target_paras):
            _set_text_in_para(target_paras[i]._element, chunk)
        else:
            if target_paras:
                new_p = copy.deepcopy(target_paras[-1]._element)
                _set_text_in_para(new_p, chunk)
                target_paras[-1]._element.addnext(new_p)

    # Clear excess paragraphs if fewer chunks than template paragraphs
    if len(chunks) < len(target_paras):
        for extra_p in target_paras[len(chunks):]:
            extra_el = extra_p._element
            parent = extra_el.getparent()
            if parent is not None:
                parent.remove(extra_el)

    logger.info(
        f"Populated Mobitel commentary in '{section_label}' ({len(chunks)} chunk(s))."
    )
    return mob_idx


def populate_mobitel_narratives(
    doc: Document,
    mobitel_writeup: MobitelWriteup,
    warnings: List[str],
):
    section_map = [
        ("executivesummary",
         mobitel_writeup.exec_summary, "Executive Summary"),
        ("performanceofthecurrentquarteragainsttheprecedingyear",
         mobitel_writeup.section_a_yoy, "Section A (YoY)"),
        ("performanceofthecurrentquarteragainsttheprecedingquarter",
         mobitel_writeup.section_b_qoq, "Section B (QoQ)"),
        ("performanceofthecurrentyearagainsttheprecedingyear",
         mobitel_writeup.section_c_ytd, "Section C (YTD)"),
        ("performanceofthecurrentquarteractualsagainstthebudget",
         mobitel_writeup.section_d_budget, "Section D (Budget)"),
    ]

    search_start = 0
    for norm_key, narrative, label in section_map:
        if not narrative:
            warnings.append(f"No Mobitel narrative for '{label}' — section left unchanged.")
            continue
        result_idx = _populate_mobitel_paragraphs(
            doc, norm_key, narrative, label, warnings, search_start=search_start
        )
        if result_idx > 0:
            search_start = result_idx


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def populate_remaining_inputs(
    doc: Document,
    mobitel_writeup: Optional[MobitelWriteup],
    group_pl_data: Optional[GroupPLData],
    quarter=None,
) -> List[str]:
    """
    Enriches the output document with Mobitel narratives and Group/SLT/Mobitel P&L figures.
    Called after report_generator has prepared the base document.
    Returns a list of warnings.
    """
    warnings: List[str] = []

    if mobitel_writeup:
        logger.info("Populating Mobitel narrative sections from write-up...")
        populate_mobitel_narratives(doc, mobitel_writeup, warnings)
        if mobitel_writeup.warnings:
            warnings.extend(f"[Write-up] {w}" for w in mobitel_writeup.warnings)

    if group_pl_data:
        logger.info("Populating Group and subsidiary figures in tables...")
        populate_group_tables(doc, group_pl_data, warnings)
        if group_pl_data.warnings:
            warnings.extend(f"[Group P&L] {w}" for w in group_pl_data.warnings)

    if warnings:
        logger.warning(
            f"populate_remaining_inputs produced {len(warnings)} warning(s)."
        )
    return warnings
