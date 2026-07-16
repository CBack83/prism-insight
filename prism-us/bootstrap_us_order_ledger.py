#!/usr/bin/env python3
"""
Bootstrap US order ledger from legacy pending queue and live KIS open orders.

Run this before enabling duplicate-buy enforcement on an existing deployment:
  python3 prism-us/bootstrap_us_order_ledger.py --mode real --apply
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional

PRISM_US_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PRISM_US_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PRISM_US_DIR))

from trading import us_stock_trading as ust

EXCHANGES = ("NASD", "NYSE", "AMEX")


def _db_path_from_args(path: Optional[str]) -> Path:
    return Path(path).expanduser().resolve() if path else PROJECT_ROOT / "stock_tracking_db.sqlite"


def _record_open_order(conn: sqlite3.Connection, trader: ust.USStockTrading,
                       order: dict, *, commit: bool = True) -> bool:
    ticker = str(order.get("ticker") or "").strip().upper()
    side = "sell" if str(order.get("sll_buy_dvsn_cd") or "") == "01" else "buy"
    if not ticker:
        return False

    try:
        ust._record_us_order_ledger(
            conn,
            account_key=trader.account_key,
            account_name=trader.account_name,
            product_code=trader.product_code,
            mode=trader.mode,
            ticker=ticker,
            side=side,
            status="open",
            source="kis_open_orders",
            order_no=order.get("order_no") or None,
            order_type="limit",
            limit_price=order.get("ord_unpr"),
            quantity=order.get("nccs_qty"),
            exchange=order.get("exchange"),
            raw_order=order,
            commit=commit,
        )
        return True
    except Exception as exc:
        # Existing active buy rows are expected when the same order was already
        # bootstrapped by an earlier guarded preflight.
        if "UNIQUE constraint failed" in str(exc):
            return False
        raise


def bootstrap(mode: str, product_code: str, db_path: Path, apply: bool) -> int:
    if not apply:
        readonly_uri = f"{db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(readonly_uri, uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            pending_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='us_pending_orders'"
            ).fetchone()
            pending_count = 0
            if pending_table:
                pending_count = conn.execute(
                    """
                    SELECT COUNT(*) FROM us_pending_orders
                    WHERE lower(status) = 'pending' AND lower(order_type) = 'buy'
                    """
                ).fetchone()[0]
            print(
                "DRY RUN: would query KIS open orders and adopt/verify "
                f"{pending_count} legacy pending order(s)"
            )
            return 0
        finally:
            conn.close()

    svr = "vps" if mode == "demo" else "prod"
    accounts = ust.ka.get_configured_accounts(svr=svr, product=str(product_code), market="us")
    if not accounts:
        print(f"No US accounts configured for mode={mode}, product={product_code}")
        return 1

    collected_orders = []
    failed = []
    for account in accounts:
        trader = ust.USStockTrading(
            mode=mode,
            account_name=account["name"],
            product_code=account["product"],
        )
        for exchange in EXCHANGES:
            orders = trader.get_unfilled_orders(exchange=exchange)
            if not getattr(trader, "_last_unfilled_order_inquiry_ok", False):
                failed.append(f"{account['name']}:{exchange}")
                continue
            collected_orders.extend((trader, order) for order in orders)

    if failed:
        print("FAIL: KIS open-order inquiry failed for " + ", ".join(failed))
        return 2

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        ust._ensure_us_order_ledger(conn, commit=False)
        pending_count = ust._bootstrap_pending_orders_to_ledger(conn, commit=False)
        recorded = 0
        for trader, order in collected_orders:
            if _record_open_order(conn, trader, order, commit=False):
                recorded += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"OK: legacy_pending={pending_count}, kis_open_orders_recorded={recorded}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap US order ledger before deployment.")
    parser.add_argument("--mode", choices=["demo", "real"], default=ust.USStockTrading.DEFAULT_MODE)
    parser.add_argument("--product-code", default="01")
    parser.add_argument("--db-path")
    parser.add_argument("--apply", action="store_true", help="Actually query KIS and write live open orders.")
    args = parser.parse_args()
    return bootstrap(args.mode, args.product_code, _db_path_from_args(args.db_path), args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
