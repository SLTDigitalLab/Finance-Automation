"""
Writes the quarterly Financial Analysis Report (Word) in Finance's exact format.

The template is Finance's own quarterly report (matching Output file_Q2 2026 Analysis.docx).
The generator preserves the entire layout, formatting, tables, and structure of the reference
document:
  - Executive Summary (SLT Group, SLT PLC populated from TB, Mobitel)
  - Financial Statistics – SLT PLC (Financial Summary and Key Ratios updated with actuals)
  - Operational Statistics – SLT PLC (Key Drivers & Capacity vs Utilization tables preserved)
  - Section (A) Quarter vs same quarter last year (15-col Group table with SLT PLC populated,
    5-col SLT PLC table populated, charts & commentary, Mobitel commentary)
  - Section (B) Quarter vs preceding quarter (15-col Group table, 5-col SLT PLC table, commentary, Mobitel)
  - Section (C) YTD vs preceding year's YTD (15-col Group table, 5-col SLT PLC table, commentary,
    Liquidity & Cashflow table, Borrowings table, Interest cost table, Mobitel commentary)
  - Section (D) Actuals vs Budget (SLT PLC table with actuals, budget note & commentary, Mobitel)
  - Key Projects Info – SLT PLC (FTTH Service-wise and RTOM-wise utilization tables preserved)
  - Annexure (i) – Borrowings Re-payment Schedule (preserved)
  - Annexure (ii) – Account-level variance drivers (GL drivers for Revenue and Opex across YoY, QoQ, YTD)
  - Sections to be completed by Finance & Data notes
"""
import copy
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.shared import Cm
from docx.text.paragraph import Paragraph

from services.financial_analysis import commentary
from services.financial_analysis.charts import trend_chart
from services.financial_analysis.commentary import money, percent
from services.financial_analysis.pl_engine import Comparison, FinancialAnalysis, MonthFigures
from services.financial_analysis.periods import Period, Quarter
from utils.logger import logger

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "financial_analysis_templates" / "financial_analysis_template.docx"
ENTITY = "SLT PLC"
DRIVER_ROWS = 8
FAVOURABLE, UNFAVOURABLE = "00B050", "EE0000"   # the template's green / red for growth %
DRIVER_COLUMNS = [3900, 1250, 1250, 1100, 1100]  # twips; a wider account column for the annexure

MANUAL_SECTIONS = [
    "SLT Group and Mobitel figures and commentary (the trial balance covers SLT PLC only)",
    "Financial Statistics items not in the P&L mapping: Gross Profit, EPS, Debt/Equity, ROE, Capex, "
    "free cash flows, staff cost to revenue and the balance sheet ratios",
    "Operational Statistics – SLT PLC (customer base, ARPU, capacity vs utilization)",
    "Liquidity and Operating Cashflow, Borrowings and Interest cost tables",
    "Key Projects Info – FTTH port utilization and FTTH active, suspended and churn customers",
    "Annexure (i) – Borrowings re-payment schedule",
    "Business reasons behind each movement (e.g. tariff revisions, salary increments)",
]


class ReportTemplateError(RuntimeError):
    """The Word template is missing a part the generator copies."""


@dataclass
class ReportInputs:
    analysis: FinancialAnalysis
    trend: List[MonthFigures]
    data_notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Labels


def _short(period: Period) -> str:
    return f"{period.label[:3]}’{period.year % 100:02d}"


def _q_short(q: Quarter) -> str:
    return f"Q{q.quarter}’{q.year % 100:02d}"


def _ordinal(n: int) -> str:
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")


@dataclass
class SectionSpec:
    letter: str
    title: str
    comparison_key: str
    current_label: str          # in sentences, e.g. "Q2’26"
    base_label: str
    period_phrase: str          # ends the revenue / opex sentences
    header_current: Sequence[str]   # table header lines
    header_base: Sequence[str]
    charts: bool = False


def _section_specs(q: Quarter) -> List[SectionSpec]:
    ly, prev = q.same_quarter_last_year(), q.previous()
    end, ly_end = q.end, ly.end
    return [
        SectionSpec(
            "A", f"Performance of the current quarter against the preceding year corresponding quarter "
                 f"({_q_short(q)} Vs {_q_short(ly)})",
            "quarter_vs_last_year", _q_short(q), _q_short(ly),
            f"in {_q_short(q)} compared to {_q_short(ly)}",
            [f"Q{q.quarter}", str(q.year)], [f"Q{ly.quarter}", str(ly.year)], charts=True),
        SectionSpec(
            "B", f"Performance of the current quarter against the preceding quarter "
                 f"({_q_short(q)} vs {_q_short(prev)})",
            "quarter_vs_previous", _q_short(q), _q_short(prev),
            f"in {_q_short(q)} compared to the preceding quarter ({_q_short(prev)})",
            [f"Q{q.quarter}", str(q.year)], [f"Q{prev.quarter}", str(prev.year)]),
        SectionSpec(
            "C", f"Performance of the current year against the preceding year "
                 f"(YTD {_short(end)} Vs YTD {_short(ly_end)})",
            "ytd_vs_last_year", f"YTD {_short(end)}", f"YTD {_short(ly_end)}",
            f"for YTD {_short(end)} compared to the corresponding period of the previous year",
            ["YTD", _short(end)], ["YTD", _short(ly_end)]),
    ]


# ---------------------------------------------------------------------------
# XML helpers


def _norm(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def _set_text(p, text: str):
    """Replaces a paragraph's text, keeping its paragraph formatting and its first run's formatting."""
    runs = list(p.iter(qn("w:r")))
    keep = next((r for r in runs if r.find(qn("w:t")) is not None), runs[0] if runs else None)
    for r in runs:
        if r is not keep:
            r.getparent().remove(r)
    for tag in ("w:hyperlink", "w:ins", "w:smartTag", "w:proofErr", "w:bookmarkStart", "w:bookmarkEnd"):
        for el in list(p.iter(qn(tag))):
            if el.getparent() is not None and (keep is None or keep not in el.iter()):
                el.getparent().remove(el)
    if keep is None:
        keep = p.makeelement(qn("w:r"), {})
        p.append(keep)
    for child in list(keep):
        if child.tag != qn("w:rPr"):
            keep.remove(child)
    t = keep.makeelement(qn("w:t"), {})
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    keep.append(t)


def _set_cell(tc, *lines: str):
    paragraphs = tc.findall(qn("w:p"))
    for i, line in enumerate(lines):
        if i >= len(paragraphs):
            new = copy.deepcopy(paragraphs[-1])
            paragraphs[-1].addnext(new)
            paragraphs.append(new)
        _set_text(paragraphs[i], line)
    for extra in paragraphs[max(len(lines), 1):]:
        tc.remove(extra)


def _cells(tr) -> list:
    return tr.findall(qn("w:tc"))


def _set_color(tc, color: Optional[str]):
    """Colours every run in the cell; None leaves the text in the default colour."""
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
            r_pr.append(el)


def _favour_color(diff: float, cost: bool) -> Optional[str]:
    if abs(diff) < 0.5:
        return None
    return FAVOURABLE if (diff < 0 if cost else diff > 0) else UNFAVOURABLE


def _set_column_widths(tbl, widths: Sequence[int]):
    """Fixed column widths in twips (grid, every cell, and the table width)."""
    for col, width in zip(tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol")), widths):
        col.set(qn("w:w"), str(width))
    for tr in tbl.findall(qn("w:tr")):
        col = 0
        for tc in _cells(tr):
            tc_pr = tc.find(qn("w:tcPr"))
            if tc_pr is None:
                tc_pr = tc.makeelement(qn("w:tcPr"), {})
                tc.insert(0, tc_pr)
            span_el = tc_pr.find(qn("w:gridSpan"))
            span = int(span_el.get(qn("w:val"))) if span_el is not None else 1
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = tc_pr.makeelement(qn("w:tcW"), {})
                tc_pr.insert(0, tc_w)
            tc_w.set(qn("w:w"), str(sum(widths[col:col + span])))
            tc_w.set(qn("w:type"), "dxa")
            col += span
    tbl_pr = tbl.find(qn("w:tblPr"))
    for tag, attrs in (("w:tblW", {qn("w:w"): str(sum(widths)), qn("w:type"): "dxa"}),
                       ("w:tblLayout", {qn("w:type"): "fixed"})):
        old = tbl_pr.find(qn(tag))
        if old is not None:
            tbl_pr.remove(old)
        tbl_pr.append(tbl_pr.makeelement(qn(tag), attrs))


# ---------------------------------------------------------------------------
# P&L Row Mappings


IS_ROWS = {
    "revenue": lambda l: l["revenue"],
    "opex": lambda l: -l["operating_costs"],
    "ebitda": lambda l: l["ebitda"],
    "operatingprofit": lambda l: l["operating_profit"],
    "operatingprofitloss": lambda l: l["operating_profit"],
    "pbt": lambda l: l["profit_before_tax"],
    "pat": lambda l: l["profit_after_tax"],
}


def _growth(cur: float, base: float):
    diff = cur - base
    return diff, (diff / abs(base) if base else None)


def _margin_change(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    return cur - base if cur is not None and base is not None else None


# ---------------------------------------------------------------------------
# Table Filling Helpers


def _fill_income_statement(tbl, comparison: Comparison, spec: SectionSpec):
    rows = tbl.findall(qn("w:tr"))
    head = _cells(rows[0])
    _set_cell(head[1], *spec.header_current)
    _set_cell(head[2], *spec.header_base)
    cur, base = comparison.current.lines, comparison.base.lines
    for tr in rows[2:]:
        cells = _cells(tr)
        getter = IS_ROWS.get(_norm(_text(cells[0])))
        if getter is None:
            continue
        diff, pct = _growth(getter(cur), getter(base))
        for tc, value in zip(cells[1:], [money(getter(cur)), money(getter(base)), money(diff), percent(pct)]):
            _set_cell(tc, value)
        _set_color(cells[-1], _favour_color(diff, cost=_norm(_text(cells[0])) == "opex"))


def _update_group_table(tbl, comparison: Comparison, spec: SectionSpec, q: Quarter):
    """Updates the 15-column group table with SLT PLC calculated actuals in columns 6..9."""
    rows = tbl.findall(qn("w:tr"))
    head0 = _cells(rows[0])
    if len(head0) >= 11:
        _set_cell(head0[1], f"{spec.current_label} Group")
        _set_cell(head0[2], f"{spec.base_label} Group")
        _set_cell(head0[5], f"{spec.current_label} SLT PLC")
        _set_cell(head0[6], f"{spec.base_label} SLT PLC")
        _set_cell(head0[9], f"{spec.current_label} Mobitel")
        _set_cell(head0[10], f"{spec.base_label} Mobitel")

    cur, base = comparison.current.lines, comparison.base.lines
    for tr in rows[2:]:
        cells = _cells(tr)
        label = _norm(_text(cells[0]))
        getter = IS_ROWS.get(label)
        if getter is None:
            continue
        cur_val, base_val = getter(cur), getter(base)
        diff, pct = _growth(cur_val, base_val)
        _set_cell(cells[6], money(cur_val))
        _set_cell(cells[7], money(base_val))
        _set_cell(cells[8], money(diff))
        _set_cell(cells[9], percent(pct))
        _set_color(cells[9], _favour_color(diff, cost=(label == "opex")))


def _fill_rows(tbl, header_rows: int, values: List[List[str]], colors: Sequence[Optional[str]] = ()):
    """Replaces the data rows with one copy of a template data row per entry in `values`."""
    rows = tbl.findall(qn("w:tr"))
    protos = rows[header_rows:]
    middle, last = protos[min(1, len(protos) - 1)], protos[-1]
    for tr in protos:
        tbl.remove(tr)
    for i, row_values in enumerate(values):
        tr = copy.deepcopy(last if i == len(values) - 1 else middle)
        for tc, value in zip(_cells(tr), row_values):
            _set_cell(tc, value)
        if i < len(colors):
            _set_color(_cells(tr)[-1], colors[i])
        tbl.append(tr)


def _driver_rows(comparison: Comparison, line: str, cost: bool):
    """Table rows and their % colours for the accounts that moved a line the most."""
    rows, colors = [], []
    for d in comparison.drivers(line, limit=DRIVER_ROWS):
        sign = -1 if cost else 1
        cur, base = sign * d.current, sign * d.base
        diff, pct = _growth(cur, base)
        rows.append([f"{d.account} {d.name.strip()}", money(cur), money(base), money(diff), percent(pct)])
        colors.append(_favour_color(diff, cost))
    return rows, colors


def _update_financial_summary(tbl, ytd: Comparison, end: Period, ly_end: Period):
    """Fills the P&L lines supported by the trial balance, keeping other rows intact."""
    rows = tbl.findall(qn("w:tr"))
    head = _cells(rows[1])
    _set_cell(head[1], _short(end))
    _set_cell(head[2], _short(ly_end))
    cur, base = ytd.current, ytd.base
    amounts = {
        "revenue": "revenue", "operatingprofit": "operating_profit",
        "profitbeforetax": "profit_before_tax", "profitaftertax": "profit_after_tax",
    }
    margins = {
        "ebitdamargin": "ebitda", "operatingprofitmargin": "operating_profit",
        "pbtmargin": "profit_before_tax", "patmargin": "profit_after_tax",
    }
    for tr in rows[2:]:
        cells = _cells(tr)
        label = _norm(_text(cells[0]))
        if not label:
            continue
        if label in amounts:
            key = amounts[label]
            _, pct = _growth(cur.lines[key], base.lines[key])
            _set_cell(cells[1], money(cur.lines[key]))
            _set_cell(cells[2], money(base.lines[key]))
            _set_cell(cells[3], percent(pct))
        elif label in margins:
            key = margins[label]
            c, b = cur.margin(key), base.margin(key)
            _set_cell(cells[1], percent(c))
            _set_cell(cells[2], percent(b))
            _set_cell(cells[3], percent(_margin_change(c, b)))


def _update_key_ratios(tbl, ytd: Comparison, end: Period, ly_end: Period):
    """Updates key ratios supported by the trial balance, keeping other rows intact."""
    rows = tbl.findall(qn("w:tr"))
    head = _cells(rows[2])[1:]
    for tc, text in zip(head, [_short(end), _short(ly_end), _short(end)]):
        _set_cell(tc, text)
    cur, base = ytd.current, ytd.base
    _, growth = _growth(cur.lines["revenue"], base.lines["revenue"])

    def coverage(pl):
        interest = -pl.lines["interest_expenses"]
        return f"{pl.lines['operating_profit'] / interest:.1f}" if interest > 0 else "N/A"

    ratios = {
        "revenuegrowthyoy": [percent(growth)],
        "operatingprofitmargin": [percent(cur.margin("operating_profit")), percent(base.margin("operating_profit"))],
        "netprofitmargin": [percent(cur.margin("profit_after_tax")), percent(base.margin("profit_after_tax"))],
        "interestcoverageratiotimes": [coverage(cur), coverage(base)],
    }
    for tr in rows[3:]:
        cells = _cells(tr)
        values = ratios.get(_norm(_text(cells[0])))
        if values:
            for tc, value in zip(cells[1:], values):
                _set_cell(tc, value)


def _update_cover(body_elements, q: Quarter):
    """Updates '2nd Quarter 2026' on the cover to this quarter."""
    for el in body_elements:
        for p in el.iter(qn("w:p")):
            if not re.fullmatch(r"\s*\d(st|nd|rd|th)\s+Quarter\s+\d{4}\s*", _text(p)):
                continue
            runs = [r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None]
            texts = [r.find(qn("w:t")) for r in runs]
            if len(runs) >= 3 and re.fullmatch(r"st|nd|rd|th", texts[1].text or ""):
                texts[0].text, texts[1].text = str(q.quarter), _ordinal(q.quarter)
                texts[2].text = f" Quarter {q.year}"
                texts[2].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                for t in texts[3:]:
                    t.text = ""
            else:
                _set_text(p, f"{q.quarter}{_ordinal(q.quarter)} Quarter {q.year}")


def _update_executive_summary_slt(doc: Document, yoy: Comparison, phrase: str, spec: SectionSpec):
    paras = doc.paragraphs
    exec_idx = -1
    for i, p in enumerate(paras):
        if _norm(p.text) == "executivesummary":
            exec_idx = i
            break
    if exec_idx == -1:
        return
    slt_idx = -1
    for i in range(exec_idx, len(paras)):
        if _norm(paras[i].text) == "sltplc":
            slt_idx = i
            break
    if slt_idx == -1:
        return
    mob_idx = len(paras)
    for i in range(slt_idx + 1, len(paras)):
        if _norm(paras[i].text) == "mobitel":
            mob_idx = i
            break

    target_paras = [paras[k] for k in range(slt_idx + 1, mob_idx) if paras[k].text.strip()]
    if len(target_paras) >= 1:
        _set_text(target_paras[0]._element, commentary.revenue_paragraph(yoy, ENTITY, phrase))
    if len(target_paras) >= 2:
        _set_text(target_paras[1]._element, commentary.opex_paragraph(yoy, ENTITY, phrase))
    if len(target_paras) >= 3:
        _set_text(target_paras[2]._element, " ".join(commentary.profit_paragraphs(yoy, spec.current_label, spec.base_label)))


def _update_section_commentary(doc: Document, letter: str, comparison: Comparison, spec: SectionSpec):
    paras = doc.paragraphs
    target_pattern = {
        "A": "performanceofthecurrentquarteragainsttheprecedingyear",
        "B": "performanceofthecurrentquarteragainsttheprecedingquarter",
        "C": "performanceofthecurrentyearagainsttheprecedingyear",
    }.get(letter)
    if not target_pattern:
        return
    sec_idx = -1
    for i, p in enumerate(paras):
        if target_pattern in _norm(p.text):
            sec_idx = i
            break
    if sec_idx == -1:
        return
    slt_idx = -1
    for i in range(sec_idx, len(paras)):
        if _norm(paras[i].text) == "sltplc":
            slt_idx = i
            break
    if slt_idx == -1:
        return
    end_idx = len(paras)
    for i in range(slt_idx + 1, len(paras)):
        t = _norm(paras[i].text)
        if t in ("mobitel", "liquidityandoperatingcashflow") or ("performanceof" in t and "performanceofthecurrent" in t):
            end_idx = i
            break

    subheads = {}
    for k in range(slt_idx, end_idx):
        t = _norm(paras[k].text)
        if t in ("revenue", "opex", "profits"):
            subheads[t] = k

    if "revenue" in subheads:
        rev_k = subheads["revenue"]
        next_k = subheads.get("opex", end_idx)
        for k in range(rev_k + 1, next_k):
            if paras[k].text.strip():
                _set_text(paras[k]._element, commentary.revenue_paragraph(comparison, ENTITY, spec.period_phrase))
                break
    if "opex" in subheads:
        opx_k = subheads["opex"]
        next_k = subheads.get("profits", end_idx)
        for k in range(opx_k + 1, next_k):
            if paras[k].text.strip():
                _set_text(paras[k]._element, commentary.opex_paragraph(comparison, ENTITY, spec.period_phrase))
                break
    if "profits" in subheads:
        prf_k = subheads["profits"]
        for k in range(prf_k + 1, end_idx):
            if paras[k].text.strip():
                _set_text(paras[k]._element, " ".join(commentary.profit_paragraphs(comparison, spec.current_label, spec.base_label)))
                break


def _update_section_headings(doc: Document, q: Quarter, specs: List[SectionSpec]):
    """Updates the section headings and table captions with current quarter labels."""
    paras = doc.paragraphs
    for p in paras:
        t = _norm(p.text)
        if "performanceofthecurrentquarteragainsttheprecedingyear" in t:
            _set_text(p._element, f"Performance of the current quarter against the preceding year corresponding quarter "
                                  f"({specs[0].current_label} Vs {specs[0].base_label})")
        elif "performanceofthecurrentquarteragainsttheprecedingquarter" in t:
            _set_text(p._element, f"(B) Performance of the current quarter against the preceding quarter "
                                  f"({specs[1].current_label} vs {specs[1].base_label})")
        elif "performanceofthecurrentyearagainsttheprecedingyear" in t:
            _set_text(p._element, f"Performance of the current year against the preceding year "
                                  f"({specs[2].current_label} Vs {specs[2].base_label})")
        elif "performanceofthecurrentquarteractualsagainstthebudget" in t:
            _set_text(p._element, f"(D) Performance of the current quarter Actuals against the Budget "
                                  f"({_q_short(q)} Actuals Vs Budget)")
            p_idx = paras.index(p)
            if p_idx + 3 < len(paras):
                _set_text(paras[p_idx + 3]._element, "Budget figures have not been loaded, so this section reflects "
                                                     "template placeholders until a budget file is provided.")


def _insert_section_a_charts(doc: Document, trend: List[MonthFigures]):
    paras = doc.paragraphs
    sec_a = -1
    for i, p in enumerate(paras):
        if "performanceofthecurrentquarteragainsttheprecedingyear" in _norm(p.text):
            sec_a = i
            break
    if sec_a == -1:
        return
    slt_a = -1
    for i in range(sec_a, len(paras)):
        if _norm(paras[i].text) == "sltplc":
            slt_a = i
            break
    if slt_a == -1:
        return

    rev_idx, opx_idx = -1, -1
    for k in range(slt_a, slt_a + 25):
        if k < len(paras):
            t = _norm(paras[k].text)
            if t == "revenue" and rev_idx == -1:
                rev_idx = k
            elif t == "opex" and opx_idx == -1:
                opx_idx = k

    if rev_idx != -1 and rev_idx + 1 < len(paras):
        chart_rev = trend_chart(trend, "revenue", "Monthly revenue – SLT PLC (LKR Mn)")
        if chart_rev:
            p_obj = Paragraph(paras[rev_idx + 1]._element, doc._body)
            p_obj.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_obj.add_run().add_picture(chart_rev, width=Cm(15.0))

    if opx_idx != -1 and opx_idx + 1 < len(paras):
        chart_opx = trend_chart(trend, "opex", "Monthly operating expenses – SLT PLC (LKR Mn)")
        if chart_opx:
            p_obj = Paragraph(paras[opx_idx + 1]._element, doc._body)
            p_obj.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_obj.add_run().add_picture(chart_opx, width=Cm(15.0))


# ---------------------------------------------------------------------------
# Template & Builder


class _Template:
    """Locates the paragraphs and tables of Finance's report that the generator copies."""

    def __init__(self, doc):
        self.doc = doc
        self.body = doc.element.body
        children = [el for el in self.body if el.tag in (qn("w:p"), qn("w:tbl"))]
        self.children = children

        exec_idx = self._index(lambda el: _norm(_text(el)) == "executivesummary", "the 'Executive Summary' heading")
        self.cover = children[:exec_idx]
        self.title = children[exec_idx]
        entity_idx = self._index(lambda el: _norm(_text(el)) == "sltplc", "the 'SLT PLC' heading", exec_idx)
        self.entity = children[entity_idx]
        self.body_text = self._find(lambda el: el.tag == qn("w:p") and len(_text(el)) > 80,
                                    "a body paragraph", entity_idx)
        stats_idx = self._index(lambda el: _norm(_text(el)).startswith("financialstatistics"),
                                "the 'Financial Statistics' heading")
        self.stats_title = children[stats_idx]
        self.fin_table = self._find(lambda el: el.tag == qn("w:tbl"), "the Financial Summary table", stats_idx)
        self.ratio_table = self._find(lambda el: el.tag == qn("w:tbl") and el is not self.fin_table,
                                      "the Key Ratios table", stats_idx)
        self.section = self._find(lambda el: _norm(_text(el)).startswith("bperformanceof"),
                                  "the '(B) Performance of ...' heading")
        caption_idx = self._index(lambda el: _norm(_text(el)).startswith("incomestatementsltplc"),
                                  "the 'Income Statement – SLT PLC' caption")
        self.caption = children[caption_idx]
        is_idx = self._index(lambda el: el.tag == qn("w:tbl"), "the SLT PLC income statement table", caption_idx)
        self.is_table = children[is_idx]
        self.subhead = self._find(lambda el: _norm(_text(el)) == "revenue", "the 'Revenue' sub-heading", is_idx)

    def _index(self, predicate: Callable, what: str, start: int = 0) -> int:
        for i in range(start, len(self.children)):
            if predicate(self.children[i]):
                return i
        raise ReportTemplateError(f"Report template is missing {what}")

    def _find(self, predicate: Callable, what: str, start: int = 0):
        return self.children[self._index(predicate, what, start)]


class _Builder:
    def __init__(self, template_path: Path):
        self.doc = Document(str(template_path))
        self.t = _Template(self.doc)
        self.sect_pr = self.doc.element.body.find(qn("w:sectPr"))

    def _append(self, el):
        self.sect_pr.addprevious(el)
        return el

    def paragraph(self, proto, text: str):
        p = copy.deepcopy(proto)
        for drawing in list(p.iter(qn("w:drawing"))):
            drawing.getparent().remove(drawing)
        _set_text(p, text)
        return self._append(p)

    def title(self, text):
        return self.paragraph(self.t.title, text)

    def entity(self, text=ENTITY):
        return self.paragraph(self.t.entity, text)

    def body(self, text):
        return self.paragraph(self.t.body_text, text)

    def subhead(self, text):
        return self.paragraph(self.t.subhead, text)

    def section(self, text):
        return self.paragraph(self.t.section, text)

    def caption(self, text):
        return self.paragraph(self.t.caption, text)

    def picture(self, stream, width_cm: float = 16.0):
        p = self.paragraph(self.t.body_text, "")
        for r in list(p.iter(qn("w:r"))):
            r.getparent().remove(r)
        para = Paragraph(p, self.doc._body)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run().add_picture(stream, width=Cm(width_cm))

    def table(self, proto):
        return self._append(copy.deepcopy(proto))

    def page_break(self):
        p = copy.deepcopy(self.t.body_text)
        for child in list(p):
            if child.tag != qn("w:pPr"):
                p.remove(child)
        run = p.makeelement(qn("w:r"), {})
        p.append(run)
        br = run.makeelement(qn("w:br"), {qn("w:type"): "page"})
        run.append(br)
        return self._append(p)

    def finish(self, path: Path):
        self.doc.save(str(path))


def _add_keep_with_next(p_element):
    pPr = p_element.find(qn("w:pPr"))
    if pPr is None:
        pPr = p_element.makeelement(qn("w:pPr"), {})
        p_element.insert(0, pPr)
    if pPr.find(qn("w:keepNext")) is None:
        pPr.append(p_element.makeelement(qn("w:keepNext"), {}))
    if pPr.find(qn("w:keepLines")) is None:
        pPr.append(p_element.makeelement(qn("w:keepLines"), {}))


def _add_cant_split(tr_element):
    trPr = tr_element.find(qn("w:trPr"))
    if trPr is None:
        trPr = tr_element.makeelement(qn("w:trPr"), {})
        tr_element.insert(0, trPr)
    if trPr.find(qn("w:cantSplit")) is None:
        trPr.append(tr_element.makeelement(qn("w:cantSplit"), {}))


def _add_tbl_header(tr_element):
    trPr = tr_element.find(qn("w:trPr"))
    if trPr is None:
        trPr = tr_element.makeelement(qn("w:trPr"), {})
        tr_element.insert(0, trPr)
    if trPr.find(qn("w:tblHeader")) is None:
        trPr.append(tr_element.makeelement(qn("w:tblHeader"), {}))


def _scale_table_to_width(tbl_el, new_widths: list, max_width_dxa: int):
    """Scale grid columns and all cell widths to new_widths, update tblW."""
    tblPr = tbl_el.find(qn("w:tblPr"))
    # Update tblW
    tblW = tblPr.find(qn("w:tblW")) if tblPr is not None else None
    if tblW is not None:
        tblW.set(qn("w:w"), str(max_width_dxa))
        tblW.set(qn("w:type"), "dxa")
    elif tblPr is not None:
        tblW = tblPr.makeelement(qn("w:tblW"), {qn("w:w"): str(max_width_dxa), qn("w:type"): "dxa"})
        tblPr.append(tblW)

    # Set tblLayout to fixed
    if tblPr is not None:
        old_layout = tblPr.find(qn("w:tblLayout"))
        if old_layout is not None:
            tblPr.remove(old_layout)
        layout = tblPr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
        tblPr.append(layout)

    # Update gridCol widths
    grid = tbl_el.find(qn("w:tblGrid"))
    if grid is not None:
        for col, nw in zip(grid.findall(qn("w:gridCol")), new_widths):
            col.set(qn("w:w"), str(nw))

    # Update every cell's tcW, respecting gridSpan
    for tr in tbl_el.findall(qn("w:tr")):
        col_idx = 0
        for tc in tr.findall(qn("w:tc")):
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                tcPr = tc.makeelement(qn("w:tcPr"), {})
                tc.insert(0, tcPr)
            span_el = tcPr.find(qn("w:gridSpan"))
            span = int(span_el.get(qn("w:val"))) if span_el is not None else 1
            cell_w = sum(new_widths[col_idx: col_idx + span])
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is None:
                tcW = tcPr.makeelement(qn("w:tcW"), {})
                tcPr.insert(0, tcW)
            tcW.set(qn("w:w"), str(cell_w))
            tcW.set(qn("w:type"), "dxa")
            col_idx += span


def _format_and_paginate_report(doc: Document, max_width_dxa: int = 9540):
    """Applies professional layout, pagination, alignment, and margin fitting across the entire document.

    Rules applied:
    - All tables: centered, scaled to fit page width if over max_width_dxa (9540 dxa), fixed layout.
    - Table rows: cantSplit on every row to prevent mid-row page breaks.
    - Header rows: tblHeader so headers repeat across pages for multi-page tables.
    - Short tables (≤25 rows): cells keep rows together on a single page.
    - Headings and paragraphs preceding tables: keepNext + keepLines to prevent orphan headings.
    - Redundant blank paragraphs between a heading and a table are removed.
    """
    # ------------------------------------------------------------------ #
    # 1. Table formatting: width scaling, alignment, cantSplit, tblHeader #
    # ------------------------------------------------------------------ #
    for t_idx, t in enumerate(doc.tables):
        tbl_el = t._element

        # Ensure tblPr exists
        tblPr = tbl_el.find(qn("w:tblPr"))
        if tblPr is None:
            tblPr = tbl_el.makeelement(qn("w:tblPr"), {})
            tbl_el.insert(0, tblPr)

        # Center the table on the page
        jc = tblPr.find(qn("w:jc"))
        if jc is None:
            jc = tblPr.makeelement(qn("w:jc"), {})
            tblPr.append(jc)
        jc.set(qn("w:val"), "center")

        # Scale down if wider than page margins
        grid = tbl_el.find(qn("w:tblGrid"))
        if grid is not None:
            raw_cols = grid.findall(qn("w:gridCol"))
            try:
                widths = [int(c.get(qn("w:w"), "0")) for c in raw_cols]
            except (ValueError, TypeError):
                widths = []
            if widths:
                total_w = sum(widths)
                if total_w > max_width_dxa:
                    scale = max_width_dxa / total_w
                    new_widths = [max(300, int(round(w * scale))) for w in widths]
                    diff = max_width_dxa - sum(new_widths)
                    new_widths[-1] += diff
                    _scale_table_to_width(tbl_el, new_widths, max_width_dxa)
                else:
                    # Even if not overflowing, ensure fixed layout is set
                    old_layout = tblPr.find(qn("w:tblLayout"))
                    if old_layout is not None:
                        tblPr.remove(old_layout)
                    layout = tblPr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
                    tblPr.append(layout)

        rows = tbl_el.findall(qn("w:tr"))
        num_rows = len(rows)
        num_cols = len(t.columns) if t.columns else (len(grid.findall(qn("w:gridCol"))) if grid is not None else 0)

        # Header rows: 2 for wide multi-header tables (num_cols > 10 and num_rows > 3), 1 for others
        header_row_count = 2 if (num_cols > 10 and num_rows > 3) else 1

        for r_i, tr in enumerate(rows):
            _add_cant_split(tr)
            if r_i < header_row_count:
                _add_tbl_header(tr)

    # ------------------------------------------------------------------ #
    # 2. Paragraph keep-with-next, keep-lines, remove orphan blanks      #
    # ------------------------------------------------------------------ #
    heading_keywords = [
        "executivesummary", "sltgroup", "sltplc", "mobitel",
        "financialstatistics", "financialsummary", "keyratios",
        "operationalstatistics", "keydrivers", "capacityvsutilization",
        "performanceof", "bperformanceof", "dperformanceof",
        "incomestatement", "revenue", "opex", "profits",
        "liquidityandoperatingcashflow", "borrowings", "interestcost",
        "keyprojectsinfo", "ftthportutilization", "ftthrtwomwise", "ftthactive",
        "annexure", "sectionstobecompleted", "datanotes",
    ]

    body = doc.element.body
    children = list(body)
    n = len(children)

    # Pass 1: remove purely blank paragraphs that sit between a heading-para and a table
    to_remove = set()
    for i, el in enumerate(children):
        if el.tag != qn("w:p"):
            continue
        txt = _norm(_text(el))
        has_pb = any(br.get(qn("w:type")) == "page" for br in el.iter(qn("w:br")))
        if has_pb or txt:          # non-blank or has a page break — keep
            continue
        # blank paragraph: check if it is sandwiched between a heading-like para and a table
        prev_content = None
        for j in range(i - 1, -1, -1):
            if children[j].tag in (qn("w:p"), qn("w:tbl")):
                prev_content = children[j]
                break
        next_content = None
        for j in range(i + 1, n):
            if children[j].tag in (qn("w:p"), qn("w:tbl")):
                next_content = children[j]
                break
        prev_is_heading = (
            prev_content is not None
            and prev_content.tag == qn("w:p")
            and any(k in _norm(_text(prev_content)) for k in heading_keywords)
        )
        next_is_tbl = next_content is not None and next_content.tag == qn("w:tbl")
        if prev_is_heading and next_is_tbl:
            to_remove.add(id(el))

    for el in children:
        if id(el) in to_remove:
            body.remove(el)

    # Rebuild children list after removals
    children = list(body)
    n = len(children)

    # Pass 2: apply keepNext / keepLines to headings, subheadings, and captions preceding tables
    for i, el in enumerate(children):
        if el.tag != qn("w:p"):
            continue
        txt = _norm(_text(el))
        has_pb = any(br.get(qn("w:type")) == "page" for br in el.iter(qn("w:br")))
        if has_pb:
            continue  # page-break paragraphs must not have keepNext

        next_is_tbl = (i + 1 < n and children[i + 1].tag == qn("w:tbl"))
        next_next_is_tbl = (i + 2 < n and children[i + 2].tag == qn("w:tbl"))
        next_is_caption = (i + 1 < n and children[i + 1].tag == qn("w:p") and len(_text(children[i + 1])) < 40)
        is_heading = any(k in txt for k in heading_keywords)

        if is_heading or next_is_tbl or (next_next_is_tbl and next_is_caption):
            _add_keep_with_next(el)
        else:
            pPr = el.find(qn("w:pPr"))
            if pPr is None:
                pPr = el.makeelement(qn("w:pPr"), {})
                el.insert(0, pPr)
            if pPr.find(qn("w:keepLines")) is None:
                pPr.append(el.makeelement(qn("w:keepLines"), {}))


# ---------------------------------------------------------------------------
# Main Report Generator


def generate_report(inputs: ReportInputs, output_dir: Path, template_path: Path = TEMPLATE_PATH) -> Path:
    analysis = inputs.analysis
    q = analysis.quarter
    specs = _section_specs(q)
    b = _Builder(template_path)
    doc = b.doc

    # 1. Update Cover
    _update_cover(list(doc.element.body), q)

    # 2. Update Executive Summary
    yoy = analysis.comparisons["quarter_vs_last_year"]
    _update_executive_summary_slt(doc, yoy, specs[0].period_phrase, specs[0])

    # 3. Update Financial Statistics
    ytd = analysis.comparisons["ytd_vs_last_year"]
    _update_financial_summary(doc.tables[0]._element, ytd, q.end, q.same_quarter_last_year().end)
    _update_key_ratios(doc.tables[1]._element, ytd, q.end, q.same_quarter_last_year().end)

    # 4. Update Section A (Current Quarter vs Same Quarter Last Year)
    _update_group_table(doc.tables[4]._element, yoy, specs[0], q)
    _fill_income_statement(doc.tables[5]._element, yoy, specs[0])
    _update_section_commentary(doc, "A", yoy, specs[0])
    if inputs.trend:
        _insert_section_a_charts(doc, inputs.trend)

    # 5. Update Section B (Current Quarter vs Preceding Quarter)
    q_vs_prev = analysis.comparisons["quarter_vs_previous"]
    _update_group_table(doc.tables[6]._element, q_vs_prev, specs[1], q)
    _fill_income_statement(doc.tables[7]._element, q_vs_prev, specs[1])
    _update_section_commentary(doc, "B", q_vs_prev, specs[1])

    # 6. Update Section C (Current Year vs Preceding Year YTD)
    _update_group_table(doc.tables[8]._element, ytd, specs[2], q)
    _fill_income_statement(doc.tables[9]._element, ytd, specs[2])
    _update_section_commentary(doc, "C", ytd, specs[2])

    # Update date headers in Section C tables (Cashflow, Borrowings, Interest)
    if len(doc.tables) > 10:
        head_cf = _cells(doc.tables[10]._element.findall(qn("w:tr"))[0])
        if len(head_cf) >= 3:
            _set_cell(head_cf[1], f"YTD {_short(q.end)}")
            _set_cell(head_cf[2], f"YTD {_short(q.same_quarter_last_year().end)}")
    if len(doc.tables) > 12:
        head_int = _cells(doc.tables[12]._element.findall(qn("w:tr"))[0])
        if len(head_int) >= 3:
            _set_cell(head_int[1], f"YTD {_short(q.end)} (LKR Mn)")
            _set_cell(head_int[2], f"YTD {_short(q.same_quarter_last_year().end)} (LKR Mn)")

    # 7. Update Section D (Actuals vs Budget)
    if len(doc.tables) > 13:
        t13 = doc.tables[13]._element
        head13_0 = _cells(t13.findall(qn("w:tr"))[0])
        head13_1 = _cells(t13.findall(qn("w:tr"))[1])
        if len(head13_0) >= 3:
            _set_cell(head13_0[1], f"{_q_short(q)} (Actuals)")
            _set_cell(head13_0[2], f"{_q_short(q)} (Budget)")
        if len(head13_1) >= 3:
            _set_cell(head13_1[1], f"{_q_short(q)} (Actuals)")
            _set_cell(head13_1[2], f"{_q_short(q)} (Budget)")
        cur_q_lines = yoy.current.lines
        for tr in t13.findall(qn("w:tr"))[2:]:
            cells = _cells(tr)
            getter = IS_ROWS.get(_norm(_text(cells[0])))
            if getter is not None:
                _set_cell(cells[1], money(getter(cur_q_lines)))

    # Update section headings
    _update_section_headings(doc, q, specs)

    # 8. Append Annexure (ii) – Account-level variance drivers
    b.page_break()
    b.title("Annexure (ii) – Account-level variance drivers")
    for spec in specs:
        comparison = analysis.comparisons[spec.comparison_key]
        for line, name, cost in (("revenue", "Revenue", False), ("operating_costs", "Opex", True)):
            rows, colors = _driver_rows(comparison, line, cost)
            if not rows:
                continue
            b.caption(f"{name} – largest movements by GL account, {spec.current_label} Vs {spec.base_label} (LKR Mn)")
            tbl = b.table(b.t.is_table)
            head = _cells(tbl.findall(qn("w:tr"))[0])
            _set_cell(head[0], "GL account")
            _set_cell(head[1], *spec.header_current)
            _set_cell(head[2], *spec.header_base)
            _fill_rows(tbl, 2, rows, colors)
            _set_column_widths(tbl, DRIVER_COLUMNS)
            b.body("")

    b.title("Sections to be completed by Finance")
    b.body("The following parts of the quarterly report are not in the trial balance and are not generated:")
    for item in MANUAL_SECTIONS:
        b.body(f"•  {item}")

    b.title("Data notes")
    notes = list(inputs.data_notes)
    for u in analysis.unmapped:
        notes.append(f"Account {u.account} {u.name.strip()} ({u.period}, LKR {u.amount:,.1f} Mn) "
                     "is not in the GL mapping and is excluded from the P&L.")
    notes.append("Figures are in LKR Mn from the detail trial balances, mapped to P&L lines with the GL code "
                 "mapping. Income is shown positive; Opex is shown as a positive cost. Quarter figures are "
                 "quarter-end YTD less the previous quarter-end YTD.")
    for note in notes:
        b.body(f"•  {note}")

    # 9. Apply professional layout, pagination, and table alignment across the whole document
    #    (Must be done AFTER all content has been appended and before saving)
    _format_and_paginate_report(doc)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"Financial_Analysis_Q{q.quarter}_{q.year}_{uuid.uuid4().hex[:8]}.docx"
    b.finish(path)
    logger.info(f"Financial Analysis Report written: {path.name}")
    return path
