import pytest

from services.financial_analysis.mapping_reader import MappingFormatError, read_gl_mapping
from services.financial_analysis.periods import Period, Quarter, parse_period
from services.financial_analysis.tb_reader import TBFormatError, read_trial_balance
from tests.financial_analysis.helpers import write_mapping, write_tb


@pytest.mark.parametrize("text, expected", [
    ("YTD June 26", Period(2026, 6)),
    ("YTD Mar 25", Period(2025, 3)),
    ("PTD March 26", Period(2026, 3)),
    ("TB March 2026", Period(2026, 3)),
    ("Detail TB_Jun 25", Period(2025, 6)),
    ("YTD Sept 2025", Period(2025, 9)),
    ("YTD", None),
    ("Total 25", None),
])
def test_parse_period(text, expected):
    assert parse_period(text) == expected


def test_quarter_navigation():
    q1 = Quarter(2026, 1)
    assert q1.previous() == Quarter(2025, 4)
    assert q1.ytd_periods() == [Period(2026, 3)]
    assert Quarter(2026, 2).ytd_periods() == [Period(2026, 6), Period(2026, 3)]
    assert Quarter(2026, 2).same_quarter_last_year() == Quarter(2025, 2)
    assert Quarter.ending(Period(2026, 9)) == Quarter(2026, 3)
    assert Quarter.ending(Period(2026, 8)) is None


def test_tb_sums_rows_per_account(tmp_path):
    path = write_tb(tmp_path / "tb.xlsx", "YTD June 26", [
        ("411101", "Initiation", -100.0, -50.0, -150.0),   # text account, as in the Mar 25 export
        (411101, "Initiation", -10.0, 0.0, -10.0),
        (111101, "Land", 160.0, 0.0, 160.0),
        (None, None, None, None, None),                     # blank trailing row
    ])
    tb = read_trial_balance(path)
    assert tb.period == Period(2026, 6)
    assert tb.row_count == 3
    assert set(tb.accounts) == {411101, 111101}
    assert tb.accounts[411101].ytd == -160.0
    assert tb.accounts[411101].ptd == -50.0
    assert tb.accounts[411101].name == "Initiation"
    assert tb.net_ytd == 0
    assert tb.warnings == []


def test_tb_header_below_title_rows(tmp_path):
    path = write_tb(tmp_path / "tb.xlsx", "YTD March 2026", [(111101, "Land", 0, 0, 0)], preamble=3)
    assert read_trial_balance(path).period == Period(2026, 3)


def test_tb_warns_when_unbalanced(tmp_path):
    path = write_tb(tmp_path / "tb.xlsx", "YTD Mar 25", [
        (111101, "Land", 0, 5000, 5000),
        (411101, "Initiation", 0, -10, -20),   # YTD != beginning + PTD
    ])
    tb = read_trial_balance(path)
    assert len(tb.warnings) == 2
    assert "net to zero" in tb.warnings[1]


def test_tb_rejects_amounts_without_account(tmp_path):
    path = write_tb(tmp_path / "tb.xlsx", "YTD Mar 25", [(None, "Mystery", 0, 10, 10)])
    with pytest.raises(TBFormatError, match="no account number"):
        read_trial_balance(path)


def test_tb_rejects_other_files(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["Name", "Amount"])
    wb.save(tmp_path / "other.xlsx")
    with pytest.raises(TBFormatError, match="header row"):
        read_trial_balance(tmp_path / "other.xlsx")


def test_mapping_reads_lines_and_continuation_rows(tmp_path):
    mapping = read_gl_mapping(write_mapping(tmp_path / "map.xlsx"))
    ranges = [str(r) for r in mapping.lines["operating_costs"].ranges]
    assert ranges == ["511101–525751", "525753–525767", "525769–525813", "529999"]
    assert [str(r) for r in mapping.lines["other_income"].ranges] == ["431001–471099", "481901–481999"]
    assert mapping.line_for(525752) == "share_of_associate"
    assert mapping.line_for(525768) == "oci_actuarial"
    assert mapping.line_for(529999) == "operating_costs"
    assert mapping.line_for(529998) is None
    assert mapping.line_for(631002) is None


def test_mapping_rejects_unknown_line_with_accounts(tmp_path):
    path = write_mapping(tmp_path / "map.xlsx", extra_rows=[("Royalty income", 700001, 700010, None)])
    with pytest.raises(MappingFormatError, match="unrecognised"):
        read_gl_mapping(path)


def test_mapping_rejects_overlapping_ranges(tmp_path):
    path = write_mapping(tmp_path / "map.xlsx", extra_rows=[("Tax on comprehensive income", 621004, None, None)])
    with pytest.raises(MappingFormatError, match="more than once"):
        read_gl_mapping(path)
    path = write_mapping(tmp_path / "map2.xlsx", extra_rows=[(None, 411200, 411300, None)])
    with pytest.raises(MappingFormatError, match="mapped to both"):
        read_gl_mapping(path)
