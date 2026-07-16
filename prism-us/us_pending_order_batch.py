#!/usr/bin/env python3
"""
US Pending Order Batch Processor

Processes queued reserved orders that were placed outside the KIS API time window.
KIS reserved order window: 10:00~23:20 KST (except 16:30~16:45)

This script is intended to run via cron at 10:05 KST (Tue-Sat):
  5 10 * * 2-6 cd /app/prism-insight && python3 prism-us/us_pending_order_batch.py

Flow:
  1. Check if reserved order window is currently open
  2. Query pending orders from us_pending_orders table (today only)
  3. Execute each order via buy_reserved_order / sell_reserved_order
  4. Update order status (executed / failed)
  5. Expire old pending orders (created before today)
"""

import sys
import json
import sqlite3
import logging
import argparse
import datetime
from pathlib import Path
from typing import Optional

# Add project paths (prism-us first so its trading/ takes priority over KR trading/)
_prism_us_dir = str(Path(__file__).resolve().parent)
_project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _project_root)
sys.path.insert(0, _prism_us_dir)

import pytz
from order_ledger_safety import sanitize_order_payload, sanitize_reason

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

KST = pytz.timezone('Asia/Seoul')

# DB path (same as trading module)
DB_PATH = Path(__file__).resolve().parent.parent / "stock_tracking_db.sqlite"


def ensure_order_ledger(conn: sqlite3.Connection, *, commit: bool = True):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS us_order_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_key TEXT NOT NULL,
            account_name TEXT,
            product_code TEXT,
            mode TEXT,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            status TEXT NOT NULL,
            source TEXT NOT NULL,
            order_no TEXT,
            pending_order_id INTEGER,
            order_type TEXT,
            limit_price REAL,
            quantity INTEGER,
            exchange TEXT,
            raw_order_json TEXT,
            quarantine_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_us_order_ledger_active_buy_v2 "
        "ON us_order_ledger(account_key, ticker) "
        "WHERE lower(side) = 'buy' AND lower(status) IN "
        "('submitting', 'submission_uncertain', 'queued', 'submitted', 'open', "
        "'closed_unverified', 'quarantined')"
    )
    if commit:
        conn.commit()


def sync_ledger_for_pending_order(conn: sqlite3.Connection, order: dict, status: str,
                                  result: dict = None, failure_reason: str = None,
                                  *, commit: bool = True):
    """Keep the active-order ledger in step with the legacy pending queue."""
    if order.get("order_type") != "buy":
        return

    ensure_order_ledger(conn, commit=False)
    now_kst = datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    result = result or {}
    sanitized_result = sanitize_order_payload(result)
    order_no = result.get("order_no")
    if status == "executed":
        ledger_status = "submitted"
        source = "kis_submit"
    elif status in {"failed", "expired", "cancelled"}:
        ledger_status = status
        source = "pending_queue"
    else:
        ledger_status = status
        source = "pending_queue"

    cur = conn.execute(
        "SELECT id FROM us_order_ledger WHERE pending_order_id = ?",
        (order["id"],),
    )
    row = cur.fetchone()
    if row:
        conn.execute(
            """
            UPDATE us_order_ledger
            SET status = ?, source = ?, order_no = COALESCE(?, order_no),
                raw_order_json = ?, quarantine_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (ledger_status, source, order_no, json.dumps(sanitized_result) if sanitized_result else None,
             sanitize_reason(failure_reason), now_kst, row[0]),
        )
    else:
        conn.execute(
            """
            INSERT INTO us_order_ledger
            (account_key, account_name, product_code, mode, ticker, side, status, source,
             order_no, pending_order_id, order_type, limit_price, exchange, raw_order_json,
             quarantine_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'buy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order["account_key"],
                order.get("account_name"),
                order.get("product_code"),
                order.get("mode"),
                order["ticker"].upper(),
                ledger_status,
                source,
                order_no,
                order["id"],
                order.get("order_type"),
                order.get("limit_price"),
                order.get("exchange"),
                json.dumps(sanitized_result) if sanitized_result else None,
                sanitize_reason(failure_reason),
                now_kst,
                now_kst,
            ),
        )
    if commit:
        conn.commit()


def get_pending_orders(conn: sqlite3.Connection, today_str: str) -> list:
    """Get today's pending orders."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, account_key, account_name, product_code, mode, ticker, order_type, limit_price, buy_amount, exchange
           FROM us_pending_orders
           WHERE status = 'pending' AND date(created_at) = ?
           ORDER BY id ASC""",
        (today_str,)
    )
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def submission_failure_status(result: dict) -> str:
    """Classify response-lost/network failures as uncertain, not rejected."""
    message = str((result or {}).get("message") or "").lower()
    ambiguous_markers = (
        "timeout",
        "timed out",
        "connection",
        "reset by peer",
        " error:",
        "exception",
    )
    return "submission_uncertain" if any(marker in message for marker in ambiguous_markers) else "failed"


def claim_pending_order(conn: sqlite3.Connection, order: dict) -> Optional[int]:
    """Atomically claim one pending row and return its submitting ledger id."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE us_pending_orders
            SET status = 'processing'
            WHERE id = ? AND status = 'pending'
            """,
            (order["id"],),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        if str(order.get("order_type") or "").lower() != "buy":
            conn.commit()
            return -1
        sync_ledger_for_pending_order(
            conn,
            order,
            "submitting",
            commit=False,
        )
        ledger_row = conn.execute(
            """
            SELECT id
            FROM us_order_ledger
            WHERE pending_order_id = ?
              AND account_key = ?
              AND upper(ticker) = ?
              AND lower(side) = 'buy'
              AND lower(status) = 'submitting'
            """,
            (
                order["id"],
                order["account_key"],
                str(order["ticker"]).strip().upper(),
            ),
        ).fetchone()
        if ledger_row is None:
            conn.rollback()
            return None
        conn.commit()
        return int(ledger_row[0])
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    except Exception:
        conn.rollback()
        raise


def update_order_status(conn: sqlite3.Connection, order_id: int,
                        status: str, result: dict = None, failure_reason: str = None,
                        *, commit: bool = True):
    """Update order status after execution attempt."""
    now_kst = datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    sanitized_result = sanitize_order_payload(result)
    conn.execute(
        """UPDATE us_pending_orders
           SET status = ?, executed_at = ?, order_result = ?, failure_reason = ?
           WHERE id = ?""",
        (status, now_kst, json.dumps(sanitized_result) if sanitized_result else None,
         sanitize_reason(failure_reason), order_id)
    )
    if commit:
        conn.commit()


def update_order_and_ledger_status(conn: sqlite3.Connection, order: dict,
                                   status: str, result: dict = None, failure_reason: str = None):
    try:
        conn.execute("BEGIN IMMEDIATE")
        update_order_status(
            conn,
            order["id"],
            status,
            result=result,
            failure_reason=failure_reason,
            commit=False,
        )
        sync_ledger_for_pending_order(
            conn,
            order,
            status,
            result=result,
            failure_reason=failure_reason,
            commit=False,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def expire_old_orders(conn: sqlite3.Connection, today_str: str) -> int:
    """Atomically expire old pending rows and their linked ledger rows."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE us_pending_orders
               SET status = 'expired', failure_reason = 'Order expired (not processed on creation day)'
               WHERE status = 'pending' AND date(created_at) < ?""",
            (today_str,),
        )
        expired_rows = cursor.rowcount
        ensure_order_ledger(conn, commit=False)
        now_kst = datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            """
            UPDATE us_order_ledger
            SET status = 'expired', quarantine_reason = 'Order expired (not processed on creation day)', updated_at = ?
            WHERE source = 'pending_queue'
              AND lower(status) = 'queued'
              AND pending_order_id IN (
                  SELECT id FROM us_pending_orders WHERE status = 'expired' AND date(created_at) < ?
              )
            """,
            (now_kst, today_str),
        )
        conn.commit()
        return expired_rows
    except Exception:
        conn.rollback()
        raise


def process_pending_orders(dry_run: bool = False):
    """Main processing logic."""
    now_kst = datetime.datetime.now(KST)
    today_str = now_kst.strftime('%Y-%m-%d')

    logger.info(f"=== US Pending Order Batch Start ({today_str} {now_kst.strftime('%H:%M:%S')} KST) ===")

    # Connect to DB
    if not DB_PATH.exists():
        logger.warning(f"Database not found: {DB_PATH}")
        return

    if dry_run:
        readonly_uri = f"{DB_PATH.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(readonly_uri, uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            expired_count = conn.execute(
                """
                SELECT COUNT(*) FROM us_pending_orders
                WHERE status = 'pending' AND date(created_at) < ?
                """,
                (today_str,),
            ).fetchone()[0]
            pending_orders = get_pending_orders(conn, today_str)
            logger.info(
                "[DRY RUN] Would expire %s old order(s) and process %s current order(s)",
                expired_count,
                len(pending_orders),
            )
            for order in pending_orders:
                logger.info(
                    "  [DRY RUN] Would execute %s for %s",
                    order["order_type"],
                    order["ticker"],
                )
            return
        finally:
            conn.close()

    conn = sqlite3.connect(str(DB_PATH))

    # Expire old orders first
    expired_count = expire_old_orders(conn, today_str)
    if expired_count > 0:
        logger.info(f"Expired {expired_count} old pending order(s)")

    # Get today's pending orders
    pending_orders = get_pending_orders(conn, today_str)

    if not pending_orders:
        logger.info("No pending orders to process")
        conn.close()
        return

    logger.info(f"Found {len(pending_orders)} pending order(s) to process")

    # Import trading module (prism-us/trading/ is first in sys.path)
    from trading.us_stock_trading import USStockTrading

    # Check if reserved order window is open using a representative trader
    try:
        window_checker = USStockTrading()
    except Exception as e:
        safe_error = sanitize_reason(str(e)) or "Unknown trading-module initialization error"
        logger.error(f"Failed to initialize trading module: {safe_error}")
        conn.close()
        return

    if not window_checker.is_reserved_order_available():
        logger.error("Reserved order window is not open. Aborting batch.")
        conn.close()
        return

    # Process each order
    success_count = 0
    fail_count = 0

    for order in pending_orders:
        order_id = order['id']
        account_name = order.get('account_name')
        product_code = order.get('product_code') or "01"
        mode = order.get('mode') or "demo"
        ticker = order['ticker']
        order_type = order['order_type']
        limit_price = order['limit_price']
        buy_amount = order['buy_amount']
        exchange = order['exchange']

        logger.info(f"Processing order #{order_id}: {order_type} {ticker} @ ${limit_price:.2f} for {account_name}")

        pending_claim_id = claim_pending_order(conn, order)
        if pending_claim_id is None:
            logger.info(f"  Order #{order_id} was already claimed by another worker; skipping")
            continue

        try:
            trader = USStockTrading(mode=mode, account_name=account_name, product_code=product_code)
            if order_type == 'buy':
                result = trader.buy_reserved_order(
                    ticker=ticker,
                    limit_price=limit_price,
                    buy_amount=buy_amount,
                    exchange=exchange,
                    force_submit=True,
                    submission_ledger_id=pending_claim_id,
                )
            elif order_type == 'sell':
                result = trader.sell_reserved_order(
                    ticker=ticker,
                    limit_price=limit_price if limit_price > 0 else None,
                    exchange=exchange
                )
            else:
                logger.warning(f"  Unknown order type: {order_type}")
                update_order_and_ledger_status(conn, order, 'failed', failure_reason=f'Unknown order type: {order_type}')
                fail_count += 1
                continue

            if result.get('success'):
                safe_message = sanitize_reason(result.get('message')) or 'Order executed successfully'
                logger.info(f"  Order #{order_id} executed successfully: {safe_message}")
                update_order_and_ledger_status(conn, order, 'executed', result=result)
                success_count += 1
            else:
                error_msg = result.get('message', 'Unknown error')
                safe_error_msg = sanitize_reason(error_msg) or 'Unknown error'
                final_status = submission_failure_status(result)
                logger.error(f"  Order #{order_id} {final_status}: {safe_error_msg}")
                update_order_and_ledger_status(
                    conn,
                    order,
                    final_status,
                    result=result,
                    failure_reason=safe_error_msg,
                )
                fail_count += 1

        except Exception as e:
            safe_error = sanitize_reason(str(e)) or 'Unknown pending-order exception'
            logger.error(f"  Order #{order_id} exception: {safe_error}")
            update_order_and_ledger_status(
                conn,
                order,
                'submission_uncertain',
                failure_reason=safe_error,
            )
            fail_count += 1

        # Rate limit between orders
        import time
        time.sleep(0.5)

    conn.close()

    logger.info(f"=== Batch Complete: {success_count} success, {fail_count} failed, {len(pending_orders)} total ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="US Pending Order Batch Processor")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (don't execute orders)")
    args = parser.parse_args()

    process_pending_orders(dry_run=args.dry_run)
