"""Budget Ledger. Integer minor units only.

Concurrency: every balance change is a single conditional UPDATE (atomic in both PostgreSQL and SQLite),
plus a DB CHECK (reserved+committed+settled <= limit) as a second line of defense.
Idempotency: (account_id, idempotency_key) is unique on BudgetEntry; the entry insert and the balance update
happen in the same transaction, so a retry with the same key is a no-op."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from atlas.models import BudgetAccount, BudgetEntry


class BudgetExceeded(Exception):
    pass


def _existing(s: Session, account_id: str, key: str) -> BudgetEntry | None:
    return s.scalar(select(BudgetEntry).where(BudgetEntry.account_id == account_id, BudgetEntry.idempotency_key == key))


def _apply(s: Session, account_id: str, key: str, entry_type: str, amount: int, stmt, action_id: str | None,
           note: str) -> BudgetEntry:
    if amount < 0:
        raise ValueError("amount must be >= 0")
    if (e := _existing(s, account_id, key)) is not None:
        return e
    sp = s.begin_nested()
    try:
        entry = BudgetEntry(account_id=account_id, entry_type=entry_type, amount_minor=amount, idempotency_key=key,
                            action_id=action_id, note=note)
        s.add(entry)
        s.flush()
        res = s.execute(stmt)
        if res.rowcount != 1:
            raise BudgetExceeded(f"{entry_type} {amount} rejected on account {account_id}")
        sp.commit()
    except IntegrityError as ie:
        sp.rollback()
        if (e := _existing(s, account_id, key)) is not None:  # concurrent same-key insert
            return e
        raise BudgetExceeded(str(ie.orig)) from ie
    except Exception:
        sp.rollback()
        raise
    s.expire_all()
    return entry


def reserve(s: Session, account_id: str, amount: int, key: str, action_id: str | None = None, note: str = "") -> BudgetEntry:
    A = BudgetAccount
    stmt = (update(A).where(A.id == account_id,
                            A.limit_minor - A.reserved_minor - A.committed_minor - A.settled_minor >= amount)
            .values(reserved_minor=A.reserved_minor + amount))
    return _apply(s, account_id, f"reserve:{key}", "reservation", amount, stmt, action_id, note)


def commit(s: Session, account_id: str, amount: int, key: str, action_id: str | None = None) -> BudgetEntry:
    A = BudgetAccount
    stmt = (update(A).where(A.id == account_id, A.reserved_minor >= amount)
            .values(reserved_minor=A.reserved_minor - amount, committed_minor=A.committed_minor + amount))
    return _apply(s, account_id, f"commit:{key}", "commitment", amount, stmt, action_id, "")


def release(s: Session, account_id: str, amount: int, key: str, action_id: str | None = None) -> BudgetEntry:
    A = BudgetAccount
    stmt = (update(A).where(A.id == account_id, A.reserved_minor >= amount)
            .values(reserved_minor=A.reserved_minor - amount))
    return _apply(s, account_id, f"release:{key}", "release", amount, stmt, action_id, "")


def settle(s: Session, account_id: str, committed_amount: int, actual_amount: int, key: str,
           action_id: str | None = None) -> BudgetEntry:
    """Move commitment to settled using provider-reconciled actual. Overspend beyond commitment is recorded
    as overrun (it already happened externally; we cannot un-spend it) and surfaced in reports."""
    A = BudgetAccount
    settled = min(actual_amount, committed_amount)
    overrun = max(0, actual_amount - committed_amount)
    stmt = (update(A).where(A.id == account_id, A.committed_minor >= committed_amount)
            .values(committed_minor=A.committed_minor - committed_amount, settled_minor=A.settled_minor + settled,
                    overrun_minor=A.overrun_minor + overrun))
    return _apply(s, account_id, f"settle:{key}", "settlement", actual_amount, stmt, action_id,
                  f"committed={committed_amount} actual={actual_amount} overrun={overrun}")


def record_estimate(s: Session, account_id: str, amount: int, key: str, note: str = "") -> BudgetEntry:
    """Model/tool cost estimates: tracked separately, flagged is_estimate, not counted as reconciled spend."""
    A = BudgetAccount
    stmt = update(A).where(A.id == account_id).values(estimated_untracked_minor=A.estimated_untracked_minor + amount)
    e = _apply(s, account_id, f"estimate:{key}", "estimate", amount, stmt, None, note)
    e.is_estimate = True
    return e


def summary(acc: BudgetAccount) -> dict:
    return {"account_id": acc.id, "category": acc.category, "currency": acc.currency, "limit": acc.limit_minor,
            "reserved": acc.reserved_minor, "committed": acc.committed_minor, "settled": acc.settled_minor,
            "available": acc.limit_minor - acc.reserved_minor - acc.committed_minor - acc.settled_minor,
            "overrun": acc.overrun_minor, "estimated_model_tool_cost": acc.estimated_untracked_minor}
