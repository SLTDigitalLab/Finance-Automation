"""
Migration service for User-Specific File Upload Privacy and Access Control.
Performs idempotent database schema upgrades and file migrations so that
previously uploaded files are safely associated with their legitimate uploaders.
"""
import json
import logging
import shutil
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings

logger = logging.getLogger(__name__)


def run_privacy_migration(engine, SessionLocal):
    """
    Executes idempotent migrations:
    1. Schema updates for report_jobs and fa_trial_balances.
    2. Data backfills for report_jobs.user_id.
    3. Storage directory migration for pre-existing files to user-scoped directories.
    """
    with engine.connect() as conn:
        # 1. Add user_id column to report_jobs if missing
        rj_check = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='report_jobs'")
        ).fetchone()
        if rj_check:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(report_jobs)"))]
            if "user_id" not in cols:
                conn.execute(text("ALTER TABLE report_jobs ADD COLUMN user_id INTEGER"))
                conn.commit()
                logger.info("Added user_id column to report_jobs table")

        # 2. Update fa_trial_balances unique constraint if still on (period_year, period_month)
        tb_check = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='fa_trial_balances'")
        ).fetchone()
        if tb_check and "uq_fa_trial_balances_period" in tb_check[0]:
            try:
                conn.execute(text("PRAGMA foreign_keys=OFF"))
                conn.execute(text("""
                    CREATE TABLE fa_trial_balances_new (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        period_year INTEGER NOT NULL,
                        period_month INTEGER NOT NULL,
                        source_filename VARCHAR,
                        row_count INTEGER NOT NULL,
                        account_count INTEGER NOT NULL,
                        net_ytd FLOAT NOT NULL,
                        uploaded_by INTEGER,
                        uploaded_at DATETIME,
                        CONSTRAINT uq_fa_trial_balances_user_period UNIQUE (uploaded_by, period_year, period_month),
                        FOREIGN KEY(uploaded_by) REFERENCES users (id)
                    )
                """))
                conn.execute(text("""
                    INSERT INTO fa_trial_balances_new (id, period_year, period_month, source_filename, row_count, account_count, net_ytd, uploaded_by, uploaded_at)
                    SELECT id, period_year, period_month, source_filename, row_count, account_count, net_ytd, uploaded_by, uploaded_at
                    FROM fa_trial_balances
                """))
                conn.execute(text("DROP TABLE fa_trial_balances"))
                conn.execute(text("ALTER TABLE fa_trial_balances_new RENAME TO fa_trial_balances"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fa_trial_balances_id ON fa_trial_balances (id)"))
                conn.execute(text("PRAGMA foreign_keys=ON"))
                conn.commit()
                logger.info("Migrated fa_trial_balances to user-scoped unique constraint")
            except Exception as e:
                logger.error(f"Failed to migrate fa_trial_balances constraint: {e}")

    # Backfill report_jobs.user_id from uploaded_finance_files
    db: Session = SessionLocal()
    try:
        from app.models.user_and_log import ReportJob, UploadedFinanceFile, User
        unlinked_jobs = db.query(ReportJob).filter(ReportJob.user_id.is_(None)).all()
        for job in unlinked_jobs:
            clean_session = job.session_id.replace("unmapped_", "")
            file_match = db.query(UploadedFinanceFile).filter(UploadedFinanceFile.session_id == clean_session).first()
            if file_match and file_match.user_id:
                job.user_id = file_match.user_id
        db.commit()

        # Build name/email to user_id lookup map
        users = db.query(User).all()
        user_lookup = {}
        for u in users:
            if u.full_name:
                user_lookup[u.full_name.strip().lower()] = u.id
            if u.email:
                user_lookup[u.email.strip().lower()] = u.id

        _migrate_disk_files(user_lookup)
    except Exception as exc:
        logger.error(f"Error during privacy migration: {exc}")
    finally:
        db.close()


def _migrate_disk_files(user_lookup: dict):
    """Migrates legacy shared folders to user-specific folders."""
    # 1. Accrual Entry Report
    accrual_dir = settings.BASE_DIR / "uploads" / "accrual_entry_report"
    if accrual_dir.exists():
        for item in list(accrual_dir.iterdir()):
            if item.is_dir() and not item.name.isdigit():
                meta_file = item / "metadata.json"
                target_user_id = None
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        for cat_info in meta.values():
                            if isinstance(cat_info, dict) and cat_info.get("uploaded_by"):
                                uploader = cat_info["uploaded_by"].strip().lower()
                                if uploader in user_lookup:
                                    target_user_id = user_lookup[uploader]
                                    break
                    except Exception:
                        pass
                if target_user_id:
                    user_folder = accrual_dir / str(target_user_id) / item.name
                    user_folder.parent.mkdir(parents=True, exist_ok=True)
                    if not user_folder.exists():
                        shutil.move(str(item), str(user_folder))
                        logger.info(f"Migrated legacy accrual folder {item.name} -> {user_folder}")

    # 2. CIP Reconciliation
    cip_dir = settings.BASE_DIR / "uploads" / "cip_reconciliation"
    meta_file = cip_dir / "metadata.json"
    if meta_file.exists():
        target_user_id = None
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            for period_files in meta.get("files", {}).values():
                for cat_info in period_files.values():
                    if isinstance(cat_info, dict) and cat_info.get("uploaded_by"):
                        uploader = cat_info["uploaded_by"].strip().lower()
                        if uploader in user_lookup:
                            target_user_id = user_lookup[uploader]
                            break
                if target_user_id:
                    break
        except Exception:
            pass

        # If files exist or metadata exists, move to target user
        if target_user_id:
            user_cip_dir = cip_dir / str(target_user_id)
            user_cip_dir.mkdir(parents=True, exist_ok=True)
            for item in list(cip_dir.iterdir()):
                if item.name != str(target_user_id) and not item.name.isdigit():
                    dest = user_cip_dir / item.name
                    if not dest.exists():
                        shutil.move(str(item), str(dest))
                        logger.info(f"Migrated legacy CIP item {item.name} -> {dest}")

    # 3. Financial Analysis: mapping, budget, remaining_inputs
    fa_dir = settings.UPLOAD_DIR / "financial_analysis"
    if fa_dir.exists():
        # Mapping
        mapping_dir = fa_dir / "mapping"
        if mapping_dir.exists():
            meta_path = mapping_dir / "gl_mapping.json"
            target_user_id = None
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    uploader = (data.get("uploaded_by") or "").strip().lower()
                    if uploader in user_lookup:
                        target_user_id = user_lookup[uploader]
                except Exception:
                    pass
            if target_user_id:
                user_map_dir = fa_dir / str(target_user_id) / "mapping"
                user_map_dir.parent.mkdir(parents=True, exist_ok=True)
                if not user_map_dir.exists():
                    shutil.move(str(mapping_dir), str(user_map_dir))
                    logger.info(f"Migrated legacy GL mapping -> {user_map_dir}")

        # Budget
        budget_dir = fa_dir / "budget"
        if budget_dir.exists():
            target_user_id = None
            for json_file in budget_dir.glob("budget_*.json"):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    uploader = (data.get("uploaded_by") or "").strip().lower()
                    if uploader in user_lookup:
                        target_user_id = user_lookup[uploader]
                        break
                except Exception:
                    pass
            if target_user_id:
                user_bud_dir = fa_dir / str(target_user_id) / "budget"
                user_bud_dir.parent.mkdir(parents=True, exist_ok=True)
                if not user_bud_dir.exists():
                    shutil.move(str(budget_dir), str(user_bud_dir))
                    logger.info(f"Migrated legacy budget -> {user_bud_dir}")

        # Remaining inputs
        rem_dir = fa_dir / "remaining_inputs"
        if rem_dir.exists():
            meta_path = rem_dir / "metadata.json"
            target_user_id = None
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    for rec in data.values():
                        if isinstance(rec, dict) and rec.get("uploader"):
                            uploader = rec["uploader"].strip().lower()
                            if uploader in user_lookup:
                                target_user_id = user_lookup[uploader]
                                break
                except Exception:
                    pass
            if target_user_id:
                user_rem_dir = fa_dir / str(target_user_id) / "remaining_inputs"
                user_rem_dir.parent.mkdir(parents=True, exist_ok=True)
                if not user_rem_dir.exists():
                    shutil.move(str(rem_dir), str(user_rem_dir))
                    logger.info(f"Migrated legacy remaining inputs -> {user_rem_dir}")

