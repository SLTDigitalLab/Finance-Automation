import datetime
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

logger = logging.getLogger(__name__)

# Base directory paths
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "finance.db"
MODELS_DIR = BASE_DIR / "ai" / "models"
BACKUPS_DIR = MODELS_DIR / "backups"
ACTIVE_MODEL_PATH = MODELS_DIR / "revenue_forecasting_model.joblib"
METADATA_PATH = MODELS_DIR / "revenue_forecasting_model_metadata.json"
CANDIDATE_MODEL_PATH = MODELS_DIR / "revenue_forecasting_model_candidate.joblib"

MODELS_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

# Lock for thread safety during background retraining
_RETRAINING_LOCK = threading.Lock()
_IS_RETRAINING = False

MONTH_ORDER = {
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
MONTH_NAMES = {v: k for k, v in MONTH_ORDER.items()}


def get_current_year() -> int:
    """Returns the primary operating current year from database or system year."""
    try:
        if DB_PATH.exists():
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT max(period_year) 
                FROM uploaded_finance_files 
                WHERE file_type = 'tb_current' AND status = 'processed';
            """)
            res = cursor.fetchone()
            conn.close()
            if res and res[0]:
                return int(res[0])
    except Exception as e:
        logger.warning(f"Could not query max period_year from DB: {e}")
    return datetime.datetime.now().year


def query_real_current_year_training_data(
    db_path: Path = DB_PATH,
    current_year: Optional[int] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Dynamically queries all processed real tb_current financial records for the current year.
    Takes the latest uploaded and processed file for each month.
    Strictly excludes tb_previous, superseded seed files, and unmapped rows.
    """
    if current_year is None:
        current_year = get_current_year()

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    
    # 1. Discover latest eligible processed current-year file for each month
    query_files = """
        SELECT f.id, f.original_filename, f.period_month, f.period_year, f.status, f.uploaded_at
        FROM uploaded_finance_files f
        WHERE f.file_type = 'tb_current'
          AND f.period_year = ?
          AND f.status = 'processed'
          AND f.id = (
              SELECT max(f2.id)
              FROM uploaded_finance_files f2
              WHERE f2.file_type = 'tb_current'
                AND f2.period_year = f.period_year
                AND f2.period_month = f.period_month
                AND f2.status = 'processed'
          )
        ORDER BY f.id ASC;
    """
    files_df = pd.read_sql_query(query_files, conn, params=(current_year,))
    
    if files_df.empty:
        conn.close()
        raise ValueError(f"No processed real current-year tb_current files found in database for year {current_year}.")

    file_ids = tuple(files_df["id"].tolist())
    placeholders = ",".join(["?"] * len(file_ids))

    # 2. Query mapped financial records belonging to these files
    query_records = f"""
        SELECT 
            uploaded_file_id,
            period_year,
            period_month,
            revenue_category,
            period_activity
        FROM financial_tb_records
        WHERE uploaded_file_id IN ({placeholders})
          AND revenue_category IS NOT NULL
          AND trim(revenue_category) != '';
    """
    records_df = pd.read_sql_query(query_records, conn, params=file_ids)
    conn.close()

    if records_df.empty:
        raise ValueError(f"No mapped financial records found for file IDs: {file_ids}")

    sorted_months = sorted(records_df["period_month"].unique(), key=lambda m: MONTH_ORDER.get(m, 99))
    data_summary = {
        "current_year": current_year,
        "eligible_file_ids": list(file_ids),
        "source_files": files_df["original_filename"].tolist(),
        "total_source_records": len(records_df),
        "months_present": sorted_months,
    }
    return records_df, data_summary


def prepare_training_features(raw_df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str], List[str], List[str]]:
    """
    Aggregates financial records and prepares chronological time-series lag features.
    Revenue sign convention: -sum(period_activity) / 1,000,000.0 (in millions LKR).
    """
    df = raw_df.copy()
    df["revenue"] = -df["period_activity"].astype(float) / 1_000_000.0

    # Aggregate by category and month
    monthly_df = (
        df.groupby(["revenue_category", "period_month", "period_year"], as_index=False)["revenue"]
        .sum()
        .rename(columns={"revenue": "current_revenue"})
    )
    monthly_df["month_number"] = monthly_df["period_month"].map(MONTH_ORDER)
    monthly_df["time_index"] = monthly_df["month_number"] - 1
    monthly_df = monthly_df.sort_values(["revenue_category", "month_number"]).reset_index(drop=True)

    # Compute 1-month lag of current year actual revenue
    monthly_df["current_revenue_lag_1"] = monthly_df.groupby("revenue_category")["current_revenue"].shift(1)

    # Drop rows where lag_1 is NaN (Month 1 serves as lag feature for Month 2)
    model_data = monthly_df.dropna(subset=["current_revenue_lag_1"]).reset_index(drop=True)

    feature_columns = [
        "revenue_category",
        "month_number",
        "time_index",
        "current_revenue_lag_1",
    ]
    categorical_features = ["revenue_category"]
    numeric_features = ["month_number", "time_index", "current_revenue_lag_1"]

    return model_data, feature_columns, categorical_features, numeric_features


def train_and_validate_model(
    db_path: Path = DB_PATH,
    current_year: Optional[int] = None
) -> Dict[str, Any]:
    """
    Core ML training logic:
    1. Extracts real current-year records from DB.
    2. Builds features.
    3. Performs chronological train/test split.
    4. Fits RandomForestRegressor pipeline.
    5. Calculates evaluation metrics (MAE, RMSE, R²).
    6. Saves candidate artifact and validates it.
    7. Atomically promotes candidate to active model with backup.
    8. Updates metadata JSON.
    """
    start_time = time.time()
    start_iso = datetime.datetime.utcnow().isoformat() + "Z"

    records_df, data_summary = query_real_current_year_training_data(db_path, current_year)
    model_data, feature_columns, categorical_features, numeric_features = prepare_training_features(records_df)

    if len(model_data) < 14:
        raise ValueError(f"Insufficient training samples ({len(model_data)}). Need at least 2 consecutive months of data.")

    # Chronological Split: hold out latest month for testing if >= 2 modeling months available
    available_months = sorted(model_data["month_number"].unique())
    latest_month_num = max(available_months)

    if len(available_months) >= 2:
        train_data = model_data[model_data["month_number"] < latest_month_num].copy()
        test_data = model_data[model_data["month_number"] == latest_month_num].copy()
        test_month_name = MONTH_NAMES.get(latest_month_num, f"Month {latest_month_num}")
    else:
        train_data = model_data.copy()
        test_data = model_data.copy()
        test_month_name = "Self (Single period)"

    X_train = train_data[feature_columns]
    y_train = train_data["current_revenue"]
    X_test = test_data[feature_columns]
    y_test = test_data["current_revenue"]

    # Build Pipeline
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "category",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical_features,
            ),
            ("numeric", SimpleImputer(strategy="median"), numeric_features),
        ]
    )

    model = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            (
                "regressor",
                RandomForestRegressor(
                    n_estimators=300,
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    model.fit(X_train, y_train)

    # Evaluate
    test_preds = model.predict(X_test)
    mae = float(mean_absolute_error(y_test, test_preds))
    rmse = float(np.sqrt(mean_squared_error(y_test, test_preds)))
    if len(y_test) >= 2 and y_test.nunique() >= 2:
        r2 = float(r2_score(y_test, test_preds))
    else:
        r2 = 1.0

    categories = sorted(model_data["revenue_category"].unique())
    training_period_str = f"{data_summary['months_present'][0]} {data_summary['current_year']} – {data_summary['months_present'][-1]} {data_summary['current_year']}"

    # Construct Artifact
    candidate_artifact = {
        "model": model,
        "feature_columns": feature_columns,
        "categorical_features": categorical_features,
        "numeric_features": numeric_features,
        "category_values": categories,
        "training_period_end": f"{data_summary['current_year']}-{latest_month_num:02d}-01",
        "target_column": "current_revenue",
        "tb_to_mn_divisor": 1_000_000,
        "revenue_sign_convention": "-period_activity / 1_000_000",
        "evaluation": {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "r2": round(r2, 4),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "test_period": f"{test_month_name} {data_summary['current_year']}",
        },
        "metadata": {
            "model_name": "RandomForestRegressor",
            "purpose": "production real-data revenue forecasting",
            "current_year": data_summary["current_year"],
            "training_period": training_period_str,
            "training_months": f"{data_summary['months_present'][0]}–{data_summary['months_present'][-1]} {data_summary['current_year']}",
            "testing_month": f"{test_month_name} {data_summary['current_year']}",
            "data_source": "Real Current-Year TB Data",
            "source_files": data_summary["source_files"],
            "source_file_ids": data_summary["eligible_file_ids"],
            "features_used": feature_columns,
            "has_previous_year_data": False,
            "last_trained": start_iso,
        },
    }

    # Step 1: Save Candidate Artifact
    joblib.dump(candidate_artifact, CANDIDATE_MODEL_PATH)
    logger.info(f"Saved candidate model to {CANDIDATE_MODEL_PATH}")

    # Step 2: Validate Candidate Artifact
    loaded_candidate = joblib.load(CANDIDATE_MODEL_PATH)
    val_pred = loaded_candidate["model"].predict(X_test.head(1))
    if not np.all(np.isfinite(val_pred)):
        raise ValueError("Candidate model validation failed: non-finite prediction generated.")
    if loaded_candidate["feature_columns"] != feature_columns:
        raise ValueError("Candidate model validation failed: feature columns mismatch.")

    # Step 3: Atomic Promotion with Backup
    timestamp_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    if ACTIVE_MODEL_PATH.exists():
        backup_file = BACKUPS_DIR / f"revenue_forecasting_model_backup_{timestamp_str}.joblib"
        shutil.copy2(ACTIVE_MODEL_PATH, backup_file)
        logger.info(f"Created active model backup at: {backup_file}")

    # Atomically replace active model with candidate
    shutil.copy2(CANDIDATE_MODEL_PATH, ACTIVE_MODEL_PATH)
    if CANDIDATE_MODEL_PATH.exists():
        try:
            CANDIDATE_MODEL_PATH.unlink()
        except Exception:
            pass

    # Save metadata JSON file for easy inspection & API consumption
    metadata_json = {
        "status": "Active",
        "model_name": "RandomForestRegressor",
        "data_source": "Real Current-Year TB Data",
        "current_year": data_summary["current_year"],
        "training_period": training_period_str,
        "training_samples": len(X_train),
        "testing_samples": len(X_test),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "last_trained": start_iso,
        "features_used": feature_columns,
        "source_file_ids": data_summary["eligible_file_ids"],
        "source_files": data_summary["source_files"],
        "duration_seconds": round(time.time() - start_time, 2),
    }

    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata_json, f, indent=2)

    logger.info(f"Model retraining successfully completed in {metadata_json['duration_seconds']}s. MAE={mae:.4f}, RMSE={rmse:.4f}, R2={r2:.4f}")
    return metadata_json


def retrain_model_task():
    """Thread execution wrapper with thread lock to ensure singleton retraining."""
    global _IS_RETRAINING
    if not _RETRAINING_LOCK.acquire(blocking=False):
        logger.warning("Retraining job is already running. Skipping concurrent trigger.")
        return

    _IS_RETRAINING = True
    try:
        logger.info("Starting background automatic model retraining...")
        result = train_and_validate_model()
        logger.info(f"Background automatic retraining succeeded: {result}")
    except Exception as e:
        logger.exception(f"Background automatic model retraining failed: {e}")
    finally:
        _IS_RETRAINING = False
        _RETRAINING_LOCK.release()


def trigger_background_retraining():
    """Non-blocking invocation of model retraining in a background daemon thread."""
    thread = threading.Thread(target=retrain_model_task, daemon=True, name="ModelRetrainingWorker")
    thread.start()
    logger.info("Triggered model retraining background thread.")
