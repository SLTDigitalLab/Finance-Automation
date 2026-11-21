"""
Builds the P&L and the comparisons for the Financial Analysis Report.

Sign convention: amounts are Rs million with income positive and costs
negative (TB balance x -1 / 1,000,000), the same as the mapping sheet. Every
line therefore adds up to its subtotal, and a positive variance is always
favourable.

For a quarter the report compares:
  quarter_vs_last_year   current quarter vs the same quarter last year
  quarter_vs_previous    current quarter vs the preceding quarter
  ytd_vs_last_year       YTD at the quarter end vs YTD at the same month last year
  quarter_vs_budget      not available until a budget file is provided
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from services.financial_analysis.mapping_reader import GLMapping
from services.financial_analysis.periods import Period, Quarter
from services.financial_analysis.tb_reader import AccountBalance

DIVISOR = 1_000_000
PL_ACCOUNT_START = 400000                     # natural accounts from 4xxxxx are P&L
APPROPRIATION_RANGE = (631000, 639999)        # dividends: below PAT, not part of the P&L

# Display order: (key, label, is_subtotal)
PL_LAYOUT: List[Tuple[str, str, bool]] = [
    ("revenue", "Revenue", False),
    ("operating_costs", "Operating costs", False),
    ("ebitda", "EBITDA", True),
    ("depreciation", "Depreciation", False),
    ("amortisation", "Amortisation and impairment of intangible assets", False),
    ("operating_profit", "Operating profit", True),
    ("other_income", "Other income", False),
    ("interest_expenses", "Interest expenses", False),
    ("fx_gain_loss", "Foreign exchange gain / (loss)", False),
    ("interest_income", "Interest income", False),
    ("share_of_associate", "Share of profit from associate company", False),
    ("profit_before_tax", "Profit before tax", True),
    ("taxation", "Taxation", False),
    ("profit_after_tax", "Profit after tax", True),
    ("oci_cash_flow_hedges", "Net movement on cash flow hedges", False),
    ("oci_fair_value", "Net change in fair value of available-for-sale financial assets", False),
    ("oci_actuarial", "Defined benefit plan actuarial gain / (loss)", False),
    ("oci_tax", "Tax on other comprehensive income", False),
    ("other_comprehensive_income", "Other comprehensive income, net of tax", True),
    ("total_comprehensive_income", "Total comprehensive income", True),
]
LABELS = {key: label for key, label, _ in PL_LAYOUT}

SUBTOTALS: Dict[str, List[str]] = {
    "ebitda": ["revenue", "operating_costs"],
    "operating_profit": ["ebitda", "depreciation", "amortisation"],
    "profit_before_tax": ["operating_profit", "other_income", "interest_expenses",
                          "fx_gain_loss", "interest_income", "share_of_associate"],
    "profit_after_tax": ["profit_before_tax", "taxation"],
    "other_comprehensive_income": ["oci_cash_flow_hedges", "oci_fair_value", "oci_actuarial", "oci_tax"],
    "total_comprehensive_income": ["profit_after_tax", "other_comprehensive_income"],
}

MARGINS = {
    "ebitda_margin": "ebitda",
    "operating_margin": "operating_profit",
    "pbt_margin": "profit_before_tax",
    "pat_margin": "profit_after_tax",
}


class MissingPeriodsError(LookupError):
    def __init__(self, periods: List[Period]):
        self.periods = sorted(set(periods))
        super().__init__("Trial balances needed but not loaded: " + ", ".join(p.label for p in self.periods))


@dataclass
class AccountAmount:
    account: int
    name: str
    line: str
    amount: float           # Rs Mn, income positive


@dataclass
class PLFigures:
    label: str
    lines: Dict[str, float]
    accounts: Dict[int, AccountAmount]

    def margin(self, line: str) -> Optional[float]:
        revenue = self.lines.get("revenue", 0.0)
        return self.lines[line] / revenue if revenue else None

    @property
    def margins(self) -> Dict[str, Optional[float]]:
        return {name: self.margin(line) for name, line in MARGINS.items()}


@dataclass
class UnmappedAccount:
    account: int
    name: str
    amount: float           # Rs Mn in the period where it was found
    period: str


def _with_subtotals(lines: Dict[str, float]) -> Dict[str, float]:
    out = {key: lines.get(key, 0.0) for key, _, is_sub in PL_LAYOUT if not is_sub}
    for key, parts in SUBTOTALS.items():   # ordered so each subtotal's parts already exist
        out[key] = sum(out[p] for p in parts)
    return {key: out[key] for key, _, _ in PL_LAYOUT}


def compute_pl(balances: Mapping[int, AccountBalance], mapping: GLMapping, label: str,
               amount_field: str = "ytd") -> Tuple[PLFigures, List[UnmappedAccount]]:
    """
    P&L from YTD balances ("ptd" gives the month alone). Also returns P&L
    accounts the mapping does not cover.
    """
    totals: Dict[str, float] = {}
    accounts: Dict[int, AccountAmount] = {}
    unmapped: List[UnmappedAccount] = []
    for acc, bal in balances.items():
        if acc < PL_ACCOUNT_START:
            continue
        raw = getattr(bal, amount_field)
        amount = -raw / DIVISOR
        line = mapping.line_for(acc)
        if line is None:
            if not APPROPRIATION_RANGE[0] <= acc <= APPROPRIATION_RANGE[1] and abs(raw) >= 0.5:
                unmapped.append(UnmappedAccount(acc, bal.name, amount, label))
            continue
        totals[line] = totals.get(line, 0.0) + amount
        accounts[acc] = AccountAmount(acc, bal.name, line, amount)
    return PLFigures(label, _with_subtotals(totals), accounts), unmapped


def subtract(a: PLFigures, b: PLFigures, label: str) -> PLFigures:
    """a - b, line by line and account by account (quarter = YTD end - YTD start)."""
    lines = {key: a.lines[key] - b.lines[key] for key in a.lines}
    accounts: Dict[int, AccountAmount] = {}
    for acc in set(a.accounts) | set(b.accounts):
        x, y = a.accounts.get(acc), b.accounts.get(acc)
        ref = x or y
        accounts[acc] = AccountAmount(acc, ref.name, ref.line, (x.amount if x else 0.0) - (y.amount if y else 0.0))
    return PLFigures(label, lines, accounts)


@dataclass
class VarianceRow:
    key: str
    label: str
    is_subtotal: bool
    current: float
    base: float
    variance: float
    variance_pct: Optional[float]   # variance / |base|; None when base is zero


@dataclass
class Driver:
    account: int
    name: str
    current: float
    base: float
    variance: float
    share: Optional[float]          # of the line's variance


@dataclass
class Comparison:
    key: str
    title: str
    current: PLFigures
    base: PLFigures

    @property
    def rows(self) -> List[VarianceRow]:
        out = []
        for key, label, is_sub in PL_LAYOUT:
            cur, base = self.current.lines[key], self.base.lines[key]
            var = cur - base
            out.append(VarianceRow(key, label, is_sub, cur, base, var, var / abs(base) if base else None))
        return out

    def drivers(self, line: str, limit: int = 5) -> List[Driver]:
        """Accounts behind a line's variance, largest movement first. Subtotals use their component accounts."""
        lines = _leaf_lines(line)
        line_var = self.current.lines[line] - self.base.lines[line]
        found = []
        for acc in set(self.current.accounts) | set(self.base.accounts):
            x, y = self.current.accounts.get(acc), self.base.accounts.get(acc)
            ref = x or y
            if ref.line not in lines:
                continue
            cur, base = (x.amount if x else 0.0), (y.amount if y else 0.0)
            var = cur - base
            if abs(var) < 1e-9:
                continue
            found.append(Driver(acc, ref.name, cur, base, var, var / line_var if line_var else None))
        found.sort(key=lambda d: (-abs(d.variance), d.account))
        return found[:limit]


def _leaf_lines(line: str) -> set:
    if line not in SUBTOTALS:
        return {line}
    return set().union(*(_leaf_lines(p) for p in SUBTOTALS[line]))


@dataclass
class BudgetFigures:
    quarter: Quarter
    quarter_opex: Optional[float] = None
    quarter_actual_opex: Optional[float] = None
    ytd_opex: Optional[float] = None
    ytd_opex_actual: Optional[float] = None
    ytd_opex_ly_actual: Optional[float] = None
    ytd_direct_expenses: Optional[float] = None
    ytd_direct_actual: Optional[float] = None
    ytd_direct_ly_actual: Optional[float] = None
    ytd_sales_expenses: Optional[float] = None
    ytd_sales_actual: Optional[float] = None
    ytd_marketing_expenses: Optional[float] = None
    ytd_marketing_actual: Optional[float] = None
    ytd_sales_mktg_expenses: Optional[float] = None
    ytd_sales_mktg_actual: Optional[float] = None
    ytd_sales_mktg_ly_actual: Optional[float] = None
    ytd_ga_costs: Optional[float] = None
    ytd_ga_actual: Optional[float] = None
    ytd_ga_ly_actual: Optional[float] = None
    ytd_staff_costs: Optional[float] = None
    ytd_staff_actual: Optional[float] = None
    ytd_staff_ly_actual: Optional[float] = None
    quarter_direct_budget: Optional[float] = None
    quarter_direct_actual: Optional[float] = None
    quarter_sales_mktg_budget: Optional[float] = None
    quarter_sales_mktg_actual: Optional[float] = None
    quarter_ga_budget: Optional[float] = None
    quarter_ga_actual: Optional[float] = None
    quarter_staff_budget: Optional[float] = None
    quarter_staff_actual: Optional[float] = None
    lines: Dict[str, float] = field(default_factory=dict)


@dataclass
class FinancialAnalysis:
    quarter: Quarter
    comparisons: Dict[str, Comparison]
    unmapped: List[UnmappedAccount] = field(default_factory=list)
    budget_available: bool = False
    budget: Optional[BudgetFigures] = None


YTDLoader = Callable[[Period], Optional[Mapping[int, AccountBalance]]]


@dataclass
class MonthFigures:
    period: Period
    revenue: Optional[float]        # Rs Mn for the month; None when the TB is not loaded
    opex: Optional[float]           # Rs Mn, shown positive


def monthly_trend(end: Period, load_ytd: YTDLoader, mapping: GLMapping, months: int = 13) -> List[MonthFigures]:
    """Revenue and opex for each of the `months` months ending at `end`, from each month's PTD column."""
    periods = []
    year, month = end.year, end.month
    for _ in range(months):
        periods.append(Period(year, month))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    out = []
    for period in reversed(periods):
        balances = load_ytd(period)
        if balances is None:
            out.append(MonthFigures(period, None, None))
            continue
        pl, _ = compute_pl(balances, mapping, period.label, amount_field="ptd")
        out.append(MonthFigures(period, pl.lines["revenue"], -pl.lines["operating_costs"]))
    return out


def required_periods(quarter: Quarter) -> List[Period]:
    needed = set(quarter.ytd_periods())
    needed |= set(quarter.same_quarter_last_year().ytd_periods())
    needed |= set(quarter.previous().ytd_periods())
    return sorted(needed)


def build_analysis(
    quarter: Quarter,
    load_ytd: YTDLoader,
    mapping: GLMapping,
    budget_end: Optional[Dict] = None,
    budget_start: Optional[Dict] = None,
) -> FinancialAnalysis:
    """
    load_ytd(period) returns that month's account balances, or None if the
    trial balance is not loaded. Raises MissingPeriodsError listing every
    trial balance still needed.
    """
    needed = required_periods(quarter)
    balances = {p: load_ytd(p) for p in needed}
    missing = [p for p, b in balances.items() if b is None]
    if missing:
        raise MissingPeriodsError(missing)

    ytd: Dict[Period, PLFigures] = {}
    unmapped: Dict[int, UnmappedAccount] = {}
    for period in needed:
        ytd[period], found = compute_pl(balances[period], mapping, f"YTD {period.label}")
        for u in found:
            unmapped.setdefault(u.account, u)

    def quarter_figures(q: Quarter) -> PLFigures:
        end = ytd[q.end]
        if q.quarter == 1:
            return PLFigures(q.label, end.lines, end.accounts)
        return subtract(end, ytd[q.previous().end], q.label)

    current = quarter_figures(quarter)
    last_year = quarter.same_quarter_last_year()
    comparisons = {
        "quarter_vs_last_year": Comparison(
            "quarter_vs_last_year", f"{quarter.label} vs {last_year.label}",
            current, quarter_figures(last_year)),
        "quarter_vs_previous": Comparison(
            "quarter_vs_previous", f"{quarter.label} vs {quarter.previous().label}",
            current, quarter_figures(quarter.previous())),
        "ytd_vs_last_year": Comparison(
            "ytd_vs_last_year", f"YTD {quarter.end.label} vs YTD {last_year.end.label}",
            ytd[quarter.end], ytd[last_year.end]),
    }

    budget_available = budget_end is not None
    budget_fig = None
    if budget_end:
        summ_end = budget_end.get("summary", {})
        summ_start = budget_start.get("summary", {}) if budget_start else {}
        lines_raw = budget_end.get("lines", {})

        def _val(s_dict, cat, field_name):
            return s_dict.get(cat, {}).get(field_name)

        ytd_opex = budget_end.get("operating_cost_ytd") or _val(summ_end, "operating_cost", "ytd_budget")
        ytd_opex_act = _val(summ_end, "operating_cost", "ytd_actual")
        ytd_opex_ly = _val(summ_end, "operating_cost", "ytd_ly_actual")

        ytd_direct = _val(summ_end, "direct_expenses", "ytd_budget")
        ytd_direct_act = _val(summ_end, "direct_expenses", "ytd_actual")
        ytd_direct_ly = _val(summ_end, "direct_expenses", "ytd_ly_actual")

        ytd_sales = _val(summ_end, "sales_expenses", "ytd_budget")
        ytd_sales_act = _val(summ_end, "sales_expenses", "ytd_actual")
        ytd_mktg = _val(summ_end, "marketing_expenses", "ytd_budget")
        ytd_mktg_act = _val(summ_end, "marketing_expenses", "ytd_actual")

        ytd_sm = _val(summ_end, "sales_marketing", "ytd_budget")
        ytd_sm_act = _val(summ_end, "sales_marketing", "ytd_actual")
        ytd_sm_ly = _val(summ_end, "sales_marketing", "ytd_ly_actual")

        ytd_ga = _val(summ_end, "ga_costs", "ytd_budget")
        ytd_ga_act = _val(summ_end, "ga_costs", "ytd_actual")
        ytd_ga_ly = _val(summ_end, "ga_costs", "ytd_ly_actual")

        ytd_staff = _val(summ_end, "staff_costs", "ytd_budget")
        ytd_staff_act = _val(summ_end, "staff_costs", "ytd_actual")
        ytd_staff_ly = _val(summ_end, "staff_costs", "ytd_ly_actual")

        def _q_diff(end_val, start_val):
            if end_val is None:
                return None
            if quarter.quarter == 1 or start_val is None:
                return end_val
            return end_val - start_val

        quarter_opex = None
        if ytd_opex is not None:
            if quarter.quarter == 1:
                quarter_opex = ytd_opex
            elif budget_start and budget_start.get("operating_cost_ytd") is not None:
                quarter_opex = ytd_opex - budget_start.get("operating_cost_ytd")
            elif "Total Operating Cost" in lines_raw and isinstance(lines_raw["Total Operating Cost"], dict):
                quarter_opex = lines_raw["Total Operating Cost"].get("ptd")

        quarter_dir_bud = _q_diff(ytd_direct, _val(summ_start, "direct_expenses", "ytd_budget"))
        quarter_dir_act = _q_diff(ytd_direct_act, _val(summ_start, "direct_expenses", "ytd_actual"))
        quarter_sm_bud = _q_diff(ytd_sm, _val(summ_start, "sales_marketing", "ytd_budget"))
        quarter_sm_act = _q_diff(ytd_sm_act, _val(summ_start, "sales_marketing", "ytd_actual"))
        quarter_ga_bud = _q_diff(ytd_ga, _val(summ_start, "ga_costs", "ytd_budget"))
        quarter_ga_act = _q_diff(ytd_ga_act, _val(summ_start, "ga_costs", "ytd_actual"))
        quarter_staff_bud = _q_diff(ytd_staff, _val(summ_start, "staff_costs", "ytd_budget"))
        quarter_staff_act = _q_diff(ytd_staff_act, _val(summ_start, "staff_costs", "ytd_actual"))

        quarter_act_opex = -current.lines.get("operating_costs", 0.0)
        lines = {k.strip(): (v.get("ytd") if isinstance(v, dict) else v) for k, v in lines_raw.items()}

        budget_fig = BudgetFigures(
            quarter=quarter,
            quarter_opex=quarter_opex,
            quarter_actual_opex=quarter_act_opex,
            ytd_opex=ytd_opex,
            ytd_opex_actual=ytd_opex_act,
            ytd_opex_ly_actual=ytd_opex_ly,
            ytd_direct_expenses=ytd_direct,
            ytd_direct_actual=ytd_direct_act,
            ytd_direct_ly_actual=ytd_direct_ly,
            ytd_sales_expenses=ytd_sales,
            ytd_sales_actual=ytd_sales_act,
            ytd_marketing_expenses=ytd_mktg,
            ytd_marketing_actual=ytd_mktg_act,
            ytd_sales_mktg_expenses=ytd_sm,
            ytd_sales_mktg_actual=ytd_sm_act,
            ytd_sales_mktg_ly_actual=ytd_sm_ly,
            ytd_ga_costs=ytd_ga,
            ytd_ga_actual=ytd_ga_act,
            ytd_ga_ly_actual=ytd_ga_ly,
            ytd_staff_costs=ytd_staff,
            ytd_staff_actual=ytd_staff_act,
            ytd_staff_ly_actual=ytd_staff_ly,
            quarter_direct_budget=quarter_dir_bud,
            quarter_direct_actual=quarter_dir_act,
            quarter_sales_mktg_budget=quarter_sm_bud,
            quarter_sales_mktg_actual=quarter_sm_act,
            quarter_ga_budget=quarter_ga_bud,
            quarter_ga_actual=quarter_ga_act,
            quarter_staff_budget=quarter_staff_bud,
            quarter_staff_actual=quarter_staff_act,
            lines=lines,
        )

    return FinancialAnalysis(
        quarter=quarter,
        comparisons=comparisons,
        unmapped=sorted(unmapped.values(), key=lambda u: u.account),
        budget_available=budget_available,
        budget=budget_fig,
    )
