import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from app.database.connection import get_db
from app.models.user_and_log import AuditLog, User
from app.schemas.auth_schemas import PaginatedAuditLogs
from app.auth.jwt_handler import get_admin_user

audit_router = APIRouter(prefix="/api/audit-logs", tags=["audit"])

@audit_router.get("", response_model=PaginatedAuditLogs)
async def get_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    module: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    query = db.query(AuditLog)
    
    # Filter by user_id
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
        
    # Filter by action
    if action:
        query = query.filter(AuditLog.action == action)

    # Filter by module
    if module:
        if module in ["Revenue Analysis", "Revenue Analytics", "Finance"]:
            query = query.filter(AuditLog.module.in_(["Revenue Analysis", "Revenue Analytics", "Finance"]))
        else:
            query = query.filter(AuditLog.module == module)
        
    # Filter by date range
    if start_date:
        try:
            start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= start_dt)
        except ValueError:
            pass
            
    if end_date:
        try:
            # Add 1 day to make the end date inclusive
            end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
            query = query.filter(AuditLog.created_at < end_dt)
        except ValueError:
            pass
            
    # Search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                AuditLog.user_name.like(search_pattern),
                AuditLog.action.like(search_pattern),
                AuditLog.module.like(search_pattern),
                AuditLog.description.like(search_pattern),
                AuditLog.ip_address.like(search_pattern)
            )
        )
        
    # Get total count
    total = query.count()
    
    # Order by newest first, then paginate
    logs = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    
    return {
        "total": total,
        "logs": logs
    }
