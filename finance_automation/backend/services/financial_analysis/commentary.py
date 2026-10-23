"""
Rule-based narrative for the Financial Analysis Report.

Sentences follow the wording of Finance's report ("increased by xx.x% (LKR
x,xxx Mn)") and name the GL accounts that moved the most. They state what the
trial balance shows; business reasons (tariff revisions, salary increments,
...) are for Finance to add when they review the draft.
"""
from typing import List, Optional

from services.financial_analysis.pl_engine import Comparison, Driver

# A movement smaller than this (Rs Mn) is described as "in line".
FLAT_THRESHOLD = 0.5
# Drivers named in a sentence: at most this many, each at least this share of the line's movement.
MAX_NAMED_DRIVERS = 3
MIN_DRIVER_SHARE = 0.05


def money(value: float) -> str:
    """1234.5 -> '1,235'; negatives in brackets as in Finance's tables."""
    rounded = round(value)
    text = f"{abs(rounded):,.0f}"
    return f"({text})" if rounded < 0 else text


def percent(value: Optional[float], decimals: int = 1) -> str:
    if value is None:
        return "N/A"
    rounded = round(value * 100, decimals)
    text = f"{abs(rounded):.{decimals}f}%"
    return f"({text})" if rounded < 0 else text


def _amount(value: float) -> str:
    return f"LKR {abs(round(value)):,.0f} Mn"


def change_phrase(current: float, base: float) -> str:
    """'increased by 12.3% (LKR 1,234 Mn)' for amounts shown positive (costs as positive costs)."""
    diff = current - base
    if abs(diff) < FLAT_THRESHOLD:
        return "remained in line"
    verb = "increased" if diff > 0 else "decreased"
    if not base:
        return f"{verb} by {_amount(diff)}"
    return f"{verb} by {abs(diff) / abs(base) * 100:.1f}% ({_amount(diff)})"


def _driver_list(drivers: List[Driver], line_variance: float, cost: bool) -> str:
    """'412101 Rental - Gross (+LKR 7,426 Mn) and 421115 ...'. Costs are signed as cost movements."""
    named = [d for d in drivers
             if line_variance and abs(d.variance) >= MIN_DRIVER_SHARE * abs(line_variance)][:MAX_NAMED_DRIVERS]
    if not named:
        return ""
    parts = []
    for d in named:
        move = -d.variance if cost else d.variance
        sign = "+" if move > 0 else "–"
        parts.append(f"{d.account} {d.name.strip()} ({sign}{_amount(move)})")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _lines(comparison: Comparison):
    return comparison.current.lines, comparison.base.lines


def revenue_paragraph(comparison: Comparison, subject: str, period_phrase: str) -> str:
    cur, base = _lines(comparison)
    text = f"{subject} revenue {change_phrase(cur['revenue'], base['revenue'])} {period_phrase}"
    variance = cur["revenue"] - base["revenue"]
    if abs(variance) < FLAT_THRESHOLD:
        return text + "."
    drivers = _driver_list(comparison.drivers("revenue"), variance, cost=False)
    if drivers:
        text += f", mainly due to movements in {drivers}"
    return text + "."


def opex_paragraph(comparison: Comparison, subject: str, period_phrase: str) -> str:
    cur, base = _lines(comparison)
    cur_opex, base_opex = -cur["operating_costs"], -base["operating_costs"]
    text = f"{subject} operating expenses {change_phrase(cur_opex, base_opex)} {period_phrase}"
    variance = cur["operating_costs"] - base["operating_costs"]
    if abs(variance) < FLAT_THRESHOLD:
        return text + "."
    drivers = _driver_list(comparison.drivers("operating_costs"), variance, cost=True)
    if drivers:
        text += f". The largest movements were in {drivers}"
    return text + "."


def _fx_phrase(current: float, base: float, current_label: str, base_label: str) -> str:
    def describe(value):
        if abs(value) < FLAT_THRESHOLD:
            return "no material exchange gain or loss"
        return f"an exchange {'gain' if value > 0 else 'loss'} of {_amount(value)}"
    return (f"The Company recorded {describe(current)} in {current_label}, "
            f"compared to {describe(base)} in {base_label}.")


def profit_paragraphs(comparison: Comparison, current_label: str, base_label: str) -> List[str]:
    cur, base = _lines(comparison)
    dep_cur = -(cur["depreciation"] + cur["amortisation"])
    dep_base = -(base["depreciation"] + base["amortisation"])
    first = (
        f"EBITDA {change_phrase(cur['ebitda'], base['ebitda'])} to {_amount(cur['ebitda'])}. "
        f"Depreciation and amortisation {change_phrase(dep_cur, dep_base)}, and Operating profit "
        f"{change_phrase(cur['operating_profit'], base['operating_profit'])} to "
        f"{_amount(cur['operating_profit'])} compared to {base_label}."
    )
    second = (
        f"Interest expenses {change_phrase(-cur['interest_expenses'], -base['interest_expenses'])}. "
        + _fx_phrase(cur["fx_gain_loss"], base["fx_gain_loss"], current_label, base_label)
        + f" As a result, Profit before tax {change_phrase(cur['profit_before_tax'], base['profit_before_tax'])}"
        f" and Profit after tax {change_phrase(cur['profit_after_tax'], base['profit_after_tax'])}, "
        f"reaching {_amount(cur['profit_after_tax'])} in {current_label}."
    )
    if cur["profit_after_tax"] < 0:
        second = second.replace(f"reaching {_amount(cur['profit_after_tax'])}",
                                f"a loss of {_amount(cur['profit_after_tax'])}")
    return [first, second]
