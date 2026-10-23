"""
Checks against the sample files Finance supplied (finance_automation/files).
Skipped when the files are not present, as they are not in git.
"""
from pathlib import Path

import pytest

from services.financial_analysis.mapping_reader import read_gl_mapping
from services.financial_analysis.periods import Period, Quarter
from services.financial_analysis.pl_engine import build_analysis
from services.financial_analysis.tb_reader import read_trial_balance

FILES = Path(__file__).resolve().parents[3] / "files"
TB_FILES = ["Detail TB_Mar 25.xlsx", "Detail TB_Jun 25.xlsx", "Detail TB_March 2026.xlsx", "Detail TB_Jun 2026.xlsx"]

pytestmark = pytest.mark.skipif(
    not all((FILES / f).exists() for f in TB_FILES + ["GL code mapping.xlsx"]),
    reason="sample finance files not present",
)


@pytest.fixture(scope="module")
def analysis():
    tbs = {}
    for name in TB_FILES:
        tb = read_trial_balance(FILES / name)
        assert abs(tb.net_ytd) < 100, f"{name} does not balance"
        tbs[tb.period] = tb.accounts
    assert set(tbs) == {Period(2025, 3), Period(2025, 6), Period(2026, 3), Period(2026, 6)}
    return build_analysis(Quarter(2026, 2), tbs.get, read_gl_mapping(FILES / "GL code mapping.xlsx"))


def test_every_pl_account_is_mapped(analysis):
    assert analysis.unmapped == []


def test_ytd_june_2026_figures(analysis):
    rows = {r.key: r for r in analysis.comparisons["ytd_vs_last_year"].rows}
    assert rows["revenue"].current == pytest.approx(46082.0, abs=0.1)
    assert rows["ebitda"].current == pytest.approx(17060.9, abs=0.1)
    assert rows["profit_after_tax"].current == pytest.approx(5149.4, abs=0.1)
    assert rows["profit_after_tax"].base == pytest.approx(2865.0, abs=0.1)


def test_quarters_add_up_to_ytd(analysis):
    q2 = {r.key: r for r in analysis.comparisons["quarter_vs_previous"].rows}
    ytd = {r.key: r for r in analysis.comparisons["ytd_vs_last_year"].rows}
    for key in ytd:
        assert q2[key].current + q2[key].base == pytest.approx(ytd[key].current, abs=1e-6)
