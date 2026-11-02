"""
CIP Reconciliation Engine
Performs financial reconciliation for Construction in Progress (CIP) & RWIP:
- Project-level consolidation (Opening + Additions + Interface = Closing Balance)
- GL Journal vs Subledger / Interface reconciliation
- Exception and discrepancy identification
"""
from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Dict, List, Optional, Set

from .cip_reader import ACCOUNTS, clean_project_num

logger = logging.getLogger(__name__)


def extract_year_from_project(project_no: str) -> Optional[int]:
    """Extracts 4-digit year from the first 2 digits of the project number."""
    if not project_no or len(project_no) < 2:
        return None
    try:
        prefix = int(project_no[:2])
        return 2000 + prefix if prefix < 50 else 1900 + prefix
    except ValueError:
        return None


@dataclass
class ProjectReconciliationRow:
    project_no: str
    project_name: str
    year: Optional[int]
    opening: Dict[str, float]
    opening_total: float
    additions: Dict[str, float]
    additions_total: float
    interface: Dict[str, float]
    interface_total: float
    closing: Dict[str, float]
    closing_total: float
    project_manager: str = ""
    project_code: str = ""
    status: str = "Reconciled"
    discrepancy_note: str = ""


@dataclass
class AccountGLReconciliation:
    account: str
    subledger_additions: float
    gl_additions_dr: float
    additions_variance: float
    interfaced_cip_total: float
    gl_interface_cr: float
    interface_variance: float
    status: str
    notes: List[str] = field(default_factory=list)


@dataclass
class CIPReconciliationResult:
    period: str
    projects: List[Dict[str, Any]]
    summary: Dict[str, Any]
    account_reconciliations: List[Dict[str, Any]]
    discrepancies: List[Dict[str, Any]]
    total_projects_count: int
    reconciled_projects_count: int
    unreconciled_projects_count: int
    total_opening_balance: float
    total_additions: float
    total_interface: float
    total_closing_balance: float


class CIPReconciliationEngine:
    """Executes the CIP reconciliation logic."""

    def __init__(
        self,
        project_master: Dict[str, Dict[str, Any]],
        subledger_additions: Dict[str, Dict[str, float]],
        interfaced_cip: Dict[str, Dict[str, float]],
        gl_summary: Dict[str, Dict[str, float]],
        opening_balances: Optional[Dict[str, Dict[str, float]]] = None,
        period: str = "Jul-26",
    ):
        self.project_master = project_master
        self.subledger_additions = subledger_additions
        self.interfaced_cip = interfaced_cip
        self.gl_summary = gl_summary
        self.opening_balances = opening_balances or {}
        self.period = period

    def run(self) -> CIPReconciliationResult:
        """Runs the complete reconciliation calculations."""
        # 1. Determine all unique project numbers across all sources
        if self.opening_balances:
            # Preserve exact reference template ordering for established projects
            template_projects = [p for p in self.opening_balances.keys() if p.isdigit()]
            # Include any genuinely new projects with non-zero additions or interface
            new_projects = []
            for p in sorted(set(self.subledger_additions.keys()) | set(self.interfaced_cip.keys())):
                if p not in self.opening_balances and p.isdigit():
                    has_add = any(abs(v) > 0.001 for v in self.subledger_additions.get(p, {}).values())
                    has_int = any(abs(v) > 0.001 for v in self.interfaced_cip.get(p, {}).values())
                    if has_add or has_int:
                        new_projects.append(p)
            sorted_projects = template_projects + new_projects
        else:
            all_projects = set(self.subledger_additions.keys()) | set(self.interfaced_cip.keys())
            sorted_projects = sorted(
                [p for p in all_projects if p.isdigit()],
                key=lambda p: (extract_year_from_project(p) or 9999, p),
            )

        project_rows: List[ProjectReconciliationRow] = []
        discrepancies: List[Dict[str, Any]] = []

        summary_opening = {a: 0.0 for a in ACCOUNTS}
        summary_additions = {a: 0.0 for a in ACCOUNTS}
        summary_interface = {a: 0.0 for a in ACCOUNTS}
        summary_closing = {a: 0.0 for a in ACCOUNTS}

        for p_no in sorted_projects:
            pm_info = self.project_master.get(p_no, {})
            p_name = pm_info.get("project_name", "")
            pm_name = pm_info.get("project_manager", "")
            p_code = pm_info.get("project_code", "")
            year = extract_year_from_project(p_no)

            # Check if missing in master
            if not p_name:
                discrepancies.append({
                    "type": "Missing Project Master",
                    "project_no": p_no,
                    "account": "All",
                    "amount": 0.0,
                    "detail": f"Project {p_no} is present in subledger/interfaced data but missing in Project Details Codes.",
                })

            # Opening
            p_open = self.opening_balances.get(p_no, {a: 0.0 for a in ACCOUNTS})
            # Additions
            p_add = self.subledger_additions.get(p_no, {a: 0.0 for a in ACCOUNTS})
            # Interface
            p_int = self.interfaced_cip.get(p_no, {a: 0.0 for a in ACCOUNTS})

            # Compute closing per account: Opening + Additions + Interface
            p_close = {}
            for a in ACCOUNTS:
                o_val = p_open.get(a, 0.0)
                a_val = p_add.get(a, 0.0)
                i_val = p_int.get(a, 0.0)
                c_val = o_val + a_val + i_val
                p_close[a] = c_val

                summary_opening[a] += o_val
                summary_additions[a] += a_val
                summary_interface[a] += i_val
                summary_closing[a] += c_val

            open_tot = sum(p_open.values())
            add_tot = sum(p_add.values())
            int_tot = sum(p_int.values())
            close_tot = sum(p_close.values())

            # Detect negative balance
            row_status = "Reconciled"
            disc_note = ""
            if close_tot < -0.01:
                row_status = "Negative Balance"
                disc_note = f"Negative closing balance: {close_tot:,.2f}"
                discrepancies.append({
                    "type": "Negative Balance",
                    "project_no": p_no,
                    "account": "Total",
                    "amount": close_tot,
                    "detail": f"Project {p_no} ({p_name}) has a negative closing balance of {close_tot:,.2f}.",
                })

            project_rows.append(
                ProjectReconciliationRow(
                    project_no=p_no,
                    project_name=p_name,
                    year=year,
                    opening=p_open,
                    opening_total=open_tot,
                    additions=p_add,
                    additions_total=add_tot,
                    interface=p_int,
                    interface_total=int_tot,
                    closing=p_close,
                    closing_total=close_tot,
                    project_manager=pm_name,
                    project_code=p_code,
                    status=row_status,
                    discrepancy_note=disc_note,
                )
            )

        # 2. Account-level GL vs Subledger / Interface reconciliation
        account_recons: List[AccountGLReconciliation] = []
        for a in ACCOUNTS:
            sub_add = summary_additions.get(a, 0.0)
            gl_info = self.gl_summary.get(a, {"dr": 0.0, "cr": 0.0, "net": 0.0})
            gl_dr = gl_info.get("dr", 0.0)
            gl_cr = gl_info.get("cr", 0.0)
            int_cip = summary_interface.get(a, 0.0)

            add_var = sub_add - gl_dr
            int_var = int_cip - (-gl_cr if gl_cr > 0 else gl_cr)

            notes = []
            acct_status = "Reconciled"
            if abs(add_var) > 1.0:
                acct_status = "Variance Detected"
                notes.append(f"Additions variance of {add_var:,.2f} between Subledger and GL DR.")
                discrepancies.append({
                    "type": "GL vs Subledger Variance",
                    "project_no": "All",
                    "account": a,
                    "amount": add_var,
                    "detail": f"Account {a}: Subledger Additions ({sub_add:,.2f}) != GL DR ({gl_dr:,.2f}). Variance: {add_var:,.2f}",
                })

            if abs(int_var) > 1.0:
                if acct_status == "Reconciled":
                    acct_status = "Variance Detected"
                notes.append(f"Interface variance of {int_var:,.2f} between Interfaced CIP and GL CR.")
                discrepancies.append({
                    "type": "GL vs Interface Variance",
                    "project_no": "All",
                    "account": a,
                    "amount": int_var,
                    "detail": f"Account {a}: Interfaced CIP ({int_cip:,.2f}) != GL CR ({gl_cr:,.2f}). Variance: {int_var:,.2f}",
                })

            account_recons.append(
                AccountGLReconciliation(
                    account=a,
                    subledger_additions=sub_add,
                    gl_additions_dr=gl_dr,
                    additions_variance=add_var,
                    interfaced_cip_total=int_cip,
                    gl_interface_cr=gl_cr,
                    interface_variance=int_var,
                    status=acct_status,
                    notes=notes,
                )
            )

        summary_dict = {
            "opening": summary_opening,
            "opening_total": sum(summary_opening.values()),
            "additions": summary_additions,
            "additions_total": sum(summary_additions.values()),
            "interface": summary_interface,
            "interface_total": sum(summary_interface.values()),
            "closing": summary_closing,
            "closing_total": sum(summary_closing.values()),
        }

        reconciled_cnt = sum(1 for r in project_rows if r.status == "Reconciled")
        unreconciled_cnt = len(project_rows) - reconciled_cnt

        return CIPReconciliationResult(
            period=self.period,
            projects=[asdict(r) for r in project_rows],
            summary=summary_dict,
            account_reconciliations=[asdict(ar) for ar in account_recons],
            discrepancies=discrepancies,
            total_projects_count=len(project_rows),
            reconciled_projects_count=reconciled_cnt,
            unreconciled_projects_count=unreconciled_cnt,
            total_opening_balance=summary_dict["opening_total"],
            total_additions=summary_dict["additions_total"],
            total_interface=summary_dict["interface_total"],
            total_closing_balance=summary_dict["closing_total"],
        )

