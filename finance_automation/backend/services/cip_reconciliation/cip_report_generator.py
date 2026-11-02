"""
CIP Report Generator
Generates the Excel reconciliation report in exact alignment with reference output:
CIP reconciliation report_Jul26_output file.xlsx
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .cip_reader import ACCOUNTS
from .cip_reconciliation_engine import CIPReconciliationResult

logger = logging.getLogger(__name__)


class CIPReportGenerator:
    """Generates the CIP Reconciliation Excel workbook."""

    def __init__(self, recon_result: CIPReconciliationResult):
        self.result = recon_result

    def generate(self, output_path: Union[str, Path]) -> Path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()
        # Default sheet
        ws = wb.active
        ws.title = "Sheet1"

        # Styles
        font_header_top = Font(name="Calibri", size=11, bold=True, color="000000")
        font_header_sub = Font(name="Calibri", size=10, bold=True, color="000000")
        font_data = Font(name="Calibri", size=10)
        font_total = Font(name="Calibri", size=10, bold=True)

        fill_top_open = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
        fill_top_add = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
        fill_top_int = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
        fill_top_bal = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
        fill_sub_hdr = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
        fill_total = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")

        thin_side = Side(border_style="thin", color="D3D3D3")
        thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        double_bottom = Border(top=thin_side, bottom=Side(border_style="double", color="000000"))

        align_center = Alignment(horizontal="center", vertical="center")
        align_right = Alignment(horizontal="right", vertical="center")
        align_left = Alignment(horizontal="left", vertical="center")

        num_fmt = "#,##0.00;(#,##0.00);0.00"

        # Row 1: Section Headers
        # Jun2026 (Cols 4-10 = D..J)
        ws.merge_cells(start_row=1, start_column=4, end_row=1, end_column=10)
        c_jun = ws.cell(1, 4, f"Jun2026")
        c_jun.font = font_header_top
        c_jun.alignment = align_center
        c_jun.fill = fill_top_open

        # Additions (Cols 11-16 = K..P)
        ws.merge_cells(start_row=1, start_column=11, end_row=1, end_column=16)
        c_add = ws.cell(1, 11, f"Additions Jul'2026")
        c_add.font = font_header_top
        c_add.alignment = align_center
        c_add.fill = fill_top_add

        # Interface (Cols 17-22 = Q..V)
        ws.merge_cells(start_row=1, start_column=17, end_row=1, end_column=22)
        c_int = ws.cell(1, 17, f"Interface Jul2026")
        c_int.font = font_header_top
        c_int.alignment = align_center
        c_int.fill = fill_top_int

        # Balance (Cols 23-29 = W..AC)
        ws.merge_cells(start_row=1, start_column=23, end_row=1, end_column=29)
        c_bal = ws.cell(1, 23, f"Balance Jul2026")
        c_bal.font = font_header_top
        c_bal.alignment = align_center
        c_bal.fill = fill_top_bal

        # Row 2: Sub-headers
        headers = [
            "Project No", "Project Name", "Year",
            111401, 111402, 111403, 111404, 111405, 111406, "Total",
            111401, 111402, 111403, 111404, 111405, 111406,
            111401, 111402, 111403, 111404, 111405, 111406,
            111401, 111402, 111403, 111404, 111405, 111406, "Total",
        ]

        for col_idx, h_text in enumerate(headers, 1):
            cell = ws.cell(2, col_idx, h_text)
            cell.font = font_header_sub
            cell.alignment = align_center if col_idx <= 3 else align_right
            cell.fill = fill_sub_hdr
            cell.border = thin_border

        # Data Rows (Row 3 onwards)
        current_row = 3
        for p in self.result.projects:
            # Col A: Project No
            try:
                p_num_val = int(p["project_no"])
            except ValueError:
                p_num_val = p["project_no"]
            c_pno = ws.cell(current_row, 1, p_num_val)
            c_pno.font = font_data
            c_pno.alignment = align_center
            c_pno.border = thin_border

            # Col B: Project Name
            c_pname = ws.cell(current_row, 2, p.get("project_name", ""))
            c_pname.font = font_data
            c_pname.alignment = align_left
            c_pname.border = thin_border

            # Col C: Year
            c_yr = ws.cell(current_row, 3, p.get("year", ""))
            c_yr.font = font_data
            c_yr.alignment = align_center
            c_yr.border = thin_border

            # Jun2026 Opening balances (Cols 4-9 = D..I)
            for i, acct in enumerate(ACCOUNTS):
                val = p["opening"].get(acct, 0.0)
                cell = ws.cell(current_row, 4 + i, val if val != 0.0 else 0)
                cell.font = font_data
                cell.alignment = align_right
                cell.number_format = num_fmt
                cell.border = thin_border

            # Col 10 (J): Opening Total Formula =SUM(D3:I3)
            c_tot_open = ws.cell(current_row, 10, f"=SUM(D{current_row}:I{current_row})")
            c_tot_open.font = font_data
            c_tot_open.alignment = align_right
            c_tot_open.number_format = num_fmt
            c_tot_open.border = thin_border

            # Additions Jul'2026 (Cols 11-16 = K..P)
            for i, acct in enumerate(ACCOUNTS):
                val = p["additions"].get(acct, 0.0)
                cell = ws.cell(current_row, 11 + i, val if val != 0.0 else 0)
                cell.font = font_data
                cell.alignment = align_right
                cell.number_format = num_fmt
                cell.border = thin_border

            # Interface Jul2026 (Cols 17-22 = Q..V)
            for i, acct in enumerate(ACCOUNTS):
                val = p["interface"].get(acct, 0.0)
                cell = ws.cell(current_row, 17 + i, val if val != 0.0 else 0)
                cell.font = font_data
                cell.alignment = align_right
                cell.number_format = num_fmt
                cell.border = thin_border

            # Balance Jul2026 (Cols 23-28 = W..AB)
            # Formula: =+D{r}+K{r}+Q{r}, =+E{r}+L{r}+R{r}, etc.
            open_col_letters = ["D", "E", "F", "G", "H", "I"]
            add_col_letters = ["K", "L", "M", "N", "O", "P"]
            int_col_letters = ["Q", "R", "S", "T", "U", "V"]
            for i in range(6):
                o_col = open_col_letters[i]
                a_col = add_col_letters[i]
                u_col = int_col_letters[i]
                formula = f"=+{o_col}{current_row}+{a_col}{current_row}+{u_col}{current_row}"
                cell = ws.cell(current_row, 23 + i, formula)
                cell.font = font_data
                cell.alignment = align_right
                cell.number_format = num_fmt
                cell.border = thin_border

            # Col 29 (AC): Closing Total Formula =SUM(W3:AB3)
            c_tot_close = ws.cell(current_row, 29, f"=SUM(W{current_row}:AB{current_row})")
            c_tot_close.font = font_data
            c_tot_close.alignment = align_right
            c_tot_close.number_format = num_fmt
            c_tot_close.border = thin_border

            current_row += 1

        last_data_row = current_row - 1

        # Summary / Total Row
        if last_data_row >= 3:
            ws.cell(current_row, 1, "Total")
            ws.cell(current_row, 1).font = font_total
            ws.cell(current_row, 1).alignment = align_center
            ws.cell(current_row, 1).fill = fill_total
            ws.cell(current_row, 1).border = double_bottom

            for col_idx in range(2, 4):
                c_empty = ws.cell(current_row, col_idx, None)
                c_empty.fill = fill_total
                c_empty.border = double_bottom

            # Columns D to AC: =SUM({col}3:{col}{last_data_row})
            for col_idx in range(4, 30):
                col_letter = get_column_letter(col_idx)
                sum_formula = f"=SUM({col_letter}3:{col_letter}{last_data_row})"
                cell = ws.cell(current_row, col_idx, sum_formula)
                cell.font = font_total
                cell.alignment = align_right
                cell.number_format = num_fmt
                cell.fill = fill_total
                cell.border = double_bottom

        # Auto-adjust column widths
        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["B"].width = 36
        ws.column_dimensions["C"].width = 8
        for c in range(4, 30):
            ws.column_dimensions[get_column_letter(c)].width = 16

        # Sheet 2: Reconciliation & GL Variance Analysis
        ws2 = wb.create_sheet(title="Reconciliation & GL Variance")
        ws2.views.sheetView[0].showGridLines = True

        ws2.cell(1, 1, f"CIP & General Ledger Reconciliation - {self.result.period}").font = Font(
            name="Calibri", size=14, bold=True, color="0B3041"
        )

        gl_headers = [
            "Account", "Subledger Additions", "GL Journal Additions (DR)", "Additions Variance",
            "Interfaced CIP Total", "GL Interface Transfer (CR)", "Interface Variance", "Reconciliation Status", "Notes"
        ]
        for c_idx, h in enumerate(gl_headers, 1):
            cell = ws2.cell(3, c_idx, h)
            cell.font = font_header_sub
            cell.alignment = align_center
            cell.fill = fill_sub_hdr
            cell.border = thin_border

        r_idx = 4
        for ar in self.result.account_reconciliations:
            ws2.cell(r_idx, 1, ar["account"]).alignment = align_center
            ws2.cell(r_idx, 2, ar["subledger_additions"]).number_format = num_fmt
            ws2.cell(r_idx, 3, ar["gl_additions_dr"]).number_format = num_fmt
            ws2.cell(r_idx, 4, ar["additions_variance"]).number_format = num_fmt
            ws2.cell(r_idx, 5, ar["interfaced_cip_total"]).number_format = num_fmt
            ws2.cell(r_idx, 6, ar["gl_interface_cr"]).number_format = num_fmt
            ws2.cell(r_idx, 7, ar["interface_variance"]).number_format = num_fmt
            ws2.cell(r_idx, 8, ar["status"]).alignment = align_center
            ws2.cell(r_idx, 9, "; ".join(ar.get("notes", []))).alignment = align_left

            for c in range(1, 10):
                ws2.cell(r_idx, c).font = font_data
                ws2.cell(r_idx, c).border = thin_border
            r_idx += 1

        # Discrepancies table
        r_idx += 2
        ws2.cell(r_idx, 1, "Exception & Discrepancy Log").font = Font(
            name="Calibri", size=12, bold=True, color="0B3041"
        )
        r_idx += 1
        disc_hdrs = ["Exception Type", "Project No", "Account", "Amount", "Detail"]
        for c_idx, h in enumerate(disc_hdrs, 1):
            cell = ws2.cell(r_idx, c_idx, h)
            cell.font = font_header_sub
            cell.alignment = align_center
            cell.fill = fill_sub_hdr
            cell.border = thin_border

        r_idx += 1
        if not self.result.discrepancies:
            ws2.cell(r_idx, 1, "No discrepancies identified. All accounts and projects reconciled.").font = font_data
        else:
            for d in self.result.discrepancies:
                ws2.cell(r_idx, 1, d.get("type", "")).alignment = align_left
                ws2.cell(r_idx, 2, d.get("project_no", "")).alignment = align_center
                ws2.cell(r_idx, 3, d.get("account", "")).alignment = align_center
                ws2.cell(r_idx, 4, d.get("amount", 0.0)).number_format = num_fmt
                ws2.cell(r_idx, 5, d.get("detail", "")).alignment = align_left
                for c in range(1, 6):
                    ws2.cell(r_idx, c).font = font_data
                    ws2.cell(r_idx, c).border = thin_border
                r_idx += 1

        # Adjust ws2 column widths
        for c in range(1, 10):
            ws2.column_dimensions[get_column_letter(c)].width = 22

        wb.save(output_file)
        logger.info(f"Successfully generated CIP reconciliation report at {output_file}")
        return output_file

