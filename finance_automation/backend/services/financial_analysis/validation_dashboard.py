"""
Validation Dashboard service for Financial Analysis reporting.
Tracks field population completeness, data sources (Trial Balance, Mobitel DOCX, Group P&L),
conflicts between sources, and verification status.
"""
from dataclasses import asdict, dataclass, field
import logging
import re
from typing import Any, Dict, List, Optional

from services.financial_analysis.group_pl_reader import GroupPLData
from services.financial_analysis.mobitel_writeup_reader import MobitelWriteup

logger = logging.getLogger(__name__)


@dataclass
class FieldStatus:
    field_name: str
    section: str
    source: str
    status: str  # "completed", "missing_input", "source_conflict", "requires_verification"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConflictRecord:
    field_name: str
    source_a: str
    value_a: Any
    source_b: str
    value_b: Any
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationDashboard:
    total_fields: int
    populated_from_tb: int
    populated_from_mobitel_docx: int
    populated_from_group_pl: int
    still_missing: int
    conflicts: List[ConflictRecord]
    requires_verification: List[str]
    field_statuses: List[FieldStatus]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_fields": self.total_fields,
            "populated_from_tb": self.populated_from_tb,
            "populated_from_mobitel_docx": self.populated_from_mobitel_docx,
            "populated_from_group_pl": self.populated_from_group_pl,
            "still_missing": self.still_missing,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "requires_verification": self.requires_verification,
            "field_statuses": [f.to_dict() for f in self.field_statuses],
        }


def build_validation_dashboard(
    analysis: Any,
    mobitel_writeup: Optional[MobitelWriteup] = None,
    group_pl_data: Optional[GroupPLData] = None,
) -> ValidationDashboard:
    """
    Builds the validation dashboard summarizing data coverage, source breakdown,
    and potential conflicts across all report sections.
    """
    field_statuses: List[FieldStatus] = []
    conflicts: List[ConflictRecord] = []
    requires_verification: List[str] = []

    has_mob_writeup = bool(mobitel_writeup)
    has_group_pl = bool(group_pl_data)
    has_budget = bool(getattr(analysis, "budget_available", False)) if analysis else False

    # 1. Executive Summary
    field_statuses.append(
        FieldStatus("SLT PLC Executive Commentary", "Executive Summary", "Trial Balance", "completed")
    )
    mob_exec_status = "completed" if (has_mob_writeup and mobitel_writeup.exec_summary) else "missing_input"
    field_statuses.append(
        FieldStatus("Mobitel Executive Commentary", "Executive Summary", "Mobitel Write-up", mob_exec_status)
    )
    field_statuses.append(
        FieldStatus("Group Executive Commentary", "Executive Summary", "Manual / Consolidation", "requires_verification")
    )
    requires_verification.append("Executive Summary: Group consolidated commentary requires review/manual input.")

    # 2. Section A (Current Quarter vs Same Quarter Last Year)
    grp_a_status = "completed" if (has_group_pl and group_pl_data.entities.get("Group")) else "missing_input"
    field_statuses.append(
        FieldStatus("Group Table - Group Figures (cols 1-4)", "Section A (YoY)", "Group P&L", grp_a_status)
    )
    field_statuses.append(
        FieldStatus("Group Table - SLT PLC Figures (cols 6-9)", "Section A (YoY)", "Trial Balance", "completed")
    )
    mob_a_table_status = "completed" if (has_group_pl and group_pl_data.entities.get("Mobitel")) else "missing_input"
    field_statuses.append(
        FieldStatus("Group Table - Mobitel Figures (cols 10-13)", "Section A (YoY)", "Group P&L", mob_a_table_status)
    )
    field_statuses.append(
        FieldStatus("SLT PLC Financial Table & Commentary", "Section A (YoY)", "Trial Balance", "completed")
    )
    mob_a_narrative_status = "completed" if (has_mob_writeup and mobitel_writeup.section_a_yoy) else "missing_input"
    field_statuses.append(
        FieldStatus("Mobitel Narrative Commentary", "Section A (YoY)", "Mobitel Write-up", mob_a_narrative_status)
    )

    # 3. Section B (Current Quarter vs Preceding Quarter)
    grp_b_status = "completed" if (has_group_pl and group_pl_data.entities.get("Group")) else "missing_input"
    field_statuses.append(
        FieldStatus("Group Table - Group Figures (cols 1-4)", "Section B (QoQ)", "Group P&L", grp_b_status)
    )
    field_statuses.append(
        FieldStatus("Group Table - SLT PLC Figures (cols 6-9)", "Section B (QoQ)", "Trial Balance", "completed")
    )
    mob_b_table_status = "completed" if (has_group_pl and group_pl_data.entities.get("Mobitel")) else "missing_input"
    field_statuses.append(
        FieldStatus("Group Table - Mobitel Figures (cols 10-13)", "Section B (QoQ)", "Group P&L", mob_b_table_status)
    )
    field_statuses.append(
        FieldStatus("SLT PLC Financial Table & Commentary", "Section B (QoQ)", "Trial Balance", "completed")
    )
    mob_b_narrative_status = "completed" if (has_mob_writeup and mobitel_writeup.section_b_qoq) else "missing_input"
    field_statuses.append(
        FieldStatus("Mobitel Narrative Commentary", "Section B (QoQ)", "Mobitel Write-up", mob_b_narrative_status)
    )

    # 4. Section C (Current Year YTD vs Preceding Year YTD)
    grp_c_status = "completed" if (has_group_pl and group_pl_data.entities.get("Group")) else "missing_input"
    field_statuses.append(
        FieldStatus("Group Table - Group Figures (cols 1-4)", "Section C (YTD)", "Group P&L", grp_c_status)
    )
    field_statuses.append(
        FieldStatus("Group Table - SLT PLC Figures (cols 6-9)", "Section C (YTD)", "Trial Balance", "completed")
    )
    mob_c_table_status = "completed" if (has_group_pl and group_pl_data.entities.get("Mobitel")) else "missing_input"
    field_statuses.append(
        FieldStatus("Group Table - Mobitel Figures (cols 10-13)", "Section C (YTD)", "Group P&L", mob_c_table_status)
    )
    field_statuses.append(
        FieldStatus("SLT PLC Financial Table & Commentary", "Section C (YTD)", "Trial Balance", "completed")
    )
    mob_c_narrative_status = "completed" if (has_mob_writeup and mobitel_writeup.section_c_ytd) else "missing_input"
    field_statuses.append(
        FieldStatus("Mobitel Narrative Commentary", "Section C (YTD)", "Mobitel Write-up", mob_c_narrative_status)
    )
    field_statuses.append(
        FieldStatus("Liquidity & Cash Flow Table", "Section C (YTD)", "Manual / Treasury", "requires_verification")
    )
    field_statuses.append(
        FieldStatus("Borrowings & Net Debt Table", "Section C (YTD)", "Manual / Treasury", "requires_verification")
    )
    field_statuses.append(
        FieldStatus("Interest Cost Table", "Section C (YTD)", "Manual / Treasury", "requires_verification")
    )
    requires_verification.append("Section C: Treasury tables (Cashflow, Borrowings, Interest) require manual input.")

    # 5. Section D (Actuals vs Budget)
    field_statuses.append(
        FieldStatus("SLT PLC Actuals Table", "Section D (Budget)", "Trial Balance", "completed")
    )
    budget_d_status = "completed" if has_budget else "missing_input"
    field_statuses.append(
        FieldStatus("SLT PLC Budget Figures", "Section D (Budget)", "Budget Store", budget_d_status)
    )
    mob_d_narrative_status = "completed" if (has_mob_writeup and mobitel_writeup.section_d_budget) else "missing_input"
    field_statuses.append(
        FieldStatus("Mobitel Narrative Commentary", "Section D (Budget)", "Mobitel Write-up", mob_d_narrative_status)
    )

    # 6. Financial Statistics & Key Ratios
    field_statuses.append(
        FieldStatus("P&L Summary Lines", "Financial Summary", "Trial Balance", "completed")
    )
    field_statuses.append(
        FieldStatus("Balance Sheet & Key Ratios", "Key Ratios", "Manual Input", "requires_verification")
    )
    requires_verification.append("Financial Statistics: Key Ratios table requires verification of balance sheet items.")

    # 7. Conflict Detection:
    # Compare Group P&L 'Telecom' figures with TB calculated actuals
    if has_group_pl and analysis and hasattr(analysis, "comparisons"):
        ytd_comp = analysis.comparisons.get("ytd_vs_last_year")
        tel_pl = group_pl_data.entities.get("Telecom")
        if ytd_comp and tel_pl:
            tb_cur_rev = ytd_comp.current.lines.get("revenue")
            pl_cur_rev = tel_pl.revenue_current
            if tb_cur_rev and pl_cur_rev:
                diff_pct = abs(tb_cur_rev - pl_cur_rev) / abs(tb_cur_rev)
                if diff_pct > 0.05:
                    conflicts.append(
                        ConflictRecord(
                            field_name="SLT PLC YTD Revenue",
                            source_a="Trial Balance",
                            value_a=round(tb_cur_rev, 2),
                            source_b="Group P&L (Telecom)",
                            value_b=round(pl_cur_rev, 2),
                            note=f"Variance of {diff_pct*100:.1f}% exceeds 5% conflict threshold.",
                        )
                    )

            tb_cur_opx = -ytd_comp.current.lines.get("operating_costs", 0)
            pl_cur_opx = tel_pl.opex_current
            if tb_cur_opx and pl_cur_opx:
                diff_pct = abs(tb_cur_opx - pl_cur_opx) / abs(tb_cur_opx)
                if diff_pct > 0.05:
                    conflicts.append(
                        ConflictRecord(
                            field_name="SLT PLC YTD Opex",
                            source_a="Trial Balance",
                            value_a=round(tb_cur_opx, 2),
                            source_b="Group P&L (Telecom)",
                            value_b=round(pl_cur_opx, 2),
                            note=f"Variance of {diff_pct*100:.1f}% exceeds 5% conflict threshold.",
                        )
                    )

    # Cross-check Mobitel Writeup vs Group P&L Mobitel standalone
    if has_mob_writeup and has_group_pl:
        mob_pl = group_pl_data.entities.get("Mobitel")
        if mob_pl and mob_pl.revenue_current and mobitel_writeup.section_c_ytd:
            # Check if writeup mentions revenue
            match = re.search(r"revenue\s+of\s+rs\.?\s*([0-9,]+)\s*mn", mobitel_writeup.section_c_ytd, re.IGNORECASE)
            if match:
                try:
                    writeup_rev = float(match.group(1).replace(",", ""))
                    pl_rev = mob_pl.revenue_current
                    diff_pct = abs(writeup_rev - pl_rev) / abs(pl_rev)
                    if diff_pct > 0.05:
                        conflicts.append(
                            ConflictRecord(
                                field_name="Mobitel YTD Revenue",
                                source_a="Mobitel Write-up",
                                value_a=writeup_rev,
                                source_b="Group P&L (Mobitel)",
                                value_b=pl_rev,
                                note=f"Difference of {diff_pct*100:.1f}% between write-up and standalone P&L column.",
                            )
                        )
                except ValueError:
                    pass

    # If any conflicts found, update corresponding field status
    conflict_fields = {c.field_name for c in conflicts}
    for fs in field_statuses:
        for cf in conflict_fields:
            if cf.lower() in fs.field_name.lower():
                fs.status = "source_conflict"

    # Compute breakdown counts
    pop_tb = sum(1 for f in field_statuses if f.source == "Trial Balance" and f.status == "completed")
    pop_mob = sum(1 for f in field_statuses if f.source == "Mobitel Write-up" and f.status == "completed")
    pop_grp = sum(1 for f in field_statuses if f.source == "Group P&L" and f.status == "completed")
    missing = sum(1 for f in field_statuses if f.status == "missing_input")

    return ValidationDashboard(
        total_fields=len(field_statuses),
        populated_from_tb=pop_tb,
        populated_from_mobitel_docx=pop_mob,
        populated_from_group_pl=pop_grp,
        still_missing=missing,
        conflicts=conflicts,
        requires_verification=requires_verification,
        field_statuses=field_statuses,
    )
