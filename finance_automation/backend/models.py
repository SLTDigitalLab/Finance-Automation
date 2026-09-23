from typing import Optional
from pydantic import BaseModel


class TBRow(BaseModel):
    gl_code: str = ""
    description: str = ""
    flexfield: str = ""
    cost_center: str = ""
    location: str = ""
    business_line: str = ""
    product: str = ""
    account: str = ""
    technology: str = ""
    intercompany: str = ""
    project: str = ""
    beginning_balance: float = 0.0
    period_activity: float = 0.0
    ending_balance: float = 0.0
    revenue_category: str = ""
    sub_category: str = ""
    row_index: int = 0


class RevenueResult(BaseModel):
    category: str
    month_actual: float = 0.0
    month_budget: float = 0.0
    month_variance: float = 0.0
    month_variance_pct: Optional[float] = None
    py_month_actual: float = 0.0
    ytd_actual: float = 0.0
    ytd_budget: float = 0.0
    ytd_variance: float = 0.0
    ytd_variance_pct: Optional[float] = None
    py_ytd_actual: float = 0.0
    is_subtotal: bool = False
    is_grand_total: bool = False


class UploadedFiles(BaseModel):
    tb_current: str = ""
    tb_previous: str = ""
    budget: str = ""
    mapping: str = ""


class ReportRequest(BaseModel):
    pass


class RevenueSummary(BaseModel):
    period_month: str = ""
    period_year: int = 0
    mapped_month: float = 0.0
    mapped_ytd: float = 0.0
    unmapped_month: float = 0.0
    unmapped_ytd: float = 0.0
    pl_month_revenue: Optional[float] = None
    pl_ytd_revenue: Optional[float] = None


class ReportResponse(BaseModel):
    status: str
    filename: str = ""
    unmapped_count: int = 0
    total_mapped: int = 0
    processing_time_seconds: float = 0.0
    report_month: str = ""
    report_year: int = 0
    message: str = ""
    revenue_summary: Optional[RevenueSummary] = None


class ValidationError(BaseModel):
    file: str
    error: str
    severity: str = "error"
