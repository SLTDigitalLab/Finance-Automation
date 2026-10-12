"""
Anomaly & Fraud Detection Service
===================================
Implements a hybrid Isolation Forest + Group Z-score approach to identify
potentially suspicious transactions in Trial Balance (TB) data.

NOTE: This service does NOT produce confirmed fraud classifications.
All outputs are anomaly scores and risk indicators for human review by
Finance Department staff.
"""
import datetime
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import LabelEncoder
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.user_and_log import (
    AnomalyDetectionResult,
    FinancialTBRecord,
    UploadedFinanceFile,
)
from config import settings

logger = logging.getLogger(__name__)

# ── Constants & Configuration ────────────────────────────────────────────────
CONTAMINATION = 0.05
ISOLATION_WEIGHT = 0.60
ZSCORE_WEIGHT = 0.40

RISK_HIGH_THRESHOLD = 0.70
RISK_MEDIUM_THRESHOLD = 0.40

MIN_RECORDS_FOR_IF = 10
DETECTION_METHOD = "hybrid_isolation_zscore"
MODEL_VERSION = "1.0.0"
OPERATING_YEAR = 2026

_ANALYSIS_LOCK = threading.Lock()
_IS_ANALYZING = False

MONTH_CALENDAR_ORDER = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}

# The standard 14 mapped revenue categories
STANDARD_14_CATEGORIES = [
    "Copper - Voice",
    "LTE - Voice",
    "FTTH - Voice",
    "Copper - BB (without Wi-Fi PP)",
    "Wi-Fi Prepaid Cards",
    "LTE - BB",
    "FTTH - BB",
    "PEO TV",
    "Enterprise (Corp. & Govt.)",
    "Carrier Domestic",
    "SME",
    "Micro Business",
    "RAM & Retail",
    "Digital Services",
]


# ── Core Anomaly Detection Pipeline ──────────────────────────────────────────

def run_anomaly_detection(
    db: Session,
    uploaded_file_ids: Optional[List[int]] = None,
    period_year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run hybrid anomaly detection on stored FinancialTBRecord rows.

    Args:
        db: SQLAlchemy session
        uploaded_file_ids: Optional list of file IDs to analyze. If None, analyzes all processed records.
        period_year: Optional year filter.

    Returns:
        Summary dict with counts by risk level and analysis run ID.
    """
    run_id = str(uuid.uuid4())[:8]
    logger.info(f"[Anomaly] Starting analysis run {run_id}")

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

    # 1. Isolation Forest
    df = _compute_isolation_scores(df)

    # 2. Group Z-scores
    df = _compute_z_scores(df)

    # 3. Composite score
    df = _compute_composite_score(df)

    # 4. Risk level classification
    df = _assign_risk_level(df)

    # 5. Explainability & Risk Reasons
    df = _build_risk_reasons(df)

    # 6. Persist results (preventing duplicates)
    counts = _persist_results(db, df, run_id, uploaded_file_ids)
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
    Triggers anomaly detection in a background daemon thread (non-blocking).
    Thread-safe to call from request handlers without delaying responses.
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

    thread = threading.Thread(target=_run, daemon=True, name="anomaly-detection-bg")
    thread.start()
    logger.info("[Anomaly] Background analysis thread started")


# ── Scoring Implementations ──────────────────────────────────────────────────

def _compute_isolation_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Runs Isolation Forest on numeric & categorical TB features.
    Adds `isolation_score_raw` (0.0–1.0, higher = more anomalous).
    """
    if len(df) < MIN_RECORDS_FOR_IF:
        df["isolation_score_raw"] = 0.0
        return df

    le_cat = LabelEncoder()
    le_bl = LabelEncoder()
    le_month = LabelEncoder()

    df["_cat_encoded"] = le_cat.fit_transform(df["revenue_category"].fillna("unknown"))
    df["_bl_encoded"] = le_bl.fit_transform(df["business_line"].fillna("unknown"))
    df["_month_encoded"] = le_month.fit_transform(df["period_month"].fillna("unknown"))

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

    raw_scores = model.decision_function(X)

    min_s, max_s = raw_scores.min(), raw_scores.max()
    if max_s > min_s:
        normalized = 1.0 - (raw_scores - min_s) / (max_s - min_s)
    else:
        normalized = np.zeros(len(raw_scores))

    df["isolation_score_raw"] = normalized
    df.drop(columns=["_cat_encoded", "_bl_encoded", "_month_encoded", "_abs_change_ratio"], inplace=True)
    return df


def _compute_z_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Vectorized per-group Z-scores for period_activity.
    Group = (revenue_category, period_month).
    """
    df = df.copy()

    group_means = df.groupby(["revenue_category", "period_month"])["period_activity"].transform("mean")
    group_stds = df.groupby(["revenue_category", "period_month"])["period_activity"].transform("std").fillna(0.0)

    global_mean = df["period_activity"].mean()
    global_std = df["period_activity"].std()
    if global_std is None or global_std == 0:
        global_std = 1.0

    stds = np.where(group_stds > 0, group_stds, global_std)
    means = np.where(group_stds > 0, group_means, global_mean)

    df["z_score_raw"] = ((df["period_activity"] - means) / stds).abs().fillna(0.0)

    z_clipped = df["z_score_raw"].clip(0, 10)
    z_min, z_max = z_clipped.min(), z_clipped.max()
    if z_max > z_min:
        df["z_score_normalized"] = (z_clipped - z_min) / (z_max - z_min)
    else:
        df["z_score_normalized"] = 0.0

    return df


def _compute_composite_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Combines Isolation Forest score and Z-Score into composite anomaly score (0.0 to 1.0).
    """
    df["anomaly_score"] = (
        ISOLATION_WEIGHT * df["isolation_score_raw"]
        + ZSCORE_WEIGHT * df["z_score_normalized"]
    ).clip(0.0, 1.0)
    return df


def _assign_risk_level(df: pd.DataFrame) -> pd.DataFrame:
    """Assigns HIGH / MEDIUM / LOW risk labels based on composite score thresholds."""
    conditions = [
        df["anomaly_score"] >= RISK_HIGH_THRESHOLD,
        df["anomaly_score"] >= RISK_MEDIUM_THRESHOLD,
    ]
    choices = ["HIGH", "MEDIUM"]
    df["risk_level"] = np.select(conditions, choices, default="LOW")
    return df


def _build_risk_reasons(df: pd.DataFrame) -> pd.DataFrame:
    """Generates informative explanations for flagged records."""
    pa_95th = df["period_activity"].abs().quantile(0.95)

    z = df["z_score_raw"].values
    pa = df["period_activity"].values
    iso = df["isolation_score_raw"].values
    bb = df["beginning_balance"].values
    eb = df["ending_balance"].values
    pa_abs = np.abs(pa)

    reasons = []
    for z_val, pa_val, iso_val, bb_val, eb_val, pa_abs_val in zip(z, pa, iso, bb, eb, pa_abs):
        parts = []

        if z_val >= 3.0:
            direction = "higher" if pa_val > 0 else "lower"
            parts.append(f"Period activity ({pa_val:,.0f}) is {z_val:.1f} std deviations {direction} than historical group average.")
        elif z_val >= 2.0:
            parts.append(f"Period activity ({pa_val:,.0f}) is moderately unusual ({z_val:.1f} std deviations from group average).")

        if iso_val >= 0.80:
            parts.append("Transaction pattern is structurally isolated from similar records (high Isolation Forest score).")
        elif iso_val >= 0.60:
            parts.append("Transaction shows a somewhat unusual pattern compared to peer records.")

        if bb_val != 0.0 and eb_val != 0.0 and ((bb_val > 0 and eb_val < 0) or (bb_val < 0 and eb_val > 0)):
            parts.append("Balance sign reversal detected between beginning and ending balances.")

        if pa_abs_val > pa_95th and pa_abs_val > 0:
            parts.append(f"Absolute transaction value ({pa_abs_val:,.0f}) is in the top 5% of analyzed transactions.")

        if not parts:
            parts.append("Standard transaction pattern — normal activity.")

        reasons.append(" ".join(parts))

    df["risk_reason"] = reasons
    return df


def _persist_results(
    db: Session,
    df: pd.DataFrame,
    run_id: str,
    uploaded_file_ids: Optional[List[int]] = None,
) -> Dict[str, int]:
    """
    Persists computed anomaly results efficiently.
    Prevents duplicates by deleting previous records for the analyzed scope before insertion.
    """
    counts = {"high": 0, "medium": 0, "low": 0}
    if df.empty:
        return counts

    try:
        level_counts = df["risk_level"].str.lower().value_counts().to_dict()
        counts["high"] = int(level_counts.get("high", 0))
        counts["medium"] = int(level_counts.get("medium", 0))
        counts["low"] = int(level_counts.get("low", 0))

        if uploaded_file_ids:
            # Incremental update: delete existing records for these uploaded files only
            db.query(AnomalyDetectionResult).filter(
                AnomalyDetectionResult.uploaded_file_id.in_(uploaded_file_ids)
            ).delete(synchronize_session=False)
        else:
            # Full refresh: clear table to avoid duplicate records across runs
            db.query(AnomalyDetectionResult).delete(synchronize_session=False)
        db.commit()

        now = datetime.datetime.utcnow()
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


# ── Query & Aggregation Helpers for Frontend Dashboard ───────────────────────

def get_category_month_matrix(
    db: Session,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Computes the Category × Month anomaly indicator matrix for Operating Year 2026.
    Returns aggregated status, risk counts, max anomaly scores, and reasons per cell.
    """
    selected_year = OPERATING_YEAR

    # 1. Determine dynamically available months for Operating Year 2026 (in calendar order)
    raw_months = [
        r[0]
        for r in db.query(AnomalyDetectionResult.period_month)
        .filter(
            AnomalyDetectionResult.period_year == selected_year,
            AnomalyDetectionResult.period_month.isnot(None),
            AnomalyDetectionResult.period_month != "",
        )
        .distinct()
        .all()
    ]

    months = sorted(raw_months, key=lambda m: MONTH_CALENDAR_ORDER.get(m, 99))

    # 2. Determine all categories present in 2026 data, ensuring standard 14 are top
    db_categories = [
        r[0]
        for r in db.query(AnomalyDetectionResult.revenue_category)
        .filter(
            AnomalyDetectionResult.period_year == selected_year,
            AnomalyDetectionResult.revenue_category.isnot(None),
        )
        .distinct()
        .all()
    ]

    # Assemble complete ordered categories list
    categories = []
    for cat in STANDARD_14_CATEGORIES:
        categories.append(cat)
    for cat in db_categories:
        if cat and cat not in categories:
            categories.append(cat)

    # 3. Fast aggregated SQL query for the matrix cells for Operating Year 2026
    sql = """
        SELECT
            period_month,
            COALESCE(NULLIF(revenue_category, ''), 'Unmapped') AS category,
            COUNT(id) AS total_records,
            SUM(CASE WHEN risk_level = 'HIGH' THEN 1 ELSE 0 END) AS high_risk_count,
            SUM(CASE WHEN risk_level = 'MEDIUM' THEN 1 ELSE 0 END) AS medium_risk_count,
            SUM(CASE WHEN risk_level = 'LOW' THEN 1 ELSE 0 END) AS low_risk_count,
            MAX(anomaly_score) AS max_anomaly_score,
            AVG(anomaly_score) AS avg_anomaly_score
        FROM anomaly_detection_results
        WHERE period_year = :year
        GROUP BY period_month, COALESCE(NULLIF(revenue_category, ''), 'Unmapped')
    """
    result_rows = db.execute(text(sql), {"year": selected_year}).fetchall()

    # Build lookup table for matrix cells
    cell_data_map = {}
    for row in result_rows:
        month = row[0]
        cat = row[1]
        key = f"{cat}__{month}"
        cell_data_map[key] = {
            "month": month,
            "category": cat,
            "total_records": int(row[2] or 0),
            "high_risk_count": int(row[3] or 0),
            "medium_risk_count": int(row[4] or 0),
            "low_risk_count": int(row[5] or 0),
            "max_anomaly_score": round(float(row[6] or 0.0), 4),
            "avg_anomaly_score": round(float(row[7] or 0.0), 4),
        }

    # Fetch top sample risk reason for cells with anomalies
    reasons_sql = """
        SELECT
            period_month,
            COALESCE(NULLIF(revenue_category, ''), 'Unmapped') AS category,
            risk_reason
        FROM anomaly_detection_results
        WHERE period_year = :year AND risk_level IN ('HIGH', 'MEDIUM')
        GROUP BY period_month, COALESCE(NULLIF(revenue_category, ''), 'Unmapped')
    """
    reason_rows = db.execute(text(reasons_sql), {"year": selected_year}).fetchall()
    reasons_map = {f"{r[1]}__{r[0]}": r[2] for r in reason_rows}

    # Assemble full matrix grid
    matrix = {}
    category_summaries = {}

    for cat in categories:
        cat_high_total = 0
        cat_med_total = 0
        cat_records_total = 0

        for month in months:
            cell_key = f"{cat}__{month}"
            cell = cell_data_map.get(cell_key)

            if cell and cell["total_records"] > 0:
                high_c = cell["high_risk_count"]
                med_c = cell["medium_risk_count"]
                cat_high_total += high_c
                cat_med_total += med_c
                cat_records_total += cell["total_records"]

                if high_c > 0:
                    status_indicator = "HIGH"
                    color = "red"
                elif med_c > 0:
                    status_indicator = "MEDIUM"
                    color = "yellow"
                else:
                    status_indicator = "NORMAL"
                    color = "green"

                reason = reasons_map.get(cell_key, "Standard transaction pattern — normal activity.")
                matrix[cell_key] = {
                    "category": cat,
                    "month": month,
                    "year": selected_year,
                    "status": status_indicator,
                    "color": color,
                    "total_records": cell["total_records"],
                    "high_risk_count": high_c,
                    "medium_risk_count": med_c,
                    "low_risk_count": cell["low_risk_count"],
                    "max_anomaly_score": cell["max_anomaly_score"],
                    "avg_anomaly_score": cell["avg_anomaly_score"],
                    "primary_risk_reason": reason,
                }
            else:
                matrix[cell_key] = {
                    "category": cat,
                    "month": month,
                    "year": selected_year,
                    "status": "NO_DATA",
                    "color": "gray",
                    "total_records": 0,
                    "high_risk_count": 0,
                    "medium_risk_count": 0,
                    "low_risk_count": 0,
                    "max_anomaly_score": 0.0,
                    "avg_anomaly_score": 0.0,
                    "primary_risk_reason": "No data uploaded for this category and month.",
                }

        category_summaries[cat] = {
            "total_records": cat_records_total,
            "total_high_risk": cat_high_total,
            "total_medium_risk": cat_med_total,
            "overall_status": "HIGH" if cat_high_total > 0 else ("MEDIUM" if cat_med_total > 0 else "NORMAL"),
        }

    return {
        "years": [OPERATING_YEAR],
        "selected_year": selected_year,
        "months": months,
        "categories": categories,
        "matrix": matrix,
        "category_summaries": category_summaries,
        "has_data": len(matrix) > 0,
    }


def get_anomaly_summary(
    db: Session,
    year: Optional[int] = None,
    period_month: Optional[str] = None,
    revenue_category: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns aggregate summary KPIs and latest month stats strictly for Operating Year 2026."""
    target_year = year if year == OPERATING_YEAR else OPERATING_YEAR
    query = db.query(AnomalyDetectionResult).filter(AnomalyDetectionResult.period_year == target_year)

    if period_month:
        query = query.filter(AnomalyDetectionResult.period_month == period_month)
    if revenue_category:
        query = query.filter(AnomalyDetectionResult.revenue_category == revenue_category)

    counts = (
        query.with_entities(
            AnomalyDetectionResult.risk_level,
            func.count(AnomalyDetectionResult.id).label("count"),
        )
        .group_by(AnomalyDetectionResult.risk_level)
        .all()
    )

    count_map = {row.risk_level.upper() if row.risk_level else "LOW": row.count for row in counts}
    total = sum(count_map.values())

    last_analyzed = (
        db.query(func.max(AnomalyDetectionResult.analyzed_at))
        .filter(AnomalyDetectionResult.period_year == target_year)
        .scalar()
    )

    # Latest month statistics for Operating Year 2026
    latest_file = (
        db.query(UploadedFinanceFile)
        .filter(
            UploadedFinanceFile.status == "processed",
            UploadedFinanceFile.file_type == "tb_current",
            UploadedFinanceFile.period_year == target_year,
        )
        .order_by(UploadedFinanceFile.uploaded_at.desc())
        .first()
    )

    latest_month_str = f"August {target_year}"
    latest_month_high = 0
    latest_month_total = 0
    if latest_file and latest_file.period_month:
        latest_month_str = f"{latest_file.period_month} {target_year}"
        lm_counts = (
            db.query(
                AnomalyDetectionResult.risk_level,
                func.count(AnomalyDetectionResult.id),
            )
            .filter(
                AnomalyDetectionResult.period_month == latest_file.period_month,
                AnomalyDetectionResult.period_year == target_year,
            )
            .group_by(AnomalyDetectionResult.risk_level)
            .all()
        )
        lm_map = {r[0].upper() if r[0] else "LOW": r[1] for r in lm_counts}
        latest_month_high = lm_map.get("HIGH", 0)
        latest_month_total = sum(lm_map.values())

    return {
        "total_analyzed": total,
        "high_count": count_map.get("HIGH", 0),
        "medium_count": count_map.get("MEDIUM", 0),
        "low_count": count_map.get("LOW", 0),
        "latest_month": latest_month_str,
        "latest_month_high_count": latest_month_high,
        "latest_month_total_count": latest_month_total,
        "last_analyzed_at": last_analyzed.isoformat() if last_analyzed else None,
        "detection_method": "Hybrid Isolation Forest + Z-Score (v1.0.0)",
        "model_version": MODEL_VERSION,
        "has_data": total > 0,
    }


def get_anomaly_results(
    db: Session,
    year: Optional[int] = None,
    risk_level: Optional[str] = None,
    period_month: Optional[str] = None,
    revenue_category: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    sort_by: str = "anomaly_score",
    sort_order: str = "desc",
) -> Dict[str, Any]:
    """Returns paginated anomaly records strictly for Operating Year 2026."""
    target_year = year if year == OPERATING_YEAR else OPERATING_YEAR
    query = db.query(AnomalyDetectionResult).filter(AnomalyDetectionResult.period_year == target_year)

    if risk_level:
        query = query.filter(AnomalyDetectionResult.risk_level == risk_level.upper())

    if period_month:
        query = query.filter(AnomalyDetectionResult.period_month == period_month)

    if revenue_category:
        if revenue_category.lower() == "unmapped":
            query = query.filter(
                (AnomalyDetectionResult.revenue_category.is_(None))
                | (AnomalyDetectionResult.revenue_category == "")
                | (AnomalyDetectionResult.revenue_category == "Unmapped")
            )
        else:
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
                AnomalyDetectionResult.cost_center.ilike(search_term),
                AnomalyDetectionResult.business_line.ilike(search_term),
            )
        )

    total = query.count()

    # Dynamic sorting
    sort_col = getattr(AnomalyDetectionResult, sort_by, AnomalyDetectionResult.anomaly_score)
    if sort_order.lower() == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    results = query.offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_data": total > 0,
        "results": [
            {
                "id": r.id,
                "tb_record_id": r.tb_record_id,
                "uploaded_file_id": r.uploaded_file_id,
                "period_month": r.period_month,
                "period_year": r.period_year,
                "gl_code": r.gl_code or "—",
                "description": r.description or "—",
                "account": r.account or "—",
                "flexfield": r.flexfield or "—",
                "cost_center": r.cost_center or "—",
                "business_line": r.business_line or "—",
                "revenue_category": r.revenue_category or "Unmapped",
                "sub_category": r.sub_category or "—",
                "period_activity": r.period_activity or 0.0,
                "beginning_balance": r.beginning_balance or 0.0,
                "ending_balance": r.ending_balance or 0.0,
                "anomaly_score": r.anomaly_score or 0.0,
                "isolation_score": r.isolation_score or 0.0,
                "z_score": r.z_score or 0.0,
                "risk_level": r.risk_level or "LOW",
                "risk_reason": r.risk_reason or "Normal activity.",
                "detection_method": r.detection_method or DETECTION_METHOD,
                "analyzed_at": r.analyzed_at.isoformat() if r.analyzed_at else None,
            }
            for r in results
        ],
    }


def get_filter_options(db: Session) -> Dict[str, Any]:
    """Returns dynamically available filter choices strictly for Operating Year 2026."""
    months_raw = [
        r[0]
        for r in db.query(AnomalyDetectionResult.period_month)
        .filter(
            AnomalyDetectionResult.period_year == OPERATING_YEAR,
            AnomalyDetectionResult.period_month.isnot(None),
            AnomalyDetectionResult.period_month != "",
        )
        .distinct()
        .all()
    ]
    months = sorted(months_raw, key=lambda m: MONTH_CALENDAR_ORDER.get(m, 99))

    categories = list(STANDARD_14_CATEGORIES)
    other_cats = [
        r[0]
        for r in db.query(AnomalyDetectionResult.revenue_category)
        .filter(
            AnomalyDetectionResult.period_year == OPERATING_YEAR,
            AnomalyDetectionResult.revenue_category.isnot(None),
        )
        .distinct()
        .all()
        if r[0] and r[0] not in categories
    ]
    categories.extend(other_cats)

    return {
        "years": [OPERATING_YEAR],
        "months": months,
        "categories": categories,
        "risk_levels": ["HIGH", "MEDIUM", "LOW"],
    }
