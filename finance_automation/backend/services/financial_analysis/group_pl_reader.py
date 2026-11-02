"""
Reader for the Group P&L Excel workbook (sheet: '1.PL Board').

Extracts entity-level financial figures for ALL available period blocks:
  Telecom, Mobitel, SLTSL, SLTDS, SLTPML, SLTCAM, SLTHCS, Xyntac, Talentfort, SLTVCOM, Group

CRITICAL ENTITY DISTINCTION:
  - 'Mobitel' column  = Mobitel standalone (NOT the same as 'Group')
  - 'Group'  column   = All subsidiaries consolidated
  - 'Mobitel Group' referenced in the write-up = Mobitel + eChannelling (different scope)
  These are NOT interchangeable and are never silently substituted.

Sheet layout (from full inspection of Group P&L_Jun 26_V2.xlsx, sheet '1.PL Board'):
  Row 7:  Entity headers (1-indexed): Telecom, Mobitel, SLTSL, SLTDS, SLTPML, SLTCAM,
          SLTHCS, Xyntac, Talentfort, SLTVCOM, Group — repeated per block.
  Rows 8-32: P&L data rows (column B = row label)

  12 data blocks — each block spans 11 columns (one per entity), 1-indexed:
  Block name                    start_col  end_col
  YTD Jun 26                        3        13
  YTD Jun 25                       16        26
  Q1'26                            29        39
  Q1'25                            42        52
  Q2'26                            54        64
  Q2'25                            66        76
  Var Q2'26 vs Q2'25 LKR Mn        78        88
  Var Q2'26 vs Q2'25 %             90       100
  Var Q2'26 vs Q1'26 LKR Mn       102       112
  Var Q2'26 vs Q1'26 %            114       124
  Var YTD Jun'26 vs Jun'25 LKR Mn 126       136
  Var YTD Jun'26 vs Jun'25 %      138       148

  Within each block the entity column order is always:
    offset 0 = Telecom, offset 1 = Mobitel, offset 2 = SLTSL, offset 3 = SLTDS,
    offset 4 = SLTPML, offset 5 = SLTCAM, offset 6 = SLTHCS, offset 7 = Xyntac,
    offset 8 = Talentfort, offset 9 = SLTVCOM, offset 10 = Group

  P&L row positions (1-indexed):
    Row  8 = Revenue
    Row  9 = Direct Cost
    Row 10 = Gross Profit
    Row 17 = Operating Profit (EBIT)
    Row 25 = Profit Before Tax (PBT)
    Row 28 = Net Profit for the Period (NPAT / PAT)
    Row 30 = Opex (summary row)
    Row 31 = EBITDA

  For percentage blocks (Var % blocks): values stored as decimals (e.g. 0.117 = 11.7%).
  #DIV/0! errors are treated as None.
  All monetary figures are in LKR Mn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import openpyxl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — hardcoded from full workbook inspection
# ---------------------------------------------------------------------------

ENTITY_ORDER = [
    "Telecom", "Mobitel", "SLTSL", "SLTDS", "SLTPML",
    "SLTCAM", "SLTHCS", "Xyntac", "Talentfort", "SLTVCOM", "Group",
]
KNOWN_ENTITIES = ENTITY_ORDER  # alias for import compatibility

HEADER_ROW = 7   # 1-indexed row with entity names

# (block_attr, start_col_1indexed, end_col_1indexed, is_percent_block)
BLOCKS = [
    ("ytd_current",        3,    13,   False),  # YTD Jun 26
    ("ytd_prior",         16,    26,   False),  # YTD Jun 25
    ("q_prev",            29,    39,   False),  # Q1'26
    ("q1_prior",          42,    52,   False),  # Q1'25 (historical)
    ("q_current",         54,    64,   False),  # Q2'26
    ("q_prior",           66,    76,   False),  # Q2'25
    ("var_q_vs_qly_lkr",  78,    88,   False),  # Var Q2'26 vs Q2'25  LKR Mn
    ("var_q_vs_qly_pct",  90,   100,   True),   # Var Q2'26 vs Q2'25  %
    ("var_q_vs_qprev_lkr",102,  112,   False),  # Var Q2'26 vs Q1'26  LKR Mn
    ("var_q_vs_qprev_pct",114,  124,   True),   # Var Q2'26 vs Q1'26  %
    ("var_ytd_lkr",       126,  136,   False),  # Var YTD Jun'26 vs Jun'25 LKR Mn
    ("var_ytd_pct",       138,  148,   True),   # Var YTD Jun'26 vs Jun'25 %
]

# P&L data rows (1-indexed)
PL_ROWS = {
    "revenue":      8,
    "direct_cost":  9,
    "gross_profit": 10,
    "ebit":         17,   # Operating Profit
    "pbt":          25,   # Profit Before Tax
    "npat":         28,   # Net Profit for the Period
    "opex":         30,   # Opex summary row
    "ebitda":       31,   # EBITDA
}

SHEET_NAME = "1.PL Board"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PeriodBlock:
    """Financial figures for one entity in one period/variance block."""
    revenue:      Optional[float] = None
    direct_cost:  Optional[float] = None
    gross_profit: Optional[float] = None
    opex:         Optional[float] = None
    ebitda:       Optional[float] = None
    ebit:         Optional[float] = None   # Operating Profit
    pbt:          Optional[float] = None
    npat:         Optional[float] = None


@dataclass
class EntityData:
    """All period blocks for a single entity."""
    name: str = ""
    # Actuals
    ytd_current:  PeriodBlock = field(default_factory=PeriodBlock)   # YTD Jun 26
    ytd_prior:    PeriodBlock = field(default_factory=PeriodBlock)   # YTD Jun 25
    q_current:    PeriodBlock = field(default_factory=PeriodBlock)   # Q2'26
    q_prior:      PeriodBlock = field(default_factory=PeriodBlock)   # Q2'25
    q_prev:       PeriodBlock = field(default_factory=PeriodBlock)   # Q1'26
    q1_prior:     PeriodBlock = field(default_factory=PeriodBlock)   # Q1'25
    # Pre-computed variances (read directly from Excel — do NOT recalculate)
    var_q_vs_qly_lkr:   PeriodBlock = field(default_factory=PeriodBlock)  # Q2'26 vs Q2'25 LKR Mn
    var_q_vs_qly_pct:   PeriodBlock = field(default_factory=PeriodBlock)  # Q2'26 vs Q2'25 %
    var_q_vs_qprev_lkr: PeriodBlock = field(default_factory=PeriodBlock)  # Q2'26 vs Q1'26 LKR Mn
    var_q_vs_qprev_pct: PeriodBlock = field(default_factory=PeriodBlock)  # Q2'26 vs Q1'26 %
    var_ytd_lkr:        PeriodBlock = field(default_factory=PeriodBlock)  # YTD LKR Mn
    var_ytd_pct:        PeriodBlock = field(default_factory=PeriodBlock)  # YTD %


# ---------------------------------------------------------------------------
# Backwards-compatible legacy flat data class
# ---------------------------------------------------------------------------

@dataclass
class EntityFigures:
    """Legacy flat data class for backwards compatibility.
    Populated from EntityData.ytd_current / ytd_prior so that
    existing code that imports EntityFigures continues to work.
    """
    entity: str = ""
    # Current period (YTD Jun 2026)
    revenue_current:      Optional[float] = None
    direct_cost_current:  Optional[float] = None
    gross_profit_current: Optional[float] = None
    opex_current:         Optional[float] = None
    ebitda_current:       Optional[float] = None
    depreciation_current: Optional[float] = None
    ebit_current:         Optional[float] = None
    pbt_current:          Optional[float] = None
    npat_current:         Optional[float] = None
    # Prior period (YTD Jun 2025)
    revenue_prior:        Optional[float] = None
    direct_cost_prior:    Optional[float] = None
    gross_profit_prior:   Optional[float] = None
    opex_prior:           Optional[float] = None
    ebitda_prior:         Optional[float] = None
    depreciation_prior:   Optional[float] = None
    ebit_prior:           Optional[float] = None
    pbt_prior:            Optional[float] = None
    npat_prior:           Optional[float] = None

    def variance(self, metric: str) -> Optional[float]:
        cur = getattr(self, f"{metric}_current", None)
        pri = getattr(self, f"{metric}_prior", None)
        if cur is None or pri is None:
            return None
        return cur - pri

    def variance_pct(self, metric: str) -> Optional[float]:
        var = self.variance(metric)
        pri = getattr(self, f"{metric}_prior", None)
        if var is None or not pri:
            return None
        return var / abs(pri)


def _entity_data_to_legacy(ed: EntityData) -> EntityFigures:
    """Convert EntityData -> EntityFigures (YTD only) for backwards compatibility."""
    c = ed.ytd_current
    p = ed.ytd_prior
    return EntityFigures(
        entity=ed.name,
        revenue_current=c.revenue,          revenue_prior=p.revenue,
        direct_cost_current=c.direct_cost,  direct_cost_prior=p.direct_cost,
        gross_profit_current=c.gross_profit, gross_profit_prior=p.gross_profit,
        opex_current=c.opex,                opex_prior=p.opex,
        ebitda_current=c.ebitda,            ebitda_prior=p.ebitda,
        ebit_current=c.ebit,                ebit_prior=p.ebit,
        pbt_current=c.pbt,                  pbt_prior=p.pbt,
        npat_current=c.npat,                npat_prior=p.npat,
    )


@dataclass
class GroupPLData:
    """Structured Group P&L data across all period blocks."""
    # New multi-period store: entity name -> EntityData
    entity_data: Dict[str, EntityData] = field(default_factory=dict)
    # Legacy flat store (YTD only) for backwards-compat with validation_dashboard, etc.
    entities: Dict[str, EntityFigures] = field(default_factory=dict)
    period_current: str = "YTD Jun 2026"
    period_prior:   str = "YTD Jun 2025"
    source_filename: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def periods(self) -> Dict[str, str]:
        return {"current": self.period_current, "prior": self.period_prior}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    """Convert a cell value to float; return None for errors/blanks/NaN."""
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        if not s or s.startswith("#"):  # e.g. #DIV/0!
            return None
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None
    try:
        f = float(val)
        return None if f != f else f    # NaN -> None
    except (TypeError, ValueError):
        return None


def _read_block(ws, start_col: int, entity_idx: int) -> PeriodBlock:
    """
    Read one PeriodBlock for one entity from the worksheet.
    start_col : 1-indexed first column of the block
    entity_idx: 1-indexed offset within block (Telecom=1, Mobitel=2, ..., Group=11)
    """
    col = start_col + entity_idx - 1
    blk = PeriodBlock()
    for attr, row in PL_ROWS.items():
        v = _safe_float(ws.cell(row=row, column=col).value)
        setattr(blk, attr, v)
    return blk


# ---------------------------------------------------------------------------
# Main reader
# ---------------------------------------------------------------------------

class GroupPLReader:
    """Reads the '1.PL Board' sheet from the Group P&L workbook.

    Returns a GroupPLData containing:
      entity_data : Dict[entity_name, EntityData]   -- all 12 period blocks
      entities    : Dict[entity_name, EntityFigures] -- YTD only (legacy compat)
    """

    SHEET_NAME = SHEET_NAME

    def read(self, path: str | Path) -> GroupPLData:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Group P&L file not found: {path}")

        try:
            wb = openpyxl.load_workbook(str(path), data_only=True)
        except Exception as exc:
            raise ValueError(f"Cannot open workbook: {exc}") from exc

        if self.SHEET_NAME not in wb.sheetnames:
            available = ", ".join(wb.sheetnames)
            raise ValueError(
                f"Sheet '{self.SHEET_NAME}' not found. Available sheets: {available}"
            )

        ws = wb[self.SHEET_NAME]
        warnings: List[str] = []

        # Build EntityData for each entity
        entity_data: Dict[str, EntityData] = {}
        for entity_idx, entity_name in enumerate(ENTITY_ORDER, start=1):
            ed = EntityData(name=entity_name)
            for block_attr, start_col, _end_col, _is_pct in BLOCKS:
                blk = _read_block(ws, start_col, entity_idx)
                setattr(ed, block_attr, blk)
            entity_data[entity_name] = ed

        # Build legacy EntityFigures (YTD only) for backwards compatibility
        entities: Dict[str, EntityFigures] = {
            name: _entity_data_to_legacy(ed)
            for name, ed in entity_data.items()
        }

        # Warn on missing critical fields for key entities
        for entity_name in ["Group", "Mobitel", "Telecom"]:
            ed = entity_data.get(entity_name)
            if ed is None:
                warnings.append(f"Entity '{entity_name}' not found in workbook.")
                continue
            for metric in ["revenue", "ebitda", "pbt", "npat"]:
                if getattr(ed.ytd_current, metric, None) is None:
                    warnings.append(
                        f"'{entity_name}' {metric} (YTD current) not found in '{self.SHEET_NAME}'."
                    )
                if getattr(ed.q_current, metric, None) is None:
                    warnings.append(
                        f"'{entity_name}' {metric} (Q2'26 current) not found in '{self.SHEET_NAME}'."
                    )

        logger.info(
            f"GroupPLReader: loaded {len(entity_data)} entities x {len(BLOCKS)} period blocks "
            f"from '{path.name}'."
        )

        return GroupPLData(
            entity_data=entity_data,
            entities=entities,
            period_current="YTD Jun 2026",
            period_prior="YTD Jun 2025",
            source_filename=path.name,
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def read_group_pl(path: str | Path) -> GroupPLData:
    """Reads Group P&L workbook and returns structured data."""
    return GroupPLReader().read(path)
