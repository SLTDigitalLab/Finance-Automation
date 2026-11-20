import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.financial_analysis.mapping_reader import read_gl_mapping
from services.financial_analysis.periods import Period, Quarter
from services.financial_analysis.pl_engine import (
    MissingPeriodsError, build_analysis, compute_pl, required_periods,
)
from tests.financial_analysis.helpers import balances, write_mapping

MN = 1_000_000


@pytest.fixture(scope="module")
def mapping(tmp_path_factory):
    return read_gl_mapping(write_mapping(tmp_path_factory.mktemp("map") / "map.xlsx"))


def ytd(revenue, opex, dep=0.0, tax=0.0, extra=None):
    """YTD balances in TB signs (revenue credit = negative) from Rs Mn figures."""
    data = {411101: -revenue * MN, 511101: opex * MN, 526101: dep * MN, 621001: tax * MN}
    data.update(extra or {})
    return balances(data)


def test_compute_pl_signs_and_subtotals(mapping):
    pl, unmapped = compute_pl(ytd(1000, 600, dep=100, tax=50, extra={
        481101: -20 * MN,            # interest income
        527101: 30 * MN,             # interest expense
        525768: -10 * MN,            # actuarial gain (OCI)
        111101: 999 * MN,            # balance sheet: ignored
        631002: 40 * MN,             # dividends: appropriation, not reported as unmapped
        700001: 5 * MN,              # unmapped P&L account
    }), mapping, "YTD Jun 2026")
    lines = pl.lines
    assert lines["revenue"] == 1000
    assert lines["operating_costs"] == -600
    assert lines["ebitda"] == 400
    assert lines["operating_profit"] == 300
    assert lines["profit_before_tax"] == 290
    assert lines["profit_after_tax"] == 240
    assert lines["other_comprehensive_income"] == 10
    assert lines["total_comprehensive_income"] == 250
    assert pl.margins["ebitda_margin"] == pytest.approx(0.4)
    assert [u.account for u in unmapped] == [700001]


def test_required_periods_q1_reaches_back_to_last_year():
    assert required_periods(Quarter(2026, 1)) == [
        Period(2025, 3), Period(2025, 9), Period(2025, 12), Period(2026, 3)]
    assert required_periods(Quarter(2026, 2)) == [
        Period(2025, 3), Period(2025, 6), Period(2026, 3), Period(2026, 6)]


def test_missing_periods_are_all_reported(mapping):
    loaded = {Period(2026, 6): ytd(1, 1), Period(2026, 3): ytd(1, 1)}
    with pytest.raises(MissingPeriodsError) as err:
        build_analysis(Quarter(2026, 2), loaded.get, mapping)
    assert err.value.periods == [Period(2025, 3), Period(2025, 6)]
    assert "Mar 2025, Jun 2025" in str(err.value)


def test_quarter_figures_and_comparisons(mapping):
    loaded = {
        Period(2025, 3): ytd(100, 60),
        Period(2025, 6): ytd(220, 130),     # Q2 2025: 120 / -70
        Period(2026, 3): ytd(150, 90),      # Q1 2026: 150 / -90
        Period(2026, 6): ytd(330, 190),     # Q2 2026: 180 / -100
    }
    analysis = build_analysis(Quarter(2026, 2), loaded.get, mapping)
    assert analysis.budget_available is False

    vs_ly = {r.key: r for r in analysis.comparisons["quarter_vs_last_year"].rows}
    assert vs_ly["revenue"].current == pytest.approx(180)
    assert vs_ly["revenue"].base == pytest.approx(120)
    assert vs_ly["revenue"].variance_pct == pytest.approx(0.5)
    assert vs_ly["operating_costs"].variance == pytest.approx(-30)   # higher cost = negative variance
    assert vs_ly["ebitda"].current == pytest.approx(80)

    vs_prev = {r.key: r for r in analysis.comparisons["quarter_vs_previous"].rows}
    assert vs_prev["revenue"].base == pytest.approx(150)
    assert vs_prev["ebitda"].variance == pytest.approx(20)

    ytd_rows = {r.key: r for r in analysis.comparisons["ytd_vs_last_year"].rows}
    assert ytd_rows["revenue"].current == pytest.approx(330)
    assert ytd_rows["revenue"].base == pytest.approx(220)
    assert ytd_rows["taxation"].variance_pct is None                # zero base
    assert analysis.comparisons["ytd_vs_last_year"].title == "YTD Jun 2026 vs YTD Jun 2025"


def test_q1_compares_with_last_years_q4(mapping):
    loaded = {
        Period(2025, 3): ytd(100, 60),
        Period(2025, 9): ytd(300, 180),
        Period(2025, 12): ytd(420, 250),    # Q4 2025: 120 / -70
        Period(2026, 3): ytd(130, 75),
    }
    comparison = build_analysis(Quarter(2026, 1), loaded.get, mapping).comparisons["quarter_vs_previous"]
    rows = {r.key: r for r in comparison.rows}
    assert comparison.title == "Q1 2026 vs Q4 2025"
    assert rows["revenue"].current == pytest.approx(130)
    assert rows["revenue"].base == pytest.approx(120)


def test_drivers_rank_accounts_by_movement(mapping):
    base = balances({411101: -100 * MN, 412101: -50 * MN, 413101: -10 * MN, 511101: 40 * MN})
    current = balances({411101: -110 * MN, 412101: -20 * MN, 414101: -5 * MN, 511101: 60 * MN})
    loaded = {Period(2025, 3): base, Period(2026, 3): current,
              Period(2025, 12): base, Period(2025, 9): balances({})}
    comparison = build_analysis(Quarter(2026, 1), loaded.get, mapping).comparisons["quarter_vs_last_year"]

    drivers = comparison.drivers("revenue")
    # Variances: 412101 -30, 411101 +10, 413101 -10 (tie broken by account), 414101 +5
    assert [d.account for d in drivers] == [412101, 411101, 413101, 414101]
    assert drivers[0].variance == pytest.approx(-30)
    assert sum(d.variance for d in drivers) == pytest.approx(-25)
    assert drivers[0].share == pytest.approx(30 / 25)

    # A subtotal's drivers come from all its component lines.
    assert {d.account for d in comparison.drivers("ebitda", limit=10)} == {411101, 412101, 413101, 414101, 511101}


def test_tb_store_round_trip_and_replace():
    from app.database.connection import Base
    from services.financial_analysis import tb_store
    from services.financial_analysis.tb_reader import TrialBalance

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    period = Period(2026, 6)
    tb_store.save_trial_balance(db, TrialBalance(period, balances({411101: -5.0, 111101: 5.0}), 2, 0.0), "a.xlsx")
    tb_store.save_trial_balance(db, TrialBalance(period, balances({411101: -7.0, 111101: 7.0}), 2, 0.0), "b.xlsx")

    stored = tb_store.load_ytd(db, period)
    assert {a: b.ytd for a, b in stored.items()} == {411101: -7.0, 111101: 7.0}
    assert tb_store.load_ytd(db, Period(2026, 3)) is None
    periods = tb_store.list_periods(db)
    assert [(p.period_year, p.period_month, p.source_filename) for p in periods] == [(2026, 6, "b.xlsx")]
