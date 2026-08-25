"""Anomaly & Fraud Detection API Routes"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional

from app.auth.jwt_handler import get_admin_user, get_current_active_user
from app.database.connection import get_db
from app.models.user_and_log import User
from app.services.anomaly_detection_service import (
    get_anomaly_results,
    get_anomaly_summary,
    get_filter_options,
    run_anomaly_detection,
    trigger_background_anomaly_analysis,
)

anomaly_router = APIRouter(prefix="/api/anomaly", tags=["anomaly"])


@anomaly_router.get("/summary")
def anomaly_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns aggregate anomaly detection statistics for the most recent analysis run.

    Provides total records analyzed and counts broken down by risk level
    (HIGH, MEDIUM, LOW), plus top suspicious categories for charts.
    """
    try:
        return get_anomaly_summary(db)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve anomaly summary: {str(exc)}",
        ) from exc


@anomaly_router.get("/results")
def anomaly_results(
    risk_level: Optional[str] = Query(None, description="Filter by risk level: HIGH, MEDIUM, LOW"),
    period_month: Optional[str] = Query(None, description="Filter by period month name e.g. June"),
    revenue_category: Optional[str] = Query(None, description="Filter by revenue category"),
    search: Optional[str] = Query(None, description="Search GL code, description, or account"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns paginated list of anomalous/suspicious transactions from the most recent run.

    Records are sorted by anomaly score (highest first).
    Each record includes the risk reason — a human-readable explanation of
    why the transaction was flagged for Finance Department review.

    IMPORTANT: These are potential anomalies for human review,
    not confirmed fraud classifications.
    """
    if risk_level and risk_level.upper() not in {"HIGH", "MEDIUM", "LOW"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="risk_level must be one of: HIGH, MEDIUM, LOW",
        )

    try:
        return get_anomaly_results(
            db,
            risk_level=risk_level,
            period_month=period_month,
            revenue_category=revenue_category,
            search=search,
            skip=skip,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve anomaly results: {str(exc)}",
        ) from exc


@anomaly_router.get("/filters")
def anomaly_filter_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Returns available filter options (months, categories) for the frontend dropdowns."""
    try:
        return get_filter_options(db)
    except Exception as exc:
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
    Triggers a new anomaly detection analysis on all processed TB records.

    Admin only. Runs asynchronously in the background — returns immediately.
    Results will be available via /api/anomaly/summary and /api/anomaly/results
    once the analysis completes (typically within a few seconds to a minute
    depending on data volume).
    """
    trigger_background_anomaly_analysis()
    return {
        "status": "started",
        "message": "Anomaly detection analysis has been triggered in the background. "
                   "Results will be available shortly via /api/anomaly/summary.",
    }


@anomaly_router.post("/analyze/sync")
def trigger_analysis_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """
    Runs anomaly detection synchronously and returns the full summary result.
    Admin only. Use this for manual re-analysis when you want to wait for completion.
    """
    try:
        result = run_anomaly_detection(db)
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Anomaly detection failed: {str(exc)}",
        ) from exc
