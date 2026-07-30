import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
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
