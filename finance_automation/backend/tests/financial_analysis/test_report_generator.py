import re
import zipfile

import pytest
from docx import Document

from services.financial_analysis.mapping_reader import read_gl_mapping
from services.financial_analysis.periods import Period, Quarter
from services.financial_analysis.pl_engine import build_analysis, monthly_trend
from services.financial_analysis.report_generator import ReportInputs, generate_report
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


def test_no_template_placeholders_left(report):
    doc = Document(str(report))
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    text = "\n".join([p.text for p in doc.paragraphs] + cells)
    assert not re.search(r"\bx[x,.]*x\b|xx\.x", text)
    assert "Mobitel" not in "\n".join(p.text for p in doc.paragraphs if not p.text.startswith("•"))


def _income_statements(doc):
    return [t for t in doc.tables
            if t.rows[0].cells[-1].text == "Growth" and t.rows[2].cells[0].text == "Revenue"]


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


def test_template_charts_removed(report):
    xml, names = _xml(report)
    assert not [n for n in names if n.startswith("word/charts/")]
    assert xml.count("<pic:pic") >= 3              # cover picture + revenue and opex trend charts
