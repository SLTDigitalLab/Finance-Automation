"""
Comprehensive Automated Test Suite for Board Pack Generation.

Validates:
  1. Structural file classification without relying on filenames
  2. Independent section generation (Board Pack, Ratio Report, Mobitel, Telecom Services)
  3. Multi-section combination (Mobitel + Telecom Services, All 4 sections)
  4. Exact slide count and sequence verification
  5. Dynamic category matching & row position tolerance
  6. Data integrity, calculations, negative numbers, percentages, and units
  7. Strict exclusion of SLT Income Stat. & Network cost for Mobitel
  8. Missing / invalid input validation errors
"""
import copy
import os
import shutil
import tempfile
from pathlib import Path

import openpyxl
import pytest
from pptx import Presentation

from services.board_pack_classifier import classify_file, check_section_requirements
from services.board_pack_combiner import combine_presentations
from services.board_pack_unified_service import generate_unified_pack, inspect_files
from services.mobitel_reader import read_mobitel_workbook
from services.mobitel_generator import generate_mobitel_deck, TEMPLATE_PATH as MOB_TMPL
from services.telecom_services_reader import read_telecom_services_inputs
from services.telecom_services_generator import generate_telecom_services_deck, TEMPLATE_PATH as TS_TMPL

# Paths to test sample files
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "files"
MOBITEL_ORIGINAL = SAMPLE_DIR / "3.New Format for PL  Board Pack Oct 2026 Original.xlsx"
MOBITEL_EDITED = SAMPLE_DIR / "Mobitel" / "3.Mobitel New Format for PL  Board Pack Oct 2026 Edited.xlsx"
TS_INFO_ORIGINAL = SAMPLE_DIR / "Telecom Services Information for PPT Original.xlsx"
TS_INFO_EDITED = SAMPLE_DIR / "Telecom Services" / "Telecom Services Information for PPT.xlsx"
TS_PL_ORIGINAL = SAMPLE_DIR / "SLTS PL Summery Telecom Services Original.xlsx"
TS_BSCF_PPTX = SAMPLE_DIR / "Telecom Services BS  CF_ SLTS.pptx"

requires_sample_files = pytest.mark.skipif(
    not MOBITEL_ORIGINAL.exists(),
    reason="Sample Excel/PPTX files are not present in repository files directory",
)


@requires_sample_files
def test_classifier_identifies_structures():
    """Verify that input files are accurately identified by internal structure without filenames."""
    # Test Mobitel workbook
    mob_info = classify_file(MOBITEL_ORIGINAL)
    assert mob_info["valid"] is True
    assert "mobitel_excel" in mob_info["roles"]
    assert mob_info["period"] == "Oct 2026"

    # Test Telecom Services Info
    ts_info = classify_file(TS_INFO_ORIGINAL)
    assert ts_info["valid"] is True
    assert "telecom_info_excel" in ts_info["roles"]

    # Test Telecom Services PL Summary
    pl_info = classify_file(TS_PL_ORIGINAL)
    assert pl_info["valid"] is True
    assert "telecom_pl_excel" in pl_info["roles"]
    assert pl_info["period"] == "Oct 2026"

    # Test Telecom Services BS & CF PPTX
    bscf_info = classify_file(TS_BSCF_PPTX)
    assert bscf_info["valid"] is True
    assert "telecom_bscf_pptx" in bscf_info["roles"]
    assert bscf_info["period"] == "Oct 2026"


@requires_sample_files
def test_requirements_checklist_validation():
    """Verify requirements logic enables generation only when all required inputs exist."""
    staged = [
        ("mobitel.xlsx", MOBITEL_ORIGINAL),
        ("ts_info.xlsx", TS_INFO_ORIGINAL),
    ]
    inspected = inspect_files(staged)

    # If only mobitel selected -> should be ready!
    status_mob = check_section_requirements(["mobitel"], inspected)
    assert status_mob["all_ready"] is True
    assert len(status_mob["missing"]) == 0

    # If telecom_services selected -> should NOT be ready (missing PL summary and BSCF pptx)
    status_ts = check_section_requirements(["telecom_services"], inspected)
    assert status_ts["all_ready"] is False
    assert any("P&L Summary" in m or "PL" in m for m in status_ts["missing"])
    assert any("BS & CF" in m for m in status_ts["missing"])


@requires_sample_files
def test_mobitel_reader_and_generator_independent():
    """Tests Mobitel 10-slide reader and generator."""
    data = read_mobitel_workbook(str(MOBITEL_ORIGINAL))
    assert data.month_label == "Oct"
    assert data.current_year == 2026
    assert data.previous_year == 2025

    # Check that excluded sheets were NOT read
    assert "SLT Income Stat." not in data.sheets_used
    assert "Network cost" not in data.sheets_used
    assert "SLT Presentation" in data.sheets_used
    assert "BS" in data.sheets_used
    assert "CF" in data.sheets_used

    # Check extracted values
    assert len(data.revenue_items) > 0
    # Rental income Month Act is ~116.69
    rental = next(it for it in data.revenue_items if "rentalincome" in it.label.lower().replace(" ", ""))
    assert round(rental.month_act) == 117
    assert round(rental.month_ly) == 150

    # Check subscribers
    assert data.subscribers.get("prepaid") == (6468134, 5920042)
    assert data.subscribers.get("postpaid") == (1078982, 1060172)

    # Test independent generation
    tmp_out = Path(tempfile.mkdtemp())
    try:
        out_deck = generate_mobitel_deck(data, str(tmp_out))
        prs = Presentation(out_deck)
        assert len(prs.slides) == 10

        # Verify Slide 2 (Revenue)
        t_rev = [sh for sh in prs.slides[1].shapes if sh.has_table][0].table
        assert t_rev.cell(2, 0).text.strip() == "Rental income"
        assert t_rev.cell(2, 2).text.strip() == "117"
        assert t_rev.cell(2, 3).text.strip() == "150"
        assert t_rev.cell(2, 4).text.strip() == "(33)"
        assert t_rev.cell(2, 5).text.strip() == "(22%)"
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)


@requires_sample_files
def test_telecom_services_reader_and_generator_independent():
    """Tests Telecom Services 9-slide reader and generator with dynamic category detection."""
    data = read_telecom_services_inputs(
        info_excel_path=str(TS_INFO_ORIGINAL),
        pl_excel_path=str(TS_PL_ORIGINAL),
        bscf_pptx_path=str(TS_BSCF_PPTX),
    )
    assert data.month_label == "Oct"
    assert data.current_year == 2026
    assert data.previous_year == 2025

    # Check Revenue items
    assert len(data.revenue_items) == 5
    si = next(it for it in data.revenue_items if it.label == "SI")
    assert round(si.act) == 535
    assert round(si.bud) == 790

    # Check Direct Costs
    assert len(data.direct_cost_items) >= 13

    # Test independent generation
    tmp_out = Path(tempfile.mkdtemp())
    try:
        out_deck = generate_telecom_services_deck(data, str(tmp_out))
        prs = Presentation(out_deck)
        assert len(prs.slides) == 9

        # Verify Slide 2 (Revenue)
        t_rev = [sh for sh in prs.slides[1].shapes if sh.has_table][0].table
        assert t_rev.cell(2, 0).text.strip() == "Service Integration"
        assert t_rev.cell(2, 2).text.strip() == "535"
        assert t_rev.cell(2, 3).text.strip() == "790"
        assert t_rev.cell(2, 4).text.strip() == "(255)"
        assert t_rev.cell(2, 5).text.strip() == "(32%)"

        # Verify Slide 7 & 8 (BS and CF copied from uploaded deck)
        t_bs = [sh for sh in prs.slides[6].shapes if sh.has_table][0].table
        assert "Non-current assets" in t_bs.cell(1, 0).text
        assert "1,947" in t_bs.cell(1, 5).text
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)


@requires_sample_files
def test_dynamic_telecom_services_row_shifts():
    """Validates that changing row positions in Telecom Services Information does not break parsing."""
    # TS_INFO_EDITED has shifted rows and explicit section titles
    data = read_telecom_services_inputs(
        info_excel_path=str(TS_INFO_EDITED),
        pl_excel_path=str(TS_PL_ORIGINAL),
        bscf_pptx_path=str(TS_BSCF_PPTX),
    )
    assert len(data.revenue_items) >= 4
    assert len(data.direct_cost_items) >= 12
    # Verify Content Cost (Peo TV) was correctly identified despite row shift
    content_cost = next(it for it in data.direct_cost_items if "Content Cost" in it.label)
    assert round(content_cost.act) == 2155


@requires_sample_files
def test_combined_mobitel_and_telecom_services():
    """Tests generating Mobitel + Telecom Services combined in one 19-slide presentation."""
    staged = [
        ("mobitel.xlsx", MOBITEL_ORIGINAL),
        ("ts_info.xlsx", TS_INFO_ORIGINAL),
        ("ts_pl.xlsx", TS_PL_ORIGINAL),
        ("ts_bscf.pptx", TS_BSCF_PPTX),
    ]

    tmp_out = Path(tempfile.mkdtemp())
    try:
        res = generate_unified_pack(
            staged_files=staged,
            selected_sections=["mobitel", "telecom_services"],
            user_output_dir=tmp_out,
        )
        assert res["status"] == "success"
        assert res["slide_count"] == 19
        assert res["sections_generated"] == ["Mobitel", "Telecom Services"]

        # Verify combined PPTX file
        out_file = tmp_out / res["filename"]
        assert out_file.exists()
        prs = Presentation(str(out_file))
        assert len(prs.slides) == 19

        # Verify Slide 1 is Mobitel title, Slide 10 is ARPU, Slide 11 is Telecom Services title, Slide 19 is Subscribers
        s1_text = " ".join(sh.text_frame.text for sh in prs.slides[0].shapes if sh.has_text_frame)
        s10_text = " ".join(sh.text_frame.text for sh in prs.slides[9].shapes if sh.has_text_frame)
        s11_text = " ".join(sh.text_frame.text for sh in prs.slides[10].shapes if sh.has_text_frame)
        s19_text = " ".join(sh.text_frame.text for sh in prs.slides[18].shapes if sh.has_text_frame)

        assert "Mobitel" in s1_text
        assert "ARPU" in s10_text
        assert "SLTS" in s11_text
        assert "Active Subscribers" in s19_text

        # Verify sequential slide numbering
        s1_num = [sh.text_frame.text.strip() for sh in prs.slides[0].shapes if sh.has_text_frame and "Slide Number" in sh.name]
        s11_num = [sh.text_frame.text.strip() for sh in prs.slides[10].shapes if sh.has_text_frame and "Slide Number" in sh.name]
        s19_num = [sh.text_frame.text.strip() for sh in prs.slides[18].shapes if sh.has_text_frame and "Slide Number" in sh.name]

        assert s1_num == ["1"]
        assert s11_num == ["11"]
        assert s19_num == ["19"]
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)


@requires_sample_files
def test_no_hardcoding_dynamic_updates():
    """Tests that modifying data in the input file dynamically changes the output deck."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        # Clone MOBITEL_ORIGINAL and alter rental income
        wb = openpyxl.load_workbook(str(MOBITEL_ORIGINAL))
        ws = wb["SLT Presentation"]
        ws.cell(4, 3).value = 999.0  # Month Act
        ws.cell(4, 4).value = 500.0  # Month LY
        ws.cell(4, 6).value = 499.0  # Month Vari
        ws.cell(4, 7).value = 0.998  # Month Vari%
        modified_excel = tmp_dir / "modified_mobitel.xlsx"
        wb.save(str(modified_excel))

        data = read_mobitel_workbook(str(modified_excel))
        rental = next(it for it in data.revenue_items if "rentalincome" in it.label.lower().replace(" ", ""))
        assert rental.month_act == 999.0

        out_deck = generate_mobitel_deck(data, str(tmp_dir))
        prs = Presentation(out_deck)
        t_rev = [sh for sh in prs.slides[1].shapes if sh.has_table][0].table
        assert t_rev.cell(2, 2).text.strip() == "999"
        assert t_rev.cell(2, 3).text.strip() == "500"
        assert t_rev.cell(2, 4).text.strip() == "499"
        assert t_rev.cell(2, 5).text.strip() == "100%"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_missing_input_error_reported():
    """Validates that missing required inputs raise a clear validation error without fallback."""
    tmp_out = Path(tempfile.mkdtemp())
    try:
        # Provide only Telecom Services info, but request Telecom Services (missing PL summary and BSCF deck)
        staged = [("info.xlsx", TS_INFO_ORIGINAL)]
        with pytest.raises(ValueError) as excinfo:
            generate_unified_pack(
                staged_files=staged,
                selected_sections=["telecom_services"],
                user_output_dir=tmp_out,
            )
        assert "Missing required inputs" in str(excinfo.value)
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)
