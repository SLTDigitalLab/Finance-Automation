from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.jwt_handler import get_current_active_user
from app.database.connection import get_db
from app.models.user_and_log import User
from app.services.revenue_forecasting_service import get_revenue_forecast


forecast_router = APIRouter(prefix="/api/forecast", tags=["forecast"])


@forecast_router.get("/revenue")
async def revenue_forecast(
    target_month: Optional[int] = Query(None, ge=1, le=12, description="Target forecast month (1-12)"),
    target_year: Optional[int] = Query(None, ge=2020, description="Target forecast year"),
    target_period: Optional[str] = Query(None, description="Target forecast period string e.g. 'December 2026'"),
    horizon: Optional[int] = Query(None, ge=1, le=120, description="Custom forecast horizon in months"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    try:
        return get_revenue_forecast(
            db=db,
            target_month=target_month,
            target_year=target_year,
            target_period=target_period,
            horizon=horizon,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forecast data is temporarily unavailable.",
        ) from exc