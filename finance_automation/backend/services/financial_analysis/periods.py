"""
Fiscal periods for the Financial Analysis Report.

The financial year runs January to December, so the YTD column of a trial
balance resets every January and a quarter's figures are its quarter-end YTD
less the previous quarter-end YTD of the same year (Q1 is just YTD March).
"""
import re
from dataclasses import dataclass
from typing import List, Optional

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# First three letters of a month name -> month number ("June", "Jun", "Sept" all match).
_MONTH_PREFIXES = {name.lower(): i + 1 for i, name in enumerate(MONTH_NAMES)}


@dataclass(frozen=True, order=True)
class Period:
    """A month-end, identified by calendar year and month."""
    year: int
    month: int

    def __post_init__(self):
        if not 1 <= self.month <= 12:
            raise ValueError(f"Invalid month {self.month}")

    @property
    def label(self) -> str:
        return f"{MONTH_NAMES[self.month - 1]} {self.year}"


@dataclass(frozen=True, order=True)
class Quarter:
    year: int
    quarter: int

    def __post_init__(self):
        if not 1 <= self.quarter <= 4:
            raise ValueError(f"Invalid quarter {self.quarter}")

    @property
    def label(self) -> str:
        return f"Q{self.quarter} {self.year}"

    @property
    def end(self) -> Period:
        return Period(self.year, self.quarter * 3)

    def previous(self) -> "Quarter":
        if self.quarter == 1:
            return Quarter(self.year - 1, 4)
        return Quarter(self.year, self.quarter - 1)

    def same_quarter_last_year(self) -> "Quarter":
        return Quarter(self.year - 1, self.quarter)

    def ytd_periods(self) -> List[Period]:
        """The trial balances needed to get this quarter's figures from YTD balances."""
        if self.quarter == 1:
            return [self.end]
        return [self.end, self.previous().end]

    @classmethod
    def ending(cls, period: Period) -> Optional["Quarter"]:
        if period.month % 3:
            return None
        return cls(period.year, period.month // 3)


def parse_period(text: str) -> Optional[Period]:
    """
    Reads a period from text such as "YTD June 26", "PTD Mar 25", "TB March 2026"
    or "Detail TB_Jun 25". Two-digit years are taken as 20YY.
    """
    if not text:
        return None
    for word, year in re.findall(r"(?<![A-Za-z])([A-Za-z]{3,9})[\s_'-]*(\d{4}|\d{2})(?!\d)", str(text)):
        month = _MONTH_PREFIXES.get(word[:3].lower())
        if month is None:
            continue
        year = int(year)
        if year < 100:
            year += 2000
        return Period(year, month)
    return None
