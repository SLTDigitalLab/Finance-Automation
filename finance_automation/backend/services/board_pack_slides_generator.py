"""Builds a two-slide Ratio and Group Balance Sheet PowerPoint."""
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from services.board_pack_slides_reader import BoardPackSlidesData, RatioMetric

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "board_pack_templates" / "board_pack_template.pptx"

_NAVY = RGBColor(0x00, 0x1B, 0x89)
_BLUE = RGBColor(0x56, 0x99, 0xD6)
_PALE_BLUE = RGBColor(0xDB, 0xE9, 0xF7)
_PALE_YELLOW = RGBColor(0xFF, 0xFF, 0x99)
_BLACK = RGBColor(0x00, 0x00, 0x00)
_DARK_BLUE = RGBColor(0x00, 0x2B, 0x65)
_GREY = RGBColor(0x4A, 0x4A, 0x4A)


def _rounded(value: float, places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _format_amount(value: float, places: int) -> str:
    amount = _rounded(value, places)
    if amount == 0:
        return "-"
    pattern = f"{{:,.{places}f}}" if places else "{:,.0f}"
    text = pattern.format(abs(amount))
    return f"({text})" if amount < 0 else text


def _format_ratio(metric: RatioMetric, value: float, decimal_places: int) -> str:
    if metric.value_format == "percent":
        scaled = _rounded(abs(value) * 100, decimal_places)
        text = f"{scaled:.{decimal_places}f}%"
        return f"({text})" if value < 0 else text
    return _format_amount(value, decimal_places)


def _rect(slide, x, y, width, height, fill, border=None, border_width=0.8):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(width), Inches(height)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if border is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = border
        shape.line.width = Pt(border_width)
    return shape


def _text(
    slide, text, x, y, width, height, *, size=12, color=_BLACK, bold=False,
    align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.MIDDLE, margin=0.04, underline=False,
):
    shape = slide.shapes.add_textbox(
        Inches(x), Inches(y), Inches(width), Inches(height)
    )
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = Inches(margin)
    frame.margin_right = Inches(margin)
    frame.margin_top = Inches(0.01)
    frame.margin_bottom = Inches(0.01)
    frame.vertical_anchor = valign
    for index, line in enumerate(str(text).split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.space_before = Pt(0)
        paragraph.space_after = Pt(0)
        run = paragraph.add_run()
        run.text = line
        run.font.name = "Arial"
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.underline = underline
        run.font.color.rgb = color
    return shape


def _logo_blob() -> bytes:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Board-pack template is missing: {TEMPLATE_PATH}")
    template = Presentation(str(TEMPLATE_PATH))
    for slide in template.slides:
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                return shape.image.blob
    raise ValueError(f"No company logo was found in the board-pack template: {TEMPLATE_PATH}")


def _add_footer(slide, number: int, logo: bytes):
    _text(slide, str(number), 12.18, 7.10, 0.16, 0.24, size=9, color=_GREY, align=PP_ALIGN.CENTER, margin=0)
    slide.shapes.add_picture(
        BytesIO(logo), Inches(12.43), Inches(7.10), width=Inches(0.80)
    )


def _new_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return slide


def _add_balance_sheet_slide(prs, data: BoardPackSlidesData, logo: bytes):
    slide = _new_slide(prs)
    _text(slide, "Balance Sheet (Group)", 1.17, 0.27, 9.55, 0.46, size=28, color=_NAVY, bold=True, margin=0)
    _rect(slide, 1.10, 0.75, 9.85, 0.035, _BLUE)
    _text(slide, "< Rs. Mn >", 9.60, 0.82, 1.65, 0.20, size=10, color=_BLACK, bold=True, align=PP_ALIGN.RIGHT)

    left = 1.10
    width = 10.20
    label_width = 6.46
    current_width = 1.87
    previous_width = width - label_width - current_width
    header_y = 1.05
    header_height = 0.46
    _rect(slide, left, header_y, width, header_height, _PALE_YELLOW)
    _text(slide, "Financial Position", left + 0.05, header_y, label_width - 0.1, header_height,
          size=15, color=_DARK_BLUE, bold=True)
    _text(slide, f"{data.period_month}- {data.period_year}", left + label_width, header_y,
          current_width, header_height, size=14, color=_DARK_BLUE, bold=True, align=PP_ALIGN.CENTER)
    _text(slide, f"{data.previous_month} – {data.previous_year}", left + label_width + current_width,
          header_y, previous_width, header_height, size=14, color=_DARK_BLUE, bold=True, align=PP_ALIGN.CENTER)

    sections = (
        data.balance_sheet[0:5],
        data.balance_sheet[5:6],
        data.balance_sheet[6:10],
        data.balance_sheet[10:],
    )
    y = 1.56
    row_height = 0.32
    section_gap = 0.28
    for section_index, section in enumerate(sections):
        for row in section:
            if row.is_total:
                _rect(slide, left, y, width, row_height, _PALE_BLUE)
            _text(slide, row.label, left + 0.05, y, label_width - 0.1, row_height,
                  size=13.2, color=_DARK_BLUE if row.is_total or row.label == "Non-Current Assets" else _GREY,
                  bold=row.is_total)
            _text(slide, _format_amount(row.current, 0), left + label_width, y,
                  current_width - 0.10, row_height, size=13.2, color=_BLACK,
                  bold=row.is_total, align=PP_ALIGN.RIGHT, margin=0.02)
            _text(slide, _format_amount(row.previous, 0), left + label_width + current_width, y,
                  previous_width - 0.08, row_height, size=13.2, color=_BLACK,
                  bold=row.is_total, align=PP_ALIGN.RIGHT, margin=0.02)
            y += row_height
        if section_index < len(sections) - 1:
            y += section_gap

    _add_footer(slide, 1, logo)
    return slide


def _category_groups(ratios):
    groups = []
    for metric in ratios:
        if not groups or groups[-1][0] != metric.category:
            groups.append((metric.category, []))
        groups[-1][1].append(metric)
    return groups


def _add_ratio_row(slide, metric: RatioMetric, y: float):
    label_x, label_width = 1.90, 3.20
    group_x, group_width = 5.32, 3.15
    company_x, company_width = 9.02, 3.15
    group_column_width = group_width / 3
    company_column_width = company_width / 3

    _rect(slide, label_x, y, label_width, metric.row_height, _PALE_BLUE)
    _rect(slide, group_x, y, group_width, metric.row_height, _PALE_BLUE)
    _rect(slide, company_x, y, company_width, metric.row_height, _PALE_BLUE)
    _text(slide, metric.label, label_x + 0.07, y, label_width - 0.13, metric.row_height,
          size=10.6, color=_BLACK, bold=True, margin=0.01)
    group_values = zip(
        (metric.group_current, metric.group_previous, metric.group_variance),
        metric.group_decimals,
    )
    company_values = zip(
        (metric.company_current, metric.company_previous, metric.company_variance),
        metric.company_decimals,
    )
    for index, (value, decimals) in enumerate(group_values):
        _text(slide, _format_ratio(metric, value, decimals), group_x + index * group_column_width,
              y, group_column_width - 0.04, metric.row_height, size=9.7,
              color=_BLACK, align=PP_ALIGN.RIGHT, margin=0.04)
    for index, (value, decimals) in enumerate(company_values):
        _text(slide, _format_ratio(metric, value, decimals), company_x + index * company_column_width,
              y, company_column_width - 0.04, metric.row_height, size=9.7,
              color=_BLACK, align=PP_ALIGN.RIGHT, margin=0.04)


def _add_ratios_slide(prs, data: BoardPackSlidesData, logo: bytes):
    slide = _new_slide(prs)
    _text(slide, "Summary – Ratios", 0.79, 0.18, 8.00, 0.46, size=28, color=_NAVY, bold=True, margin=0)
    _rect(slide, 0.32, 0.62, 11.84, 0.035, _BLUE)

    header_x, header_y, header_width, header_height = 0.27, 0.68, 11.90, 0.62
    _rect(slide, header_x, header_y, header_width, header_height, _PALE_YELLOW)
    _text(slide, "Group - YTD", 5.32, 0.70, 3.15, 0.25, size=12, color=_DARK_BLUE,
          bold=True, align=PP_ALIGN.CENTER)
    _text(slide, "Company - YTD", 9.02, 0.70, 3.15, 0.25, size=12, color=_DARK_BLUE,
          bold=True, align=PP_ALIGN.CENTER)
    headers = (str(data.current_year), str(data.ratio_previous_year), "Vari")
    for start, width in ((5.32, 3.15), (9.02, 3.15)):
        col_width = width / 3
        for index, label in enumerate(headers):
            _text(slide, label, start + index * col_width, 1.00, col_width, 0.25,
                  size=11, color=_DARK_BLUE, bold=True, align=PP_ALIGN.CENTER, underline=True)

    y = header_y + header_height
    row_gap = 0.1875
    group_gap = 0.21
    groups = _category_groups(data.ratios)
    for group_index, (category, metrics) in enumerate(groups):
        block_start = y
        for metric_index, metric in enumerate(metrics):
            _add_ratio_row(slide, metric, y)
            y += metric.row_height
            if metric_index < len(metrics) - 1:
                y += row_gap
        block_height = y - block_start
        _rect(slide, 0.27, block_start, 1.55, block_height, _PALE_BLUE, border=_BLACK, border_width=0.9)
        _text(slide, category, 0.30, block_start + 0.02, 1.49, block_height - 0.04,
              size=10.5, color=_BLACK, bold=True, align=PP_ALIGN.CENTER, margin=0.02)
        if group_index < len(groups) - 1:
            y += group_gap

    _add_footer(slide, 2, logo)
    return slide


def generate_board_pack_slides(data: BoardPackSlidesData, output_dir: str) -> str:
    """Write the two-slide PowerPoint and return its absolute path."""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    prs.core_properties.title = "Finance Board Pack - Balance Sheet and Ratios"
    prs.core_properties.subject = f"{data.period_month} {data.period_year}"
    logo = _logo_blob()

    _add_balance_sheet_slide(prs, data, logo)
    _add_ratios_slide(prs, data, logo)

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    filename = (
        f"Finance_Board_Pack_Slides_{data.period_month}_{data.period_year}_"
        f"{uuid4().hex[:8]}.pptx"
    )
    output_path = destination / filename
    prs.save(str(output_path))
    return str(output_path)
