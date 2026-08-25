from fastapi import APIRouter, Depends
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    try:
        return get_revenue_forecast(db)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forecast data is temporarily unavailable.",
        ) from exc