"""
CIP Reconciliation Engine
Performs financial reconciliation for Construction in Progress (CIP) & RWIP:
- Project-level consolidation (Opening + Additions + Interface = Closing Balance)
- GL Journal vs Subledger / Interface reconciliation
- Exception and discrepancy identification
"""
from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple

from .cip_reader import CIPInputError, normalize_source

logger = logging.getLogger(__name__)

TOLERANCE = 1.0


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
    opening: Dict[str, Optional[float]]
    opening_total: Optional[float]
    additions: Dict[str, float]
    additions_total: float
    interface: Dict[str, float]
    interface_total: float
    closing: Dict[str, Optional[float]]
    closing_total: Optional[float]
    project_manager: str = ""
    project_code: str = ""
    status: str = "Reconciled"
    discrepancy_note: str = ""


@dataclass
class AccountGLReconciliation:
    account: str
    subledger_additions: float
    gl_additions_net: float
    additions_variance: float
    interfaced_cip_total: float
    gl_assets_net: float
    interface_variance: float
    trial_balance_closing: Optional[float]
    trial_balance_variance: Optional[float]
    trial_balance_opening: Optional[float]
    opening_trial_balance_variance: Optional[float]
    status: str
    notes: List[str] = field(default_factory=list)


@dataclass
class CIPReconciliationResult:
    period: str
    projects: List[Dict[str, Any]]
    summary: Dict[str, Any]
    account_reconciliations: List[Dict[str, Any]]
    trial_balance_reconciliations: List[Dict[str, Any]]
    journal_adjustments: List[Dict[str, Any]]
    discrepancies: List[Dict[str, Any]]
    unallocated_additions: Dict[str, float]
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
        gl_summary: Dict[str, Dict[str, Any]],
        opening_balances: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
        period: str = "",
        trial_balance: Optional[Dict[str, Any]] = None,
        journal_rows: Optional[List[Dict[str, Any]]] = None,
    ):
        self.project_master = project_master
        self.subledger_additions = subledger_additions
        self.interfaced_cip = interfaced_cip
        self.gl_summary = gl_summary
        self.opening_balances = opening_balances or {}
        self.period = period
        self.trial_balance = trial_balance or {}
        self.has_trial_balance = trial_balance is not None
        self.journal_rows = journal_rows or []
        self.accounts = self._discover_accounts()

    def _discover_accounts(self) -> List[str]:
        accounts: List[str] = []
        for source in (self.opening_balances, self.subledger_additions, self.interfaced_cip):
            for balances in source.values():
                for account in balances:
                    if account not in accounts:
                        accounts.append(account)
        for account in self.gl_summary:
            if account not in accounts:
                accounts.append(account)
        return accounts

    def _journal_account_totals(self, account: str) -> Dict[str, float]:
        summary = self.gl_summary.get(account, {})
        sources = summary.get("sources")
        if not isinstance(sources, dict):
            return {
                "additions": float(summary.get("dr", 0.0)),
                "assets": -float(summary.get("cr", 0.0)),
            }

        additions = 0.0
        assets = 0.0
        for source_key, values in sources.items():
            net = float(values.get("net", 0.0))
            normalized = normalize_source(values.get("source") or source_key)
            if normalized == "assets":
                assets += net
            elif normalized != "spreadsheethq":
                additions += net
        return {"additions": additions, "assets": assets}

    def _oriented_interfaces(
        self,
        asset_nets: Dict[str, float],
    ) -> Tuple[Dict[str, Dict[str, float]], Dict[str, bool], Dict[str, float], List[Dict[str, Any]]]:
        interfaces = {
            project: {account: float(value) for account, value in balances.items()}
            for project, balances in self.interfaced_cip.items()
        }
        flipped: Dict[str, bool] = {}
        source_totals: Dict[str, float] = {}
        unmatched_movements: List[Dict[str, Any]] = []
        for account in self.accounts:
            interface_total = sum(values.get(account, 0.0) for values in interfaces.values())
            asset_total = asset_nets.get(account, 0.0)
            should_flip = interface_total * asset_total < 0
            flipped[account] = should_flip
            if should_flip:
                for values in interfaces.values():
                    values[account] = -values.get(account, 0.0)
                interface_total = -interface_total

            source_totals[account] = interface_total
            difference = asset_total - interface_total
            if abs(difference) <= TOLERANCE:
                continue

            candidates = [
                (project, values[account])
                for project, values in interfaces.items()
                if account in values and abs(values[account] + difference) <= TOLERANCE
            ]
            if len(candidates) != 1:
                continue

            project, amount = candidates[0]
            interfaces[project].pop(account)
            unmatched_movements.append({
                "type": "Unmatched Interface Movement",
                "project_no": project,
                "account": account,
                "amount": amount,
                "detail": (
                    f"Interface movement {amount:,.2f} for project {project}, account {account}, "
                    "is the unique source row matching the difference from the journal Assets net. "
                    "It was excluded from the calculated closing balance and needs review."
                ),
            })
        return interfaces, flipped, source_totals, unmatched_movements

    def _journal_adjustments(
        self,
        interfaces: Dict[str, Dict[str, float]],
    ) -> List[Dict[str, Any]]:
        groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        for row in self.journal_rows:
            project = row.get("project")
            source_key = normalize_source(row.get("source"))
            if not project or source_key == "spreadsheethq":
                continue
            kind = "interface" if source_key == "assets" else "additions"
            groups.setdefault((kind, row["account"], project), []).append(row)

        targets = []
        for project, values in self.subledger_additions.items():
            for account in self.accounts:
                target = float(values.get(account, 0.0))
                if abs(target) > TOLERANCE:
                    targets.append(("additions", account, project, target))
        for project, values in interfaces.items():
            for account in self.accounts:
                target = float(values.get(account, 0.0))
                if abs(target) > TOLERANCE:
                    targets.append(("interface", account, project, target))

        adjustments: List[Dict[str, Any]] = []
        for kind, account, project, target in targets:
            lines = groups.get((kind, account, project), [])
            current = sum(float(line.get("net", 0.0)) for line in lines)
            variance = target - current
            if abs(variance) <= TOLERANCE:
                continue

            entry: Dict[str, Any] = {
                "kind": kind,
                "account": account,
                "project_no": project,
                "target_net": target,
                "original_net": current,
                "variance": variance,
                "status": "needs_review",
                "sheet": None,
                "row_number": None,
                "original_dr": None,
                "original_cr": None,
                "adjusted_dr": None,
                "adjusted_cr": None,
                "detail": "",
            }
            if len(lines) == 1 and abs(target) > TOLERANCE:
                line = lines[0]
                dr = float(line.get("dr", 0.0))
                cr = float(line.get("cr", 0.0))
                adjusted_dr = dr + max(variance, 0.0)
                adjusted_cr = cr + max(-variance, 0.0)
                entry.update({
                    "status": "applied_to_copy",
                    "sheet": line.get("sheet"),
                    "row_number": line.get("row_number"),
                    "original_dr": dr,
                    "original_cr": cr,
                    "adjusted_dr": adjusted_dr,
                    "adjusted_cr": adjusted_cr,
                    "detail": "Unique journal line adjusted in the generated review copy; uploaded source remains unchanged.",
                })
            elif not lines:
                entry["detail"] = "No uniquely mapped journal line exists for this project/account amount."
            elif len(lines) > 1:
                entry["detail"] = (
                    f"{len(lines)} journal lines could explain this project/account difference; "
                    "no line was changed."
                )
            else:
                entry["detail"] = "A zero target cannot safely identify which journal line should be changed."
            adjustments.append(entry)
        return adjustments

    def run(self) -> CIPReconciliationResult:
        """Runs the complete reconciliation calculations."""
        if not self.accounts:
            raise CIPInputError("No CIP account codes were found in the uploaded source files.")

        journal_totals = {account: self._journal_account_totals(account) for account in self.accounts}
        interfaces, flipped_accounts, source_interface_totals, unmatched_interface_movements = self._oriented_interfaces(
            {account: values["assets"] for account, values in journal_totals.items()}
        )
        journal_project_additions: Dict[str, Dict[str, float]] = {}
        unmapped_journal_groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
        subledger_accounts = {
            account
            for balances in self.subledger_additions.values()
            for account in balances
        }
        for row in self.journal_rows:
            source_key = normalize_source(row.get("source"))
            if source_key in {"assets", "spreadsheethq"}:
                continue

            project = row.get("project")
            if project and str(project).strip() not in {"0", "0.0"}:
                balances = journal_project_additions.setdefault(project, {})
                balances[row["account"]] = balances.get(row["account"], 0.0) + float(row.get("net", 0.0))
                continue

            key = (row["account"], source_key or "unclassified")
            group = unmapped_journal_groups.setdefault(
                key,
                {"amount": 0.0, "rows": []},
            )
            group["amount"] += float(row.get("net", 0.0))
            group["rows"].append(row.get("row_number"))

        cip_input_projects = set(self.opening_balances) | set(self.subledger_additions) | set(interfaces)
        all_projects = cip_input_projects | set(journal_project_additions)
        established = list(dict.fromkeys(project for project in self.opening_balances if project in all_projects))
        new_projects = sorted(
            all_projects - set(established),
            key=lambda project: (extract_year_from_project(project) or 9999, project),
        )
        sorted_projects = established + new_projects
        project_rows: List[ProjectReconciliationRow] = []
        discrepancies: List[Dict[str, Any]] = []
        discrepancies.extend(unmatched_interface_movements)
        journal_only_groups: Dict[Tuple[str, str, str], float] = {}
        for row in self.journal_rows:
            project = row.get("project")
            source_key = normalize_source(row.get("source"))
            if project and project not in cip_input_projects and source_key != "spreadsheethq":
                key = (project, row["account"], source_key or "unclassified")
                journal_only_groups[key] = journal_only_groups.get(key, 0.0) + float(row.get("net", 0.0))
        for (project, account, source), amount in journal_only_groups.items():
            discrepancies.append({
                "type": "Journal Project Missing from CIP Inputs",
                "project_no": project,
                "account": account,
                "amount": amount,
                "detail": (
                    f"Journal project {project} has no opening, subledger, or interface record "
                    f"for account {account} (source: {source}); it is excluded from the project rollforward."
                ),
            })

        for (account, source), group in unmapped_journal_groups.items():
            included_as_unallocated = (
                account not in subledger_accounts and abs(group["amount"]) > TOLERANCE
            )
            row_numbers = [number for number in group["rows"] if number is not None]
            row_detail = (
                f" Journal rows: {', '.join(str(number) for number in row_numbers[:10])}."
                if row_numbers else ""
            )
            discrepancies.append({
                "type": "Unmapped Journal Transaction",
                "project_no": "",
                "account": account,
                "amount": group["amount"],
                "transaction_count": len(group["rows"]),
                "detail": (
                    f"{len(group['rows'])} {source} journal transaction(s) for account {account} "
                    f"have no mapped project number. "
                    f"{'Included as unallocated activity in the report.' if included_as_unallocated else 'Not assigned to a project because project-level subledger data exists.'}"
                    f"{row_detail}"
                ),
            })

        opening_accounts = {
            account
            for balances in self.opening_balances.values()
            for account in balances
        }
        for account in self.accounts:
            if account not in opening_accounts:
                discrepancies.append({
                    "type": "Missing Opening Balance Account",
                    "project_no": "All",
                    "account": account,
                    "amount": 0.0,
                    "detail": (
                        f"Account {account} is present in current-period inputs but absent from "
                        "the prior-period opening report; no opening amount was supplied."
                    ),
                })

        summary_opening = {a: 0.0 for a in self.accounts}
        summary_additions = {a: 0.0 for a in self.accounts}
        summary_subledger_additions = {a: 0.0 for a in self.accounts}
        summary_interface = {a: 0.0 for a in self.accounts}
        summary_closing = {a: 0.0 for a in self.accounts}

        unallocated_additions = {
            account: sum(
                group["amount"]
                for (group_account, _), group in unmapped_journal_groups.items()
                if group_account == account
            )
            for account in self.accounts
            if account not in subledger_accounts
        }
        unallocated_additions = {
            account: amount
            for account, amount in unallocated_additions.items()
            if abs(amount) > TOLERANCE
        }

        for p_no in sorted_projects:
            pm_info = self.project_master.get(p_no, {})
            p_name = pm_info.get("project_name", "")
            pm_name = pm_info.get("project_manager", "")
            p_code = pm_info.get("project_code", "")
            encoded_year = extract_year_from_project(p_no)
            try:
                mapped_year = int(pm_info.get("project_year"))
            except (TypeError, ValueError):
                mapped_year = None
            year = mapped_year or encoded_year

            # Check if missing in master
            if p_no not in self.project_master:
                discrepancies.append({
                    "type": "Missing Project Master",
                    "project_no": p_no,
                    "account": "All",
                    "amount": 0.0,
                    "detail": f"Project {p_no} appears in the reconciliation inputs but is absent from the project master.",
                })
            if mapped_year and encoded_year and mapped_year != encoded_year:
                discrepancies.append({
                    "type": "Project Year Mapping Variance",
                    "project_no": p_no,
                    "account": "All",
                    "amount": 0.0,
                    "detail": (
                        f"Project {p_no} encodes year {encoded_year} in its number, but the project master "
                        f"start date maps it to {mapped_year}; the report uses the project-master year."
                    ),
                })
            has_opening = p_no in self.opening_balances
            if not has_opening:
                discrepancies.append({
                    "type": "Missing Opening Balance",
                    "project_no": p_no,
                    "account": "All",
                    "amount": 0.0,
                    "detail": (
                        f"Project {p_no} has no row in the prior-period opening report; "
                        "its closing balance cannot be calculated and it is excluded from the report."
                    ),
                })

            # Opening
            p_open = self.opening_balances.get(p_no, {})
            # Additions
            source_additions = self.subledger_additions.get(p_no, {})
            p_add = dict(source_additions)
            for account, amount in journal_project_additions.get(p_no, {}).items():
                if account not in p_add and abs(amount) > TOLERANCE:
                    p_add[account] = amount
                    discrepancies.append({
                        "type": "Journal Addition Missing from Subledger",
                        "project_no": p_no,
                        "account": account,
                        "amount": amount,
                        "detail": (
                            f"Project-mapped journal additions of {amount:,.2f} for project {p_no}, "
                            f"account {account}, were included because no project/account row exists "
                            "in the subledger."
                        ),
                    })
            # Interface
            p_int = interfaces.get(p_no, {})

            # Compute closing per account: Opening + Additions + Interface
            p_close: Dict[str, Optional[float]] = {}
            for a in self.accounts:
                a_val = p_add.get(a, 0.0)
                i_val = p_int.get(a, 0.0)
                summary_subledger_additions[a] += float(source_additions.get(a, 0.0) or 0.0)
                if has_opening:
                    summary_additions[a] += a_val
                    summary_interface[a] += i_val

                if not has_opening or a not in opening_accounts:
                    p_close[a] = None
                    continue

                raw_open = p_open.get(a, 0.0)
                o_val = 0.0 if raw_open is None else float(raw_open)
                c_val = o_val + a_val + i_val
                p_close[a] = c_val

                summary_opening[a] += o_val
                summary_closing[a] += c_val

            open_tot = (
                sum(value or 0.0 for value in p_open.values())
                if has_opening and all(a in opening_accounts for a in self.accounts)
                else None
            )
            add_tot = sum(p_add.values())
            int_tot = sum(p_int.values())
            close_tot = (
                sum(value for value in p_close.values() if value is not None)
                if has_opening and all(value is not None for value in p_close.values())
                else None
            )

            # Detect negative balance
            row_status = "Reconciled"
            disc_note = ""
            if close_tot is None:
                row_status = "Missing Opening Balance"
            elif close_tot < -TOLERANCE:
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

        for account, amount in unallocated_additions.items():
            if account in opening_accounts:
                summary_additions[account] += amount
                summary_closing[account] += amount

        # Compare ledger totals by source with the source reports and Trial Balance.
        account_recons: List[AccountGLReconciliation] = []
        trial_balance_reconciliations: List[Dict[str, Any]] = []
        tb_balances = self.trial_balance.get("balances", {})
        tb_opening_balances = self.trial_balance.get("opening_balances", {})
        for a in self.accounts:
            sub_add = summary_subledger_additions.get(a, 0.0)
            gl_add = journal_totals[a]["additions"]
            gl_assets = journal_totals[a]["assets"]
            int_cip = summary_interface.get(a, 0.0)
            add_var = sub_add - gl_add
            int_var = source_interface_totals.get(a, 0.0) - gl_assets
            tb_closing = float(tb_balances[a]) if a in tb_balances else None
            tb_variance = summary_closing[a] - tb_closing if tb_closing is not None else None
            tb_opening = float(tb_opening_balances[a]) if a in tb_opening_balances else None
            opening_tb_variance = summary_opening[a] - tb_opening if tb_opening is not None else None

            notes = []
            acct_status = "Reconciled"
            if abs(add_var) > TOLERANCE:
                acct_status = "Variance Detected"
                notes.append(f"Additions variance of {add_var:,.2f} between Subledger and journal source net.")
                discrepancies.append({
                    "type": "GL vs Subledger Variance",
                    "project_no": "All",
                    "account": a,
                    "amount": add_var,
                    "detail": (
                        f"Account {a}: Subledger additions ({sub_add:,.2f}) do not equal "
                        f"the journal net excluding Assets and Spreadsheet - HQ ({gl_add:,.2f}). "
                        f"Variance: {add_var:,.2f}."
                    ),
                })

            if abs(int_var) > TOLERANCE:
                if acct_status == "Reconciled":
                    acct_status = "Variance Detected"
                notes.append(f"Interface variance of {int_var:,.2f} between interface report and Assets source net.")
                discrepancies.append({
                    "type": "GL vs Interface Variance",
                    "project_no": "All",
                    "account": a,
                    "amount": int_var,
                    "detail": (
                        f"Account {a}: source interface amount ({source_interface_totals.get(a, 0.0):,.2f}) "
                        f"does not equal the journal net for Assets ({gl_assets:,.2f}). "
                        f"Variance: {int_var:,.2f}."
                    )
                })

            if tb_closing is None and self.has_trial_balance:
                acct_status = "Variance Detected"
                notes.append("Trial Balance account is missing; no closing comparison was possible.")
                discrepancies.append({
                    "type": "Missing Trial Balance Account",
                    "project_no": "All",
                    "account": a,
                    "amount": 0.0,
                    "detail": (
                        f"Account {a} is present in the reconciliation inputs but was not found "
                        "in column E of the uploaded Trial Balance."
                    ),
                })

            if tb_closing is not None and abs(tb_variance or 0.0) > TOLERANCE:
                acct_status = "Variance Detected"
                notes.append(f"Closing balance differs from Trial Balance by {tb_variance:,.2f}.")
                discrepancies.append({
                    "type": "Trial Balance Closing Variance",
                    "project_no": "All",
                    "account": a,
                    "amount": tb_variance,
                    "detail": (
                        f"Calculated closing balance ({summary_closing[a]:,.2f}) does not equal "
                        f"Trial Balance closing ({tb_closing:,.2f})."
                    ),
                })

            if tb_opening is not None and abs(opening_tb_variance or 0.0) > TOLERANCE:
                acct_status = "Variance Detected"
                notes.append(f"Opening balance differs from prior-period Trial Balance by {opening_tb_variance:,.2f}.")
                discrepancies.append({
                    "type": "Prior Period Opening Variance",
                    "project_no": "All",
                    "account": a,
                    "amount": opening_tb_variance,
                    "detail": (
                        f"Opening balance ({summary_opening[a]:,.2f}) does not equal "
                        f"the prior-period Trial Balance ({tb_opening:,.2f})."
                    ),
                })

            account_recons.append(
                AccountGLReconciliation(
                    account=a,
                    subledger_additions=sub_add,
                    gl_additions_net=gl_add,
                    additions_variance=add_var,
                    interfaced_cip_total=int_cip,
                    gl_assets_net=gl_assets,
                    interface_variance=int_var,
                    trial_balance_closing=tb_closing,
                    trial_balance_variance=tb_variance,
                    trial_balance_opening=tb_opening,
                    opening_trial_balance_variance=opening_tb_variance,
                    status=acct_status,
                    notes=notes,
                )
            )
            if self.has_trial_balance:
                trial_balance_reconciliations.append({
                    "account": a,
                    "calculated_closing": summary_closing[a],
                    "trial_balance_closing": tb_closing,
                    "variance": tb_variance,
                    "status": (
                        "Missing Trial Balance Account"
                        if tb_closing is None
                        else "Reconciled" if abs(tb_variance or 0.0) <= TOLERANCE else "Variance Detected"
                    ),
                })

        for row in self.journal_rows:
            if row.get("project_mapping_status") == "ambiguous_code":
                discrepancies.append({
                    "type": "Ambiguous Project Code",
                    "project_no": row.get("project") or "",
                    "account": row.get("account", ""),
                    "amount": row.get("net", 0.0),
                    "detail": f"Project code '{row.get('future')}' maps to more than one project number.",
                })
            elif row.get("project_mapping_status") == "unmatched_code":
                discrepancies.append({
                    "type": "Unmatched Project Code",
                    "project_no": row.get("project") or "",
                    "account": row.get("account", ""),
                    "amount": row.get("net", 0.0),
                    "detail": f"Project code '{row.get('future')}' was not found in the project master.",
                })
            if row.get("source_key") == "unclassified":
                discrepancies.append({
                    "type": "Unclassified Journal Source",
                    "project_no": row.get("project") or "",
                    "account": row.get("account", ""),
                    "amount": row.get("net", 0.0),
                    "detail": "Journal row has an amount but no source; it is included in additions pending review.",
                })

        journal_adjustments = self._journal_adjustments(interfaces)
        for adjustment in journal_adjustments:
            if adjustment["status"] != "applied_to_copy":
                discrepancies.append({
                    "type": "Journal Amount Review",
                    "project_no": adjustment["project_no"],
                    "account": adjustment["account"],
                    "amount": adjustment["variance"],
                    "detail": adjustment["detail"],
                })

        for account, was_flipped in flipped_accounts.items():
            if was_flipped:
                logger.info(
                    "Normalized interface sign for account %s to match the journal Assets net direction",
                    account,
                )

        summary_dict = {
            "opening": summary_opening,
            "opening_total": sum(summary_opening.values()),
            "additions": summary_additions,
            "additions_total": sum(summary_additions.values()),
            "subledger_additions": summary_subledger_additions,
            "subledger_additions_total": sum(summary_subledger_additions.values()),
            "interface": summary_interface,
            "interface_total": sum(summary_interface.values()),
            "source_interface": source_interface_totals,
            "closing": summary_closing,
            "closing_total": sum(summary_closing.values()),
            "journal_additions_net": {
                account: journal_totals[account]["additions"] for account in self.accounts
            },
            "journal_assets_net": {
                account: journal_totals[account]["assets"] for account in self.accounts
            },
            "trial_balance": tb_balances,
        }

        reconciled_cnt = sum(1 for r in project_rows if r.status == "Reconciled")
        unreconciled_cnt = len(project_rows) - reconciled_cnt

        return CIPReconciliationResult(
            period=self.period,
            projects=[asdict(r) for r in project_rows],
            summary=summary_dict,
            account_reconciliations=[asdict(ar) for ar in account_recons],
            trial_balance_reconciliations=trial_balance_reconciliations,
            journal_adjustments=journal_adjustments,
            discrepancies=discrepancies,
            unallocated_additions=unallocated_additions,
            total_projects_count=len(project_rows),
            reconciled_projects_count=reconciled_cnt,
            unreconciled_projects_count=unreconciled_cnt,
            total_opening_balance=summary_dict["opening_total"],
            total_additions=summary_dict["additions_total"],
            total_interface=summary_dict["interface_total"],
            total_closing_balance=summary_dict["closing_total"],
        )

