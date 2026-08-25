"""
Anomaly & Fraud Detection Service
===================================
Implements a hybrid Isolation Forest + Z-score approach to identify
potentially suspicious transactions in Trial Balance (TB) data.

NOTE: This service does NOT produce confirmed fraud classifications.
All outputs are anomaly scores for human review by Finance Department staff.
"""
import datetime
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import LabelEncoder
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user_and_log import (
    AnomalyDetectionResult,
    FinancialTBRecord,
    UploadedFinanceFile,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Isolation Forest contamination: expected fraction of anomalies (tunable)
CONTAMINATION = 0.05

# Composite score weights (must sum to 1.0)
ISOLATION_WEIGHT = 0.60
ZSCORE_WEIGHT = 0.40

# Risk thresholds (composite score 0.0–1.0)
RISK_HIGH_THRESHOLD = 0.70
RISK_MEDIUM_THRESHOLD = 0.40

# Minimum number of records required to run Isolation Forest meaningfully
MIN_RECORDS_FOR_IF = 10

# Detection method label stored with each result
DETECTION_METHOD = "hybrid_isolation_zscore"
MODEL_VERSION = "1.0.0"

# Lock for thread-safe background analysis
_ANALYSIS_LOCK = threading.Lock()
_IS_ANALYZING = False


# ── Main Entry Point ─────────────────────────────────────────────────────────

def run_anomaly_detection(
    db: Session,
    uploaded_file_ids: Optional[List[int]] = None,
    period_year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run anomaly detection on stored FinancialTBRecord rows.

    Args:
        db: SQLAlchemy session
        uploaded_file_ids: If provided, only analyze records from these files.
                           If None, analyze all processed tb_current records.
        period_year: If provided, restrict analysis to this year.

    Returns:
        Summary dict with counts by risk level and analysis run ID.
    """
    run_id = str(uuid.uuid4())[:8]
    logger.info(f"[Anomaly] Starting analysis run {run_id}")

    # ── Load records (optimized SQL query for fast DataFrame construction) ───
    sql = """
        SELECT
            r.id,
            r.uploaded_file_id,
            COALESCE(r.period_month, '') AS period_month,
            r.period_year,
            COALESCE(r.gl_code, '') AS gl_code,
            COALESCE(r.description, '') AS description,
            COALESCE(r.flexfield, '') AS flexfield,
            COALESCE(r.account, '') AS account,
            COALESCE(r.cost_center, '') AS cost_center,
            COALESCE(r.business_line, '') AS business_line,
            COALESCE(NULLIF(r.revenue_category, ''), 'Unmapped') AS revenue_category,
            COALESCE(r.sub_category, '') AS sub_category,
            COALESCE(r.period_activity, 0.0) AS period_activity,
            COALESCE(r.beginning_balance, 0.0) AS beginning_balance,
            COALESCE(r.ending_balance, 0.0) AS ending_balance
        FROM financial_tb_records r
        JOIN uploaded_finance_files f ON r.uploaded_file_id = f.id
        WHERE f.status = 'processed'
    """
    params = []
    if uploaded_file_ids:
        placeholders = ",".join(["?"] * len(uploaded_file_ids))
        sql += f" AND r.uploaded_file_id IN ({placeholders})"
        params.extend(uploaded_file_ids)

    if period_year:
        sql += " AND r.period_year = ?"
        params.append(period_year)

    import sqlite3
    db_file = Path("finance.db")
    if hasattr(db.bind, "url") and db.bind.url.database:
        db_file = Path(db.bind.url.database)

    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    df = pd.read_sql_query(sql, conn, params=params if params else None)
    conn.close()

    if df.empty:
        logger.warning(f"[Anomaly] No records found for analysis run {run_id}")
        return {
            "run_id": run_id,
            "total_analyzed": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "status": "no_data",
            "message": "No processed TB records found for anomaly detection.",
        }

    logger.info(f"[Anomaly] Loaded {len(df)} TB records for run {run_id}")

    # ── Compute scores ────────────────────────────────────────────────────────
    df = _compute_isolation_scores(df)
    df = _compute_z_scores(df)
    df = _compute_composite_score(df)
    df = _assign_risk_level(df)
    df = _build_risk_reasons(df)

    # ── Persist results ───────────────────────────────────────────────────────
    counts = _persist_results(db, df, run_id)
    logger.info(
        f"[Anomaly] Run {run_id} complete — "
        f"HIGH={counts['high']}, MEDIUM={counts['medium']}, LOW={counts['low']}"
    )

    return {
        "run_id": run_id,
        "total_analyzed": len(df),
        **counts,
        "status": "completed",
        "message": f"Analysis complete. {len(df)} records analyzed.",
    }


def trigger_background_anomaly_analysis(
    uploaded_file_ids: Optional[List[int]] = None,
    period_year: Optional[int] = None,
) -> None:
    """
    Triggers anomaly detection in a background thread (non-blocking).
    Safe to call from request handlers — will not block the API response.
    """
    global _IS_ANALYZING

    if _IS_ANALYZING:
        logger.info("[Anomaly] Background analysis already in progress — skipping trigger")
        return

    def _run():
        global _IS_ANALYZING
        with _ANALYSIS_LOCK:
            _IS_ANALYZING = True
            try:
                from app.database.connection import SessionLocal
                db = SessionLocal()
                try:
                    run_anomaly_detection(
                        db,
                        uploaded_file_ids=uploaded_file_ids,
                        period_year=period_year,
                    )
                finally:
                    db.close()
            except Exception as exc:
                logger.exception(f"[Anomaly] Background analysis failed: {exc}")
            finally:
                _IS_ANALYZING = False

    thread = threading.Thread(target=_run, daemon=True, name="anomaly-detection")
    thread.start()
    logger.info("[Anomaly] Background analysis thread started")


# ── Score Computation ─────────────────────────────────────────────────────────

def _compute_isolation_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Runs Isolation Forest on numeric TB features.
    Adds `isolation_score_raw` (0.0–1.0, higher = more anomalous).
    """
    if len(df) < MIN_RECORDS_FOR_IF:
        logger.warning(
            f"[Anomaly] Only {len(df)} records — too few for Isolation Forest. "
            "Assigning uniform isolation_score=0.0"
        )
        df["isolation_score_raw"] = 0.0
        return df

    # Encode categorical features numerically for Isolation Forest
    le_cat = LabelEncoder()
    le_bl = LabelEncoder()
    le_month = LabelEncoder()

    df["_cat_encoded"] = le_cat.fit_transform(df["revenue_category"].fillna("unknown"))
    df["_bl_encoded"] = le_bl.fit_transform(df["business_line"].fillna("unknown"))
    df["_month_encoded"] = le_month.fit_transform(df["period_month"].fillna("unknown"))

    # Derived feature: magnitude of change relative to beginning balance
    df["_abs_change_ratio"] = np.where(
        df["beginning_balance"].abs() > 1.0,
        (df["period_activity"].abs() / df["beginning_balance"].abs()).clip(0, 100),
        df["period_activity"].abs().clip(0, 1e9),
    )

    feature_cols = [
        "period_activity",
        "beginning_balance",
        "ending_balance",
        "_abs_change_ratio",
        "_cat_encoded",
        "_bl_encoded",
        "_month_encoded",
    ]

    X = df[feature_cols].fillna(0.0).values

    model = IsolationForest(
        n_estimators=100,
        contamination=CONTAMINATION,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X)

    # decision_function returns: negative = more anomalous, positive = more normal
    raw_scores = model.decision_function(X)

    # Normalize to 0–1 where 1 = most anomalous
    min_s, max_s = raw_scores.min(), raw_scores.max()
    if max_s > min_s:
        normalized = 1.0 - (raw_scores - min_s) / (max_s - min_s)
    else:
        normalized = np.zeros(len(raw_scores))

    df["isolation_score_raw"] = normalized

    # Cleanup temp columns
    df.drop(columns=["_cat_encoded", "_bl_encoded", "_month_encoded", "_abs_change_ratio"], inplace=True)

    return df


def _compute_z_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Vectorized per-group Z-scores for period_activity.
    Group = (revenue_category, period_month).
    """
    df = df.copy()

    # Compute group mean and std via pandas transform (vectorized)
    group_means = df.groupby(["revenue_category", "period_month"])["period_activity"].transform("mean")
    group_stds = df.groupby(["revenue_category", "period_month"])["period_activity"].transform("std").fillna(0.0)

    # Global mean and std fallback where group std is 0
    global_mean = df["period_activity"].mean()
    global_std = df["period_activity"].std()
    if global_std is None or global_std == 0:
        global_std = 1.0

    stds = np.where(group_stds > 0, group_stds, global_std)
    means = np.where(group_stds > 0, group_means, global_mean)

    df["z_score_raw"] = ((df["period_activity"] - means) / stds).abs().fillna(0.0)

    # Clip extreme z-scores and normalize 0–1
    z_clipped = df["z_score_raw"].clip(0, 10)
    z_min, z_max = z_clipped.min(), z_clipped.max()
    if z_max > z_min:
        df["z_score_normalized"] = (z_clipped - z_min) / (z_max - z_min)
    else:
        df["z_score_normalized"] = 0.0

    return df


def _compute_composite_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Combines isolation and z-score into a single composite anomaly score (0–1).
    Higher = more suspicious.
    """
    df["anomaly_score"] = (
        ISOLATION_WEIGHT * df["isolation_score_raw"]
        + ZSCORE_WEIGHT * df["z_score_normalized"]
    ).clip(0.0, 1.0)
    return df


def _assign_risk_level(df: pd.DataFrame) -> pd.DataFrame:
    """Assigns HIGH / MEDIUM / LOW risk labels based on composite score thresholds (vectorized)."""
    conditions = [
        df["anomaly_score"] >= RISK_HIGH_THRESHOLD,
        df["anomaly_score"] >= RISK_MEDIUM_THRESHOLD,
    ]
    choices = ["HIGH", "MEDIUM"]
    df["risk_level"] = np.select(conditions, choices, default="LOW")
    return df


def _build_risk_reasons(df: pd.DataFrame) -> pd.DataFrame:
    """
    Vectorized generation of human-readable explanations.
    """
    pa_95th = df["period_activity"].abs().quantile(0.95)

    z = df["z_score_raw"].values
    pa = df["period_activity"].values
    iso = df["isolation_score_raw"].values
    bb = df["beginning_balance"].values
    eb = df["ending_balance"].values
    pa_abs = np.abs(pa)

    reasons = []
    # Build reasons fast with list comprehension over tuples
    for z_val, pa_val, iso_val, bb_val, eb_val, pa_abs_val in zip(z, pa, iso, bb, eb, pa_abs):
        parts = []

        if z_val >= 3.0:
            direction = "higher" if pa_val > 0 else "lower"
            parts.append(f"Period activity ({pa_val:,.0f}) is {z_val:.1f} std deviations {direction} than historical average.")
        elif z_val >= 2.0:
            parts.append(f"Period activity ({pa_val:,.0f}) is moderately unusual ({z_val:.1f} std deviations from group average).")

        if iso_val >= 0.80:
            parts.append("Transaction pattern is structurally isolated from similar records (high Isolation Forest score).")
        elif iso_val >= 0.60:
            parts.append("Transaction shows a somewhat unusual pattern compared to peer records.")

        if bb_val != 0.0 and eb_val != 0.0 and ((bb_val > 0 and eb_val < 0) or (bb_val < 0 and eb_val > 0)):
            parts.append("Balance sign reversal detected: beginning and ending balances have opposite signs.")

        if pa_abs_val > pa_95th and pa_abs_val > 0:
            parts.append(f"Absolute transaction value ({pa_abs_val:,.0f}) is in the top 5% of analyzed transactions.")

        if not parts:
            parts.append("Standard transaction pattern — normal activity.")

        reasons.append(" ".join(parts))

    df["risk_reason"] = reasons
    return df


# ── Persistence ───────────────────────────────────────────────────────────────

def _persist_results(
    db: Session, df: pd.DataFrame, run_id: str
) -> Dict[str, int]:
    """
    Clears previous results and saves new results efficiently in batches.
    Returns counts by risk level.
    """
    counts = {"high": 0, "medium": 0, "low": 0}
    if df.empty:
        return counts

    try:
        # Calculate risk level counts
        level_counts = df["risk_level"].str.lower().value_counts().to_dict()
        counts["high"] = int(level_counts.get("high", 0))
        counts["medium"] = int(level_counts.get("medium", 0))
        counts["low"] = int(level_counts.get("low", 0))

        # Clear existing results safely without massive IN clause
        db.query(AnomalyDetectionResult).delete(synchronize_session=False)
        db.commit()

        now = datetime.datetime.utcnow()

        # Prepare dicts for bulk insertion
        records_to_insert = []
        for _, row in df.iterrows():
            records_to_insert.append({
                "tb_record_id": int(row["id"]),
                "uploaded_file_id": int(row["uploaded_file_id"]) if pd.notna(row["uploaded_file_id"]) else None,
                "period_month": str(row["period_month"]) if row["period_month"] else None,
                "period_year": int(row["period_year"]) if pd.notna(row["period_year"]) else None,
                "gl_code": str(row["gl_code"]) if row["gl_code"] else None,
                "description": str(row["description"]) if row["description"] else None,
                "flexfield": str(row["flexfield"]) if row["flexfield"] else None,
                "account": str(row["account"]) if row["account"] else None,
                "cost_center": str(row["cost_center"]) if row["cost_center"] else None,
                "business_line": str(row["business_line"]) if row["business_line"] else None,
                "revenue_category": str(row["revenue_category"]) if row["revenue_category"] else None,
                "sub_category": str(row["sub_category"]) if row["sub_category"] else None,
                "period_activity": float(row["period_activity"]),
                "beginning_balance": float(row["beginning_balance"]),
                "ending_balance": float(row["ending_balance"]),
                "anomaly_score": round(float(row["anomaly_score"]), 4),
                "isolation_score": round(float(row["isolation_score_raw"]), 4),
                "z_score": round(float(row["z_score_raw"]), 4),
                "risk_level": str(row["risk_level"]),
                "risk_reason": str(row["risk_reason"]),
                "detection_method": DETECTION_METHOD,
                "model_version": MODEL_VERSION,
                "analysis_run_id": run_id,
                "analyzed_at": now,
            })

        # Insert in chunks of 5000 records to keep memory lean and fast
        batch_size = 5000
        for i in range(0, len(records_to_insert), batch_size):
            batch = records_to_insert[i:i + batch_size]
            db.bulk_insert_mappings(AnomalyDetectionResult, batch)
            db.commit()

        logger.info(f"[Anomaly] Successfully persisted {len(records_to_insert)} results for run {run_id}")

    except Exception as exc:
        db.rollback()
        logger.exception(f"[Anomaly] Failed to persist results for run {run_id}: {exc}")
        raise

    return counts


# ── Query Helpers for API ─────────────────────────────────────────────────────

def get_anomaly_summary(db: Session) -> Dict[str, Any]:
    """Returns aggregate statistics for the most recent analysis run."""
    latest_run = (
        db.query(AnomalyDetectionResult.analysis_run_id)
        .order_by(AnomalyDetectionResult.analyzed_at.desc())
        .first()
    )

    if not latest_run:
        return {
            "total_analyzed": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "analysis_run_id": None,
            "last_analyzed_at": None,
            "has_data": False,
        }

    run_id = latest_run[0]

    counts = (
        db.query(
            AnomalyDetectionResult.risk_level,
            func.count(AnomalyDetectionResult.id).label("count"),
        )
        .filter(AnomalyDetectionResult.analysis_run_id == run_id)
        .group_by(AnomalyDetectionResult.risk_level)
        .all()
    )

    count_map = {row.risk_level: row.count for row in counts}
    total = sum(count_map.values())

    last_analyzed = (
        db.query(func.max(AnomalyDetectionResult.analyzed_at))
        .filter(AnomalyDetectionResult.analysis_run_id == run_id)
        .scalar()
    )

    # Category distribution for chart
    category_counts = (
        db.query(
            AnomalyDetectionResult.revenue_category,
            AnomalyDetectionResult.risk_level,
            func.count(AnomalyDetectionResult.id).label("count"),
        )
        .filter(
            AnomalyDetectionResult.analysis_run_id == run_id,
            AnomalyDetectionResult.risk_level.in_(["HIGH", "MEDIUM"]),
        )
        .group_by(AnomalyDetectionResult.revenue_category, AnomalyDetectionResult.risk_level)
        .order_by(func.count(AnomalyDetectionResult.id).desc())
        .limit(10)
        .all()
    )

    return {
        "total_analyzed": total,
        "high_count": count_map.get("HIGH", 0),
        "medium_count": count_map.get("MEDIUM", 0),
        "low_count": count_map.get("LOW", 0),
        "analysis_run_id": run_id,
        "last_analyzed_at": last_analyzed.isoformat() if last_analyzed else None,
        "has_data": total > 0,
        "category_distribution": [
            {
                "revenue_category": row.revenue_category or "Unmapped",
                "risk_level": row.risk_level,
                "count": row.count,
            }
            for row in category_counts
        ],
    }


def get_anomaly_results(
    db: Session,
    risk_level: Optional[str] = None,
    period_month: Optional[str] = None,
    revenue_category: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> Dict[str, Any]:
    """Returns paginated anomaly results with optional filters."""
    # Use the most recent run only
    latest_run = (
        db.query(AnomalyDetectionResult.analysis_run_id)
        .order_by(AnomalyDetectionResult.analyzed_at.desc())
        .first()
    )

    if not latest_run:
        return {"total": 0, "results": [], "has_data": False}

    run_id = latest_run[0]
    query = db.query(AnomalyDetectionResult).filter(
        AnomalyDetectionResult.analysis_run_id == run_id
    )

    if risk_level:
        query = query.filter(AnomalyDetectionResult.risk_level == risk_level.upper())

    if period_month:
        query = query.filter(AnomalyDetectionResult.period_month == period_month)

    if revenue_category:
        query = query.filter(AnomalyDetectionResult.revenue_category == revenue_category)

    if search:
        search_term = f"%{search}%"
        from sqlalchemy import or_
        query = query.filter(
            or_(
                AnomalyDetectionResult.gl_code.ilike(search_term),
                AnomalyDetectionResult.description.ilike(search_term),
                AnomalyDetectionResult.account.ilike(search_term),
                AnomalyDetectionResult.flexfield.ilike(search_term),
            )
        )

    total = query.count()
    results = (
        query.order_by(AnomalyDetectionResult.anomaly_score.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "has_data": True,
        "results": [
            {
                "id": r.id,
                "tb_record_id": r.tb_record_id,
                "period_month": r.period_month,
                "period_year": r.period_year,
                "gl_code": r.gl_code,
                "description": r.description,
                "account": r.account,
                "cost_center": r.cost_center,
                "business_line": r.business_line,
                "revenue_category": r.revenue_category,
                "sub_category": r.sub_category,
                "period_activity": r.period_activity,
                "beginning_balance": r.beginning_balance,
                "ending_balance": r.ending_balance,
                "anomaly_score": r.anomaly_score,
                "isolation_score": r.isolation_score,
                "z_score": r.z_score,
                "risk_level": r.risk_level,
                "risk_reason": r.risk_reason,
                "detection_method": r.detection_method,
                "analyzed_at": r.analyzed_at.isoformat() if r.analyzed_at else None,
            }
            for r in results
        ],
    }


def get_filter_options(db: Session) -> Dict[str, List[str]]:
    """Returns available filter values for the frontend dropdowns."""
    latest_run = (
        db.query(AnomalyDetectionResult.analysis_run_id)
        .order_by(AnomalyDetectionResult.analyzed_at.desc())
        .first()
    )

    if not latest_run:
        return {"months": [], "categories": []}

    run_id = latest_run[0]

    months = [
        r[0]
        for r in db.query(AnomalyDetectionResult.period_month)
        .filter(
            AnomalyDetectionResult.analysis_run_id == run_id,
            AnomalyDetectionResult.period_month.isnot(None),
        )
        .distinct()
        .all()
        if r[0]
    ]

    categories = [
        r[0]
        for r in db.query(AnomalyDetectionResult.revenue_category)
        .filter(
            AnomalyDetectionResult.analysis_run_id == run_id,
            AnomalyDetectionResult.revenue_category.isnot(None),
        )
        .distinct()
        .all()
        if r[0]
    ]

    return {
        "months": sorted(months),
        "categories": sorted(categories),
    }
