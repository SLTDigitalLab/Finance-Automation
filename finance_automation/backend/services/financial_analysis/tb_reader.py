"""
Reads a monthly detail trial balance export ("Detail TB_Jun 2026.xlsx").

Expected columns (located by header text, so column order may change):
  A/c | A/c Name | GL code | Beginning balance | PTD <Mon YY> | YTD <Mon YY>

The period comes from the "YTD <Mon YY>" header. Rows are one per GL code
combination (~50k); they are summed to one balance per natural account, which
is all the P&L analysis needs. Amounts stay in rupees with the TB sign
convention (debits positive, credits negative).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd

from services.financial_analysis.periods import Period, parse_period
from utils.logger import logger

ACCOUNT_SEGMENT = 5          # natural account is the 6th segment of the GL code
HEADER_SEARCH_ROWS = 20
BALANCE_TOLERANCE = 100.0    # rupees; the exports carry small rounding differences
ROW_TOLERANCE = 1.0          # rupees; per row Beginning + PTD vs YTD


class TBFormatError(ValueError):
    """The file is not a detail trial balance in the expected layout."""


@dataclass
class AccountBalance:
    account: int
    name: str
    beginning: float = 0.0
    ptd: float = 0.0
    ytd: float = 0.0


@dataclass
class TrialBalance:
    period: Period
    accounts: Dict[int, AccountBalance]
    row_count: int
    net_ytd: float
    warnings: List[str] = field(default_factory=list)


def _norm(value) -> str:
    return re.sub(r"[^a-z]", "", str(value).lower()) if value is not None else ""


def _find_columns(header: List[object]) -> Dict[str, int]:
    cols: Dict[str, int] = {}
    for i, cell in enumerate(header):
        key = _norm(cell)
        if key == "ac":
            cols["account"] = i
        elif key == "acname":
            cols["name"] = i
        elif key == "glcode":
            cols["gl_code"] = i
        elif key.startswith("beginningbalance") or key.startswith("openingbalance"):
            cols["beginning"] = i
        elif key.startswith("ptd"):
            cols["ptd"] = i
        elif key.startswith("ytd"):
            cols["ytd"] = i
    return cols


def _account_from_gl(gl_code) -> Optional[int]:
    parts = str(gl_code).split(".")
    if len(parts) > ACCOUNT_SEGMENT and parts[ACCOUNT_SEGMENT].strip().isdigit():
        return int(parts[ACCOUNT_SEGMENT])
    return None


def read_trial_balance(path: Union[str, Path], sheet_name: Union[int, str] = 0) -> TrialBalance:
    path = Path(path)
    try:
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object)
    except Exception as exc:
        raise TBFormatError(f"Could not open {path.name} as an Excel workbook: {exc}") from exc

    header_row, cols = None, {}
    for i in range(min(HEADER_SEARCH_ROWS, len(raw))):
        cols = _find_columns(list(raw.iloc[i]))
        if "ytd" in cols and ("account" in cols or "gl_code" in cols):
            header_row = i
            break
    if header_row is None:
        raise TBFormatError(
            f"{path.name}: could not find the trial balance header row "
            "(expected columns 'A/c', 'GL code' and 'YTD <Mon YY>')"
        )

    ytd_header = raw.iat[header_row, cols["ytd"]]
    period = parse_period(ytd_header) or parse_period(path.stem)
    if period is None:
        raise TBFormatError(f"{path.name}: could not read the period from the header '{ytd_header}'")

    data = raw.iloc[header_row + 1:]
    warnings: List[str] = []

    def amounts(key: str) -> pd.Series:
        if key not in cols:
            return pd.Series(0.0, index=data.index)
        return pd.to_numeric(data.iloc[:, cols[key]], errors="coerce").fillna(0.0)

    ytd, ptd, beginning = amounts("ytd"), amounts("ptd"), amounts("beginning")

    account = pd.Series(pd.NA, index=data.index, dtype=object)
    if "account" in cols:
        account = pd.to_numeric(data.iloc[:, cols["account"]], errors="coerce")
    if "gl_code" in cols:
        from_gl = data.iloc[:, cols["gl_code"]].map(_account_from_gl)
        account = account.fillna(from_gl) if "account" in cols else from_gl
    names = data.iloc[:, cols["name"]].astype(str).str.strip() if "name" in cols else pd.Series("", index=data.index)

    blank = account.isna()
    unidentified = blank & ((ytd != 0) | (ptd != 0))
    if unidentified.any():
        raise TBFormatError(
            f"{path.name}: {int(unidentified.sum())} rows have amounts but no account number "
            f"(first at Excel row {int(unidentified.idxmax()) + 1})"
        )

    frame = pd.DataFrame({
        "account": account[~blank].astype(int),
        "name": names[~blank],
        "beginning": beginning[~blank],
        "ptd": ptd[~blank],
        "ytd": ytd[~blank],
    })
    if frame.empty:
        raise TBFormatError(f"{path.name}: no trial balance rows found")

    if "ptd" in cols and "beginning" in cols:
        off = (frame["beginning"] + frame["ptd"] - frame["ytd"]).abs() > ROW_TOLERANCE
        if off.any():
            warnings.append(f"{int(off.sum())} rows where Beginning balance + PTD differs from YTD by more than {ROW_TOLERANCE:g}")

    net_ytd = float(frame["ytd"].sum())
    if abs(net_ytd) > BALANCE_TOLERANCE:
        warnings.append(f"Trial balance does not net to zero: YTD total is {net_ytd:,.2f}")

    grouped = frame.groupby("account").agg(
        name=("name", "first"), beginning=("beginning", "sum"), ptd=("ptd", "sum"), ytd=("ytd", "sum")
    )
    accounts = {
        int(acc): AccountBalance(int(acc), row["name"], float(row["beginning"]), float(row["ptd"]), float(row["ytd"]))
        for acc, row in grouped.iterrows()
    }

    for w in warnings:
        logger.warning(f"{path.name}: {w}")
    logger.info(f"Read TB {path.name}: {period.label}, {len(frame)} rows, {len(accounts)} accounts")
    return TrialBalance(period=period, accounts=accounts, row_count=len(frame), net_ytd=net_ytd, warnings=warnings)
