"""Anomaly & Fraud Detection API Routes"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.jwt_handler import get_admin_user, get_current_active_user
from app.database.connection import get_db
from app.models.user_and_log import User
from app.services.anomaly_detection_service import (
    get_anomaly_results,
    get_anomaly_summary,
    get_category_month_matrix,
    get_filter_options,
    run_anomaly_detection,
    trigger_background_anomaly_analysis,
)

logger = logging.getLogger(__name__)
anomaly_router = APIRouter(prefix="/api/anomaly", tags=["anomaly"])


@anomaly_router.get("/matrix")
def anomaly_matrix(
    year: Optional[int] = Query(None, description="Operating year to retrieve matrix for"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns the Category × Month anomaly indicator matrix for the given year.

    Provides aggregated status (HIGH, MEDIUM, NORMAL, NO_DATA), anomaly counts,
    and highest risk scores for each revenue category across all dynamic months.
    """
    try:
        return get_category_month_matrix(db, year=year)
    except Exception as exc:
        logger.exception(f"Failed to compute anomaly matrix: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve anomaly matrix: {str(exc)}",
        ) from exc


@anomaly_router.get("/summary")
def anomaly_summary(
    year: Optional[int] = Query(None, description="Filter summary by year"),
    period_month: Optional[str] = Query(None, description="Filter summary by month"),
    revenue_category: Optional[str] = Query(None, description="Filter summary by category"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns aggregate anomaly detection statistics and KPI card figures.

    Provides total records analyzed, counts by risk level (HIGH, MEDIUM, LOW),
    and latest month statistics.
    """
    try:
        return get_anomaly_summary(
            db,
            year=year,
            period_month=period_month,
            revenue_category=revenue_category,
        )
    except Exception as exc:
        logger.exception(f"Failed to retrieve anomaly summary: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve anomaly summary: {str(exc)}",
        ) from exc


@anomaly_router.get("/results")
def anomaly_results(
    year: Optional[int] = Query(None, description="Filter by year"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level: HIGH, MEDIUM, LOW"),
    period_month: Optional[str] = Query(None, description="Filter by period month name e.g. June"),
    revenue_category: Optional[str] = Query(None, description="Filter by revenue category"),
    search: Optional[str] = Query(None, description="Search GL code, description, or account"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return"),
    sort_by: str = Query("anomaly_score", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns paginated list of anomalous / suspicious transactions.

    Each record includes full flexfield context, beginning/ending balances,
    anomaly score, Z-score, risk level, and human-readable risk reason.

    IMPORTANT: Anomaly indicators identify unusual financial patterns
    for human review and do NOT confirm fraud.
    """
    if risk_level and risk_level.upper() not in {"HIGH", "MEDIUM", "LOW"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="risk_level must be one of: HIGH, MEDIUM, LOW",
        )

    try:
        return get_anomaly_results(
            db,
            year=year,
            risk_level=risk_level,
            period_month=period_month,
            revenue_category=revenue_category,
            search=search,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except Exception as exc:
        logger.exception(f"Failed to retrieve anomaly results: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve anomaly results: {str(exc)}",
        ) from exc


@anomaly_router.get("/filters")
def anomaly_filter_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Returns dynamic filter options (years, months, categories) for frontend dropdowns."""
    try:
        return get_filter_options(db)
    except Exception as exc:
        logger.exception(f"Failed to retrieve filter options: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve filter options: {str(exc)}",
        ) from exc


@anomaly_router.post("/analyze")
def trigger_analysis(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """
    Triggers background anomaly detection across all processed TB records (Admin only).
    Runs asynchronously and returns immediately.
    """
    try:
        trigger_background_anomaly_analysis()
        return {
            "status": "started",
            "message": "Anomaly detection analysis has been triggered in the background.",
        }
    except Exception as exc:
        logger.exception(f"Failed to trigger analysis: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger analysis: {str(exc)}",
        ) from exc


@anomaly_router.post("/analyze/sync")
def trigger_analysis_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """
    Runs anomaly detection synchronously and returns completion summary (Admin only).
    """
    try:
        result = run_anomaly_detection(db)
        return result
    except Exception as exc:
        logger.exception(f"Synchronous anomaly detection failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Anomaly detection failed: {str(exc)}",
        ) from exc
