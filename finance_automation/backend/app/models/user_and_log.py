import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from app.database.connection import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False, default="")
    auth_provider = Column(String, default="local")  # "local" or "microsoft"
    microsoft_id = Column(String, nullable=True, unique=True, index=True)   # Graph object ID
    service_number = Column(String, nullable=True)   # UPN prefix e.g. "012345"
    role = Column(String, default="User")  # "Admin" or "User"
    status = Column(String, default="Pending")  # "Pending", "Approved", "Rejected"
    is_active = Column(Boolean, default=True)

    created_by = Column(Integer, nullable=True)
    approved_by = Column(Integer, nullable=True)
    approved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, nullable=True)
    action = Column(String, nullable=False)  # "Registration", "Login", etc.
    module = Column(String, nullable=False)  # "Auth", "User Management", etc.
    description = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class PasswordResetOTP(Base):
    __tablename__ = "password_reset_otps"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    otp_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ReportJob(Base):
    """Persists report generation results so all server workers can read them."""
    __tablename__ = "report_jobs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, nullable=False)  # "processing" | "success" | "error"
    result_json = Column(Text, nullable=True)  # full JSON blob of ReportResponse.model_dump()
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


class UploadedFinanceFile(Base):
    __tablename__ = "uploaded_finance_files"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    file_type = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_hash = Column(String, nullable=False, unique=True, index=True)
    period_month = Column(String, nullable=True)
    period_year = Column(Integer, nullable=True)
    file_size = Column(Integer, nullable=True)
    status = Column(String, default="uploaded")
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)


class FinancialTBRecord(Base):
    __tablename__ = "financial_tb_records"
    __table_args__ = (
        UniqueConstraint(
            "uploaded_file_id",
            "row_index",
            name="uq_financial_tb_records_uploaded_file_row",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    uploaded_file_id = Column(
        Integer, ForeignKey("uploaded_finance_files.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    period_month = Column(String, nullable=True)
    period_year = Column(Integer, nullable=True)
    gl_code = Column(String, nullable=True)
    description = Column(String, nullable=True)
    flexfield = Column(String, nullable=True)
    cost_center = Column(String, nullable=True)
    location = Column(String, nullable=True)
    business_line = Column(String, nullable=True)
    product = Column(String, nullable=True)
    account = Column(String, nullable=True)
    technology = Column(String, nullable=True)
    intercompany = Column(String, nullable=True)
    project = Column(String, nullable=True)
    beginning_balance = Column(Float, default=0.0)
    period_activity = Column(Float, default=0.0)
    ending_balance = Column(Float, default=0.0)
    revenue_category = Column(String, nullable=True)
    sub_category = Column(String, nullable=True)
    row_index = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
