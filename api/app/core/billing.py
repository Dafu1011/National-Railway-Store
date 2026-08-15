from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage import AppStorage, new_id, row_to_dict


GENERATION_CHARGE_POINTS = 10
RECHARGE_VALID_DAYS = 365


class InsufficientBalance(Exception):
    def __init__(self, *, required_points: int, available_points: int):
        super().__init__("insufficient balance")
        self.required_points = required_points
        self.available_points = available_points


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_after_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def ensure_user_account(connection: Any, *, user_id: str, username: str) -> dict[str, Any]:
    account = row_to_dict(connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone())
    if account is None:
        connection.execute(
            """
            INSERT INTO user_accounts (user_id, username_snapshot, balance_points, reserved_points)
            VALUES (?, ?, 0, 0)
            """,
            (user_id, username or ""),
        )
        account = row_to_dict(connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone())
    elif username and account.get("username_snapshot") != username:
        connection.execute(
            "UPDATE user_accounts SET username_snapshot = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (username, user_id),
        )
        account["username_snapshot"] = username
    return account


def get_account_payload(storage: AppStorage, user: dict[str, Any]) -> dict[str, Any]:
    with storage.connect() as connection:
        account = ensure_user_account(connection, user_id=user["id"], username=user.get("username", ""))
        refresh_expired_points(connection, user_id=user["id"])
        account = row_to_dict(connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user["id"],)).fetchone())
        next_lot = row_to_dict(
            connection.execute(
                """
                SELECT id, remaining_points, expires_at
                FROM account_point_lots
                WHERE user_id = ? AND remaining_points > 0 AND expires_at > ?
                ORDER BY expires_at ASC, created_at ASC
                LIMIT 1
                """,
                (user["id"], utc_now()),
            ).fetchone()
        )
    return account_payload(account, user=user, next_lot=next_lot)


def list_transactions(storage: AppStorage, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with storage.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM account_transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def recharge_account(
    storage: AppStorage,
    *,
    target_user: dict[str, Any],
    points: int,
    remark: str,
) -> dict[str, Any]:
    if points <= 0:
        raise ValueError("points must be positive")
    with storage.connect() as connection:
        account = ensure_user_account(connection, user_id=target_user["id"], username=target_user.get("username", ""))
        refresh_expired_points(connection, user_id=target_user["id"])
        account = row_to_dict(
            connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (target_user["id"],)).fetchone()
        )
        balance_after = int(account["balance_points"]) + points
        connection.execute(
            """
            INSERT INTO account_point_lots
                (id, user_id, source_type, total_points, remaining_points, expires_at)
            VALUES (?, ?, 'manual_recharge', ?, ?, ?)
            """,
            (new_id(), target_user["id"], points, points, utc_after_days(RECHARGE_VALID_DAYS)),
        )
        connection.execute(
            """
            UPDATE user_accounts
            SET balance_points = ?, username_snapshot = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (balance_after, target_user.get("username", ""), target_user["id"]),
        )
        insert_transaction(
            connection,
            user_id=target_user["id"],
            transaction_type="recharge",
            points=points,
            balance_after=balance_after,
            remark=remark,
        )
        account = row_to_dict(
            connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (target_user["id"],)).fetchone()
        )
        next_lot = row_to_dict(
            connection.execute(
                """
                SELECT id, remaining_points, expires_at
                FROM account_point_lots
                WHERE user_id = ? AND remaining_points > 0
                ORDER BY expires_at ASC, created_at ASC
                LIMIT 1
                """,
                (target_user["id"],),
            ).fetchone()
        )
    return account_payload(account, user=target_user, next_lot=next_lot)


def reserve_generation_charge(storage: AppStorage, *, user: dict[str, Any], job_id: str) -> None:
    with storage.connect() as connection:
        ensure_user_account(connection, user_id=user["id"], username=user.get("username", ""))
        refresh_expired_points(connection, user_id=user["id"])

        # The conditional UPDATE is the concurrency guard: PostgreSQL will lock the account row
        # and only one request can reserve the same available points.
        updated = connection.execute(
            """
            UPDATE user_accounts
            SET reserved_points = reserved_points + ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND (balance_points - reserved_points) >= ?
            """,
            (GENERATION_CHARGE_POINTS, user["id"], GENERATION_CHARGE_POINTS),
        )
        if updated.rowcount != 1:
            account = row_to_dict(connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user["id"],)).fetchone())
            available_points = int(account["balance_points"]) - int(account["reserved_points"]) if account else 0
            raise InsufficientBalance(required_points=GENERATION_CHARGE_POINTS, available_points=available_points)
        connection.execute(
            """
            INSERT INTO generation_billing_holds (id, user_id, job_id, points, status)
            VALUES (?, ?, ?, ?, 'reserved')
            """,
            (new_id(), user["id"], job_id, GENERATION_CHARGE_POINTS),
        )


def charge_generation_hold(storage: AppStorage, *, user_id: str, job_id: str) -> None:
    with storage.connect() as connection:
        hold = reserved_hold(connection, user_id=user_id, job_id=job_id)
        if hold is None:
            return
        points_to_charge = int(hold["points"])
        deduct_from_lots(connection, user_id=user_id, points=points_to_charge)
        account = row_to_dict(connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone())
        balance_after = max(0, int(account["balance_points"]) - points_to_charge)
        reserved_after = max(0, int(account["reserved_points"]) - points_to_charge)
        connection.execute(
            """
            UPDATE user_accounts
            SET balance_points = ?, reserved_points = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (balance_after, reserved_after, user_id),
        )
        connection.execute(
            """
            UPDATE generation_billing_holds
            SET status = 'charged', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (hold["id"],),
        )
        insert_transaction(
            connection,
            user_id=user_id,
            transaction_type="generation_charge",
            points=-points_to_charge,
            balance_after=balance_after,
            related_job_id=job_id,
            remark="生成5张图片扣费",
        )


def release_generation_hold(storage: AppStorage, *, user_id: str, job_id: str, remark: str = "") -> None:
    with storage.connect() as connection:
        hold = reserved_hold(connection, user_id=user_id, job_id=job_id)
        if hold is None:
            return
        points = int(hold["points"])
        account = row_to_dict(connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone())
        reserved_after = max(0, int(account["reserved_points"]) - points)
        connection.execute(
            """
            UPDATE user_accounts
            SET reserved_points = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (reserved_after, user_id),
        )
        connection.execute(
            """
            UPDATE generation_billing_holds
            SET status = 'released', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (hold["id"],),
        )
        insert_transaction(
            connection,
            user_id=user_id,
            transaction_type="generation_release",
            points=0,
            balance_after=int(account["balance_points"]),
            related_job_id=job_id,
            remark=remark,
        )


def refresh_expired_points(connection: Any, *, user_id: str) -> None:
    expired_lots = connection.execute(
        """
        SELECT id, remaining_points
        FROM account_point_lots
        WHERE user_id = ? AND remaining_points > 0 AND expires_at <= ?
        """,
        (user_id, utc_now()),
    ).fetchall()
    expired_points = sum(int(row["remaining_points"]) for row in expired_lots)
    if expired_points <= 0:
        return
    for lot in expired_lots:
        connection.execute("UPDATE account_point_lots SET remaining_points = 0 WHERE id = ?", (lot["id"],))
    account = row_to_dict(connection.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone())
    balance_after = max(0, int(account["balance_points"]) - expired_points)
    connection.execute(
        """
        UPDATE user_accounts
        SET balance_points = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (balance_after, user_id),
    )
    insert_transaction(
        connection,
        user_id=user_id,
        transaction_type="expire",
        points=-expired_points,
        balance_after=balance_after,
        remark="点数有效期到期",
    )


def deduct_from_lots(connection: Any, *, user_id: str, points: int) -> None:
    remaining = points
    lots = connection.execute(
        """
        SELECT id, remaining_points
        FROM account_point_lots
        WHERE user_id = ? AND remaining_points > 0 AND expires_at > ?
        ORDER BY expires_at ASC, created_at ASC
        """,
        (user_id, utc_now()),
    ).fetchall()
    for lot in lots:
        if remaining <= 0:
            break
        lot_remaining = int(lot["remaining_points"])
        used = min(remaining, lot_remaining)
        connection.execute(
            "UPDATE account_point_lots SET remaining_points = ? WHERE id = ?",
            (lot_remaining - used, lot["id"]),
        )
        remaining -= used
    if remaining > 0:
        raise InsufficientBalance(required_points=points, available_points=points - remaining)


def reserved_hold(connection: Any, *, user_id: str, job_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        connection.execute(
            """
            SELECT * FROM generation_billing_holds
            WHERE user_id = ? AND job_id = ? AND status = 'reserved'
            """,
            (user_id, job_id),
        ).fetchone()
    )


def insert_transaction(
    connection: Any,
    *,
    user_id: str,
    transaction_type: str,
    points: int,
    balance_after: int,
    related_job_id: str | None = None,
    remark: str = "",
) -> None:
    connection.execute(
        """
        INSERT INTO account_transactions
            (id, user_id, type, points, balance_after, related_job_id, remark)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id(), user_id, transaction_type, points, balance_after, related_job_id, remark),
    )


def account_payload(
    account: dict[str, Any],
    *,
    user: dict[str, Any],
    next_lot: dict[str, Any] | None,
) -> dict[str, Any]:
    balance_points = int(account["balance_points"])
    reserved_points = int(account["reserved_points"])
    return {
        "user": {
            "id": user["id"],
            "email": user.get("email", ""),
            "username": user.get("username", account.get("username_snapshot", "")),
        },
        "username": user.get("username", account.get("username_snapshot", "")),
        "balance_points": balance_points,
        "reserved_points": reserved_points,
        "available_points": max(0, balance_points - reserved_points),
        "next_expiring_lot": next_lot,
    }
