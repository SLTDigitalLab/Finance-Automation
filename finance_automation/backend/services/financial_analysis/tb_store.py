"""
Keeps each month's trial balance (summed to natural account) in the database,
so a quarterly run only needs the new month's file: the comparison periods are
already stored.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.user_and_log import FATrialBalance, FATrialBalanceAccount
from services.financial_analysis.periods import Period
from services.financial_analysis.tb_reader import AccountBalance, TrialBalance
from utils.logger import logger


def _find(db: Session, period: Period) -> Optional[FATrialBalance]:
    return (
        db.query(FATrialBalance)
        .filter(FATrialBalance.period_year == period.year, FATrialBalance.period_month == period.month)
        .first()
    )


def save_trial_balance(db: Session, tb: TrialBalance, source_filename: str = None,
                       user_id: int = None) -> FATrialBalance:
    """Stores the trial balance, replacing any already loaded for the same month."""
    existing = _find(db, tb.period)
    if existing:
        db.query(FATrialBalanceAccount).filter(
            FATrialBalanceAccount.trial_balance_id == existing.id
        ).delete(synchronize_session=False)
        db.delete(existing)
        db.flush()

    record = FATrialBalance(
        period_year=tb.period.year,
        period_month=tb.period.month,
        source_filename=source_filename,
        row_count=tb.row_count,
        account_count=len(tb.accounts),
        net_ytd=tb.net_ytd,
        uploaded_by=user_id,
    )
    db.add(record)
    db.flush()
    db.bulk_insert_mappings(FATrialBalanceAccount, [
        {
            "trial_balance_id": record.id,
            "account": bal.account,
            "account_name": bal.name,
            "beginning_balance": bal.beginning,
            "period_activity": bal.ptd,
            "ytd_balance": bal.ytd,
        }
        for bal in tb.accounts.values()
    ])
    db.commit()
    logger.info(f"{'Replaced' if existing else 'Stored'} trial balance {tb.period.label} ({len(tb.accounts)} accounts)")
    return record


def delete_trial_balance(db: Session, period: Period) -> bool:
    record = _find(db, period)
    if record is None:
        return False
    db.query(FATrialBalanceAccount).filter(
        FATrialBalanceAccount.trial_balance_id == record.id
    ).delete(synchronize_session=False)
    db.delete(record)
    db.commit()
    logger.info(f"Deleted trial balance {period.label}")
    return True


def load_ytd(db: Session, period: Period) -> Optional[Dict[int, AccountBalance]]:
    record = _find(db, period)
    if record is None:
        return None
    rows = db.query(FATrialBalanceAccount).filter(FATrialBalanceAccount.trial_balance_id == record.id).all()
    return {
        r.account: AccountBalance(r.account, r.account_name or "", r.beginning_balance or 0.0,
                                  r.period_activity or 0.0, r.ytd_balance or 0.0)
        for r in rows
    }


def list_periods(db: Session) -> List[FATrialBalance]:
    return (
        db.query(FATrialBalance)
        .order_by(FATrialBalance.period_year.desc(), FATrialBalance.period_month.desc())
        .all()
    )
