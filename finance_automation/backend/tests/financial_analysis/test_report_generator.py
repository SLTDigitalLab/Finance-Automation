import re
import zipfile

import pytest
from docx import Document
from docx.oxml.ns import qn

from services.financial_analysis.mapping_reader import read_gl_mapping
from services.financial_analysis.periods import Period, Quarter
from services.financial_analysis.pl_engine import build_analysis, monthly_trend
from services.financial_analysis.report_generator import TEMPLATE_PATH, ReportInputs, generate_report
from tests.financial_analysis.helpers import balances, write_mapping

MN = 1_000_000


def ytd(revenue, opex, fx=0.0):
    return balances({411101: -revenue * MN, 511101: opex * MN, 526101: 10 * MN,
                     527201: -fx * MN, 621001: 5 * MN})


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("report")
    mapping = read_gl_mapping(write_mapping(tmp / "map.xlsx"))
    loaded = {
        Period(2025, 3): ytd(100, 60),
        Period(2025, 9): ytd(300, 180),
        Period(2025, 12): ytd(420, 250, fx=4),
        Period(2026, 3): ytd(110, 75, fx=-3),     # Q1 2026: revenue up, opex up, FX loss
    }
    q = Quarter(2026, 1)
    analysis = build_analysis(q, loaded.get, mapping)
    path = generate_report(ReportInputs(analysis, monthly_trend(q.end, loaded.get, mapping), ["Test note"]), tmp)
    return path


def _xml(path):
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf8"), z.namelist()


def test_cover_shows_the_quarter(report):
    xml, _ = _xml(report)
    texts = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
    assert "1st Quarter 2026" in texts
    assert "2nd Quarter" not in texts


def test_reference_document_structure_preserved(report):
    doc = Document(str(report))
    assert len(doc.tables) >= 17
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Executive Summary" in text
    assert "SLT Group" in text
    assert "SLT PLC" in text
    assert "Mobitel" in text
    assert "Key Projects Info" in text or "FTTH Port Utilization" in text
    assert "Annexure" in text


def _income_statements(doc):
    return [t for t in doc.tables
            if len(t.columns) == 5 and t.rows[0].cells[-1].text == "Growth" and t.rows[2].cells[0].text == "Revenue"][:3]


def test_income_statement_tables(report):
    doc = Document(str(report))
    tables = _income_statements(doc)
    assert len(tables) == 3                     # (A), (B), (C)
    q_vs_ly = tables[0]
    assert [c.text for c in q_vs_ly.rows[0].cells[1:3]] == ["Q1\n2026", "Q1\n2025"]
    assert [c.text for c in q_vs_ly.rows[2].cells] == ["Revenue", "110", "100", "10", "10.0%"]
    assert [c.text for c in q_vs_ly.rows[3].cells] == ["Opex", "75", "60", "15", "25.0%"]
    q_vs_q4 = tables[1]
    assert [c.text for c in q_vs_q4.rows[2].cells] == ["Revenue", "110", "120", "(10)", "(8.3%)"]


def test_growth_colours_follow_favourability(report):
    doc = Document(str(report))
    table = _income_statements(doc)[0]

    def color(row):
        run = table.rows[row].cells[-1].paragraphs[0].runs[0]
        return str(run.font.color.rgb)
    assert color(2) == "00B050"     # revenue up: favourable
    assert color(3) == "EE0000"     # opex up: unfavourable


def test_commentary_and_notes(report):
    text = "\n".join(p.text for p in Document(str(report)).paragraphs)
    assert "SLT PLC revenue increased by 10.0% (LKR 10 Mn) in Q1’26 compared to Q1’25" in text
    assert "an exchange loss of LKR 3 Mn in Q1’26, compared to an exchange gain of LKR 4 Mn in Q4’25" in text
    assert "Budget figures have not been loaded" in text
    assert "•  Test note" in text


def _texts(el):
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def _layout(doc):
    """Tables (grid widths) and lines of text up to the generated Annexure (ii); blank lines are left out."""
    out = []
    for el in doc.element.body:
        if el.tag == qn("w:p") and "Annexure (ii)" in _texts(el):
            break
        if el.tag == qn("w:tbl"):
            out.append(("tbl", tuple(c.get(qn("w:w")) for c in el.iter(qn("w:gridCol")))))
        elif el.tag == qn("w:p") and (_texts(el).strip() or next(el.iter(qn("w:drawing")), None) is not None):
            out.append(("p",))
    return out


def _page_starts(doc):
    """Text of each paragraph that starts a page (pageBreakBefore), or of a table's first cell."""
    return [_texts(el)[:30] for el in doc.element.body
            if el.tag in (qn("w:p"), qn("w:tbl"))
            and next(el.iter(qn("w:p"))).find(f"{qn('w:pPr')}/{qn('w:pageBreakBefore')}") is not None]


def test_layout_matches_finance_template(report):
    """Table widths and charts are Finance's own; only the annexure and notes are added."""
    generated, template = Document(str(report)), Document(str(TEMPLATE_PATH))
    assert _layout(generated) == _layout(template)
    xml, _ = _xml(report)
    with zipfile.ZipFile(TEMPLATE_PATH) as z:
        assert xml.count("<pic:pic") == z.read("word/document.xml").decode("utf8").count("<pic:pic")


def test_blank_line_spacers_become_page_breaks(report):
    starts = _page_starts(Document(str(report)))
    for heading in ("Financial Statistics", "Key Ratios", "Operational Statistics", "(D) Performance",
                    "(ii) FTTH Port Utilization", "Annexure (i)"):
        assert any(s.startswith(heading) for s in starts), heading
    assert not any(s.startswith("Executive Summary") or s.startswith("Financial Analysis") for s in starts)


def test_group_table_values_use_the_cells_font_size(report):
    group = Document(str(report)).tables[4]._tbl
    revenue = group.tr_lst[2].tc_lst[6]
    sizes = {el.get(qn("w:val")) for el in revenue.iter(qn("w:sz"))}
    assert sizes == {"18"}                                    # 9pt, as in the (B) and (C) Group tables


def test_header_lines_follow_template(report):
    doc = Document(str(report))
    budget = next(t for t in doc.tables if "Budget" in t.rows[0].cells[2].text)
    assert budget.rows[0].cells[1].text == "Q1’26\n(Actuals)"
    merged = budget._tbl.tr_lst[1].tc_lst[1]                 # continuation of the vertically merged header
    assert "".join(t.text or "" for t in merged.iter(qn("w:t"))) == ""
    assert "(YTD March’26 Vs YTD March’25)" in "\n".join(p.text for p in doc.paragraphs)

