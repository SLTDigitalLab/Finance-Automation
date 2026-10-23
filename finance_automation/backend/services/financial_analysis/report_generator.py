"""
Writes the quarterly Financial Analysis Report (Word) in Finance's format.

The template is Finance's own Q2 2026 report with figures masked as "xx.x%".
Its cover page is kept (the quarter is updated) and the body is rebuilt from
copies of its paragraphs and tables, so fonts, shading and table layouts match
the report Finance already produces.

What the trial balance supports is generated for SLT PLC (the TB is company 01):
  Executive Summary, Financial Statistics, sections (A) quarter vs same quarter
  last year, (B) quarter vs preceding quarter, (C) YTD vs last year's YTD, an
  annexure of account-level drivers and data notes.
Section (D), actuals vs budget, is a placeholder until a budget file is loaded.
Group / Mobitel figures, operational statistics, cash flow, borrowings and
FTTH data are not in the TB; the report lists them for Finance to add.
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


# ---------------------------------------------------------------------------
# Builder


class _Builder:
    def __init__(self, template_path: Path):
        self.doc = Document(str(template_path))
        self.t = _Template(self.doc)
        # Detach everything but the cover; parts are copied back as needed.
        keep = set(map(id, self.t.cover))
        self.sect_pr = self.t.body.find(qn("w:sectPr"))
        for el in list(self.t.body):
            if el is not self.sect_pr and id(el) not in keep:
                self.t.body.remove(el)

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
        p = self.paragraph(self.t.body_text, "")
        run = next(p.iter(qn("w:r")))
        for child in list(run):
            if child.tag != qn("w:rPr"):
                run.remove(child)
        br = run.makeelement(qn("w:br"), {qn("w:type"): "page"})
        run.append(br)

    def finish(self, path: Path):
        self._drop_unused_parts()
        self.doc.save(str(path))

    def _drop_unused_parts(self):
        """Removes the template's charts and images that the rebuilt body no longer references."""
        xml = self.doc.element.xml
        part = self.doc.part
        for r_id, rel in list(part.rels.items()):
            if rel.reltype in (RT.CHART, RT.IMAGE) and f'"{r_id}"' not in xml:
                del part.rels[r_id]


# ---------------------------------------------------------------------------
# Content


def _update_cover(cover: list, q: Quarter):
    """'2nd Quarter 2026' on the cover -> this quarter (the text sits in a few runs, twice)."""
    for el in cover:
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


def _margin_change(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    return cur - base if cur is not None and base is not None else None


def _fill_financial_summary(tbl, ytd: Comparison, end: Period, ly_end: Period):
    """Keeps the rows the P&L supports; budget columns stay N/A until a budget is loaded."""
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
            continue  # spacer row
        if label in amounts:
            key = amounts[label]
            _, pct = _growth(cur.lines[key], base.lines[key])
            values = [money(cur.lines[key]), money(base.lines[key]), percent(pct)]
        elif label in margins:
            key = margins[label]
            c, b = cur.margin(key), base.margin(key)
            values = [percent(c), percent(b), percent(_margin_change(c, b))]
        else:
            tbl.remove(tr)
            continue
        for tc, value in zip(cells[1:], values + ["N/A", "N/A"]):
            _set_cell(tc, value)


def _fill_key_ratios(tbl, ytd: Comparison, end: Period, ly_end: Period):
    rows = tbl.findall(qn("w:tr"))
    head = _cells(rows[2])[1:]   # first cell continues the merged label column
    for tc, text in zip(head, [_short(end), _short(ly_end), _short(end)]):
        _set_cell(tc, text)
    cur, base = ytd.current, ytd.base
    _, growth = _growth(cur.lines["revenue"], base.lines["revenue"])

    def coverage(pl):
        interest = -pl.lines["interest_expenses"]
        return f"{pl.lines['operating_profit'] / interest:.1f}" if interest > 0 else "N/A"

    ratios = {
        "revenuegrowthyoy": [percent(growth), "N/A"],
        "operatingprofitmargin": [percent(cur.margin("operating_profit")), percent(base.margin("operating_profit"))],
        "netprofitmargin": [percent(cur.margin("profit_after_tax")), percent(base.margin("profit_after_tax"))],
        "interestcoverageratiotimes": [coverage(cur), coverage(base)],
    }
    for tr in rows[3:]:
        cells = _cells(tr)
        values = ratios.get(_norm(_text(cells[0])))
        if values is None:
            tbl.remove(tr)
            continue
        for tc, value in zip(cells[1:], values + ["N/A"]):
            _set_cell(tc, value)


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


def _comparison_section(b: _Builder, spec: SectionSpec, comparison: Comparison, trend: List[MonthFigures]):
    b.section(f"({spec.letter}) {spec.title}")
    b.entity()
    b.caption(f"Income Statement – {ENTITY} {spec.current_label} Vs {spec.base_label} (LKR Mn)")
    _fill_income_statement(b.table(b.t.is_table), comparison, spec)
    b.body("")

    b.subhead("Revenue")
    if spec.charts:
        chart = trend_chart(trend, "revenue", "Monthly revenue – SLT PLC (LKR Mn)")
        if chart:
            b.picture(chart)
    b.body(commentary.revenue_paragraph(comparison, ENTITY, spec.period_phrase))

    b.subhead("Opex")
    if spec.charts:
        chart = trend_chart(trend, "opex", "Monthly operating expenses – SLT PLC (LKR Mn)")
        if chart:
            b.picture(chart)
    b.body(commentary.opex_paragraph(comparison, ENTITY, spec.period_phrase))

    b.subhead("Profits")
    for text in commentary.profit_paragraphs(comparison, spec.current_label, spec.base_label):
        b.body(text)


def generate_report(inputs: ReportInputs, output_dir: Path, template_path: Path = TEMPLATE_PATH) -> Path:
    analysis = inputs.analysis
    q = analysis.quarter
    specs = _section_specs(q)
    b = _Builder(template_path)
    _update_cover(b.t.cover, q)

    # Executive Summary: the quarter against the same quarter last year.
    yoy = analysis.comparisons["quarter_vs_last_year"]
    phrase = specs[0].period_phrase
    b.title("Executive Summary")
    b.entity()
    b.body(commentary.revenue_paragraph(yoy, ENTITY, phrase))
    b.body(commentary.opex_paragraph(yoy, ENTITY, phrase))
    for text in commentary.profit_paragraphs(yoy, specs[0].current_label, specs[0].base_label):
        b.body(text)

    ytd = analysis.comparisons["ytd_vs_last_year"]
    b.paragraph(b.t.stats_title, f"Financial Statistics – {ENTITY}")
    _fill_financial_summary(b.table(b.t.fin_table), ytd, q.end, q.same_quarter_last_year().end)
    b.body("")
    _fill_key_ratios(b.table(b.t.ratio_table), ytd, q.end, q.same_quarter_last_year().end)
    b.body("Margin variances are differences in percentage points. Interest cover is Operating profit "
           "divided by interest expenses. Budget columns are N/A until a budget is loaded.")

    for spec in specs:
        _comparison_section(b, spec, analysis.comparisons[spec.comparison_key], inputs.trend)

    b.section(f"(D) Performance of the current quarter Actuals against the Budget ({_q_short(q)} Actuals Vs Budget)")
    b.entity()
    b.body("Budget figures have not been loaded, so this section has not been generated. "
           "It will be filled automatically once the budget file is provided.")

    # Annexures
    b.page_break()
    b.title("Annexure – Account-level variance drivers")
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

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"Financial_Analysis_Q{q.quarter}_{q.year}_{uuid.uuid4().hex[:8]}.docx"
    b.finish(path)
    logger.info(f"Financial Analysis Report written: {path.name}")
    return path
