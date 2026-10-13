"""Use case access API: which finance use case(s) each email may open."""
import logging
from typing import List

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.jwt_handler import get_admin_user, get_current_active_user
from app.database.connection import get_db
from app.models.user_and_log import User, UserUseCaseAccess
from app.services.audit_logger import log_audit

logger = logging.getLogger(__name__)
use_case_router = APIRouter(prefix="/api/use-cases", tags=["use-cases"])

# Must match the ids in frontend/src/config/useCases.js
USE_CASE_IDS = ["revenue", "board_pack"] + [f"use_case_{n}" for n in range(3, 14)] + ["petty_cash", "use_case_14"]


class AssignmentUpdate(BaseModel):
    email: str
    use_cases: List[str]


def _normalise_email(email: str) -> str:
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid email address: {exc}") from exc


def get_user_use_cases(db: Session, user: User) -> List[str]:
    if user.role == "Admin":
        return list(USE_CASE_IDS)
    rows = (
        db.query(UserUseCaseAccess.use_case_id)
        .filter(UserUseCaseAccess.email == (user.email or "").lower())
        .all()
    )
    return [r[0] for r in rows if r[0] in USE_CASE_IDS]


def require_use_case(use_case_id: str):
    """Route dependency: only users assigned to `use_case_id` (or Admins) may call the endpoint."""

    def checker(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if use_case_id not in get_user_use_cases(db, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not assigned to this use case.",
            )
        return current_user

    return checker


@use_case_router.get("/me")
def my_use_cases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return {"use_cases": get_user_use_cases(db, current_user)}


@use_case_router.get("/assignments")
def list_assignments(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Every non-admin user plus any emails assigned before they first logged in."""
    assigned: dict = {}
    for row in db.query(UserUseCaseAccess).all():
        assigned.setdefault(row.email, []).append(row.use_case_id)

    result = []
    for user in db.query(User).filter(User.role != "Admin").order_by(User.full_name).all():
        email = (user.email or "").lower()
        use_cases = assigned.pop(email, [])
        result.append({
            "email": email,
            "full_name": user.full_name,
            "user_id": user.id,
            "status": user.status,
            "is_active": user.is_active,
            "registered": True,
            "use_cases": [u for u in USE_CASE_IDS if u in use_cases],
        })
    for email, use_cases in sorted(assigned.items()):
        result.append({
            "email": email,
            "full_name": None,
            "user_id": None,
            "status": None,
            "is_active": None,
            "registered": False,
            "use_cases": [u for u in USE_CASE_IDS if u in use_cases],
        })
    return result


@use_case_router.put("/assignments")
def update_assignment(
    payload: AssignmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Replaces the use cases assigned to an email. An empty list removes all access."""
    email = _normalise_email(payload.email)
    unknown = [u for u in payload.use_cases if u not in USE_CASE_IDS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown use case(s): {', '.join(unknown)}")
    wanted = [u for u in USE_CASE_IDS if u in set(payload.use_cases)]

    db.query(UserUseCaseAccess).filter(UserUseCaseAccess.email == email).delete()
    for use_case_id in wanted:
        db.add(UserUseCaseAccess(email=email, use_case_id=use_case_id, assigned_by=admin.id))
    db.commit()

    log_audit(
        db=db,
        action="Use Case Assignment",
        module="User Management",
        description=f"Admin set use cases for {email}: {', '.join(wanted) or 'none'}",
        user_id=admin.id,
        user_name=admin.full_name,
        request=request,
    )
    return {"email": email, "use_cases": wanted}
