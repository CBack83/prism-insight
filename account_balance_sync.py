#!/usr/bin/env python3
"""
KIS real-account holdings reconciliation for Prism Insight.

Default behavior is dry-run only:
    python account_balance_sync.py

Apply explicit, non-destructive DB updates:
    python account_balance_sync.py --apply

What this script does:
- Reads real KIS holdings for configured KR/US accounts.
- Compares them with stock_tracking_db.sqlite holdings tables.
- Ignores configured non-trading holdings such as unlisted employee shares.
- Adds actual-only tradable holdings and updates common holding prices when --apply is used.
- Never deletes DB-only holdings automatically.

Quantity policy:
- The current production schema may not have a quantity column.
- This script detects the column at runtime and only writes quantity when the column exists.
- Without a quantity column, quantity is included in scenario metadata for audit only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "stock_tracking_db.sqlite"
DEFAULT_MODE = "real"
DEFAULT_PRODUCT = "01"

MARKET_TABLES = {
    "kr": "stock_holdings",
    "us": "us_stock_holdings",
}

MARKET_LABELS = {
    "kr": "국내",
    "us": "미국",
}

# Holdings that exist in the broker account but should not be tracked by the bot.
# 350920 is an unlisted employee-share holding, so it should not appear as a
# reconciliation mismatch or be inserted into the trading DB.
EXCLUDED_ACTUAL_ONLY = {
    ("kr", "350920"): "우리사주/비상장/투자봇 검토 제외",
}


@dataclass(frozen=True)
class HoldingKey:
    market: str
    account_key: str
    ticker: str


@dataclass
class Holding:
    market: str
    account_key: str
    account_name: str | None
    ticker: str
    company_name: str
    buy_price: float | None = None
    current_price: float | None = None
    quantity: int | None = None
    buy_date: str | None = None
    last_updated: str | None = None
    target_price: float | None = None
    stop_loss: float | None = None
    scenario: dict[str, Any] | None = None
    trigger_type: str | None = None
    trigger_mode: str | None = None
    sector: str | None = None
    exchange: str | None = None

    @property
    def key(self) -> HoldingKey:
        return HoldingKey(self.market, self.account_key, self.ticker)


@dataclass
class Change:
    key: HoldingKey
    actual: Holding
    db: Holding
    fields: dict[str, tuple[Any, Any]]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _load_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _mask_account_key(account_key: str) -> str:
    try:
        svr, account, product = account_key.split(":")
        return f"{svr}:{account[:2]}****{account[-2:]}:{product}"
    except ValueError:
        return account_key


def _price_changed(db_value: float | None, actual_value: float | None, market: str) -> bool:
    if db_value is None or actual_value is None:
        return db_value != actual_value
    tolerance = 0.005 if market == "us" else 0.5
    return abs(db_value - actual_value) > tolerance


def _format_price(value: float | None, market: str) -> str:
    if value is None:
        return "없음"
    if market == "us":
        return f"${value:,.2f}"
    return f"{value:,.0f}원"


def _format_holding(holding: Holding) -> str:
    account = _mask_account_key(holding.account_key)
    qty = f", {holding.quantity}주" if holding.quantity is not None and holding.market == "kr" else ""
    if holding.quantity is not None and holding.market == "us":
        qty = f", {holding.quantity} shares"
    price = _format_price(holding.buy_price, holding.market)
    return f"{MARKET_LABELS[holding.market]} {holding.company_name}({holding.ticker}) [{account}]{qty}, 평균 {price}"


def _load_us_trading_class():
    module_path = PROJECT_ROOT / "prism-us" / "trading" / "us_stock_trading.py"
    spec = importlib.util.spec_from_file_location("prism_us_stock_trading", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load US trading module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.USStockTrading


def _get_kis_auth_module():
    trading_dir = PROJECT_ROOT / "trading"
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if str(trading_dir) not in sys.path:
        sys.path.insert(0, str(trading_dir))
    import kis_auth as ka

    return ka


def fetch_actual_holdings(markets: Iterable[str], mode: str, product: str) -> list[Holding]:
    """Fetch live broker holdings from KIS."""
    ka = _get_kis_auth_module()
    from trading.domestic_stock_trading import DomesticStockTrading

    USStockTrading = _load_us_trading_class()
    svr = "vps" if mode == "demo" else "prod"
    holdings: list[Holding] = []

    for market in markets:
        trading_class = DomesticStockTrading if market == "kr" else USStockTrading
        accounts = ka.get_configured_accounts(svr=svr, product=product, market=market)

        for account in accounts:
            trader = trading_class(
                mode=mode,
                account_name=account["name"],
                product_code=account["product"],
            )
            portfolio = trader.get_portfolio()

            for item in portfolio:
                if market == "kr":
                    holdings.append(
                        Holding(
                            market="kr",
                            account_key=account["account_key"],
                            account_name=account["name"],
                            ticker=str(item.get("stock_code") or ""),
                            company_name=str(item.get("stock_name") or ""),
                            quantity=_safe_int(item.get("quantity")),
                            buy_price=_safe_float(item.get("avg_price")),
                            current_price=_safe_float(item.get("current_price")),
                        )
                    )
                else:
                    holdings.append(
                        Holding(
                            market="us",
                            account_key=account["account_key"],
                            account_name=account["name"],
                            ticker=str(item.get("ticker") or ""),
                            company_name=str(item.get("stock_name") or ""),
                            quantity=_safe_int(item.get("quantity")),
                            buy_price=_safe_float(item.get("avg_price")),
                            current_price=_safe_float(item.get("current_price")),
                            exchange=item.get("exchange"),
                        )
                    )

    return [holding for holding in holdings if holding.ticker]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def read_db_holdings(db_path: Path, markets: Iterable[str]) -> tuple[list[Holding], dict[str, set[str]]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        all_holdings: list[Holding] = []
        columns_by_market: dict[str, set[str]] = {}

        for market in markets:
            table = MARKET_TABLES[market]
            columns = _table_columns(conn, table)
            columns_by_market[market] = columns

            select_columns = [
                "account_key",
                "account_name",
                "ticker",
                "company_name",
                "buy_price",
                "current_price",
                "buy_date",
                "last_updated",
                "scenario",
                "target_price",
                "stop_loss",
                "trigger_type",
                "trigger_mode",
                "sector",
            ]
            if "quantity" in columns:
                select_columns.insert(5, "quantity")

            sql = f"""
                SELECT {", ".join(select_columns)}
                FROM {table}
                ORDER BY account_key, ticker
            """
            for row in conn.execute(sql):
                row_dict = dict(row)
                all_holdings.append(
                    Holding(
                        market=market,
                        account_key=row_dict["account_key"],
                        account_name=row_dict.get("account_name"),
                        ticker=row_dict["ticker"],
                        company_name=row_dict["company_name"],
                        quantity=_safe_int(row_dict.get("quantity")),
                        buy_price=_safe_float(row_dict.get("buy_price")),
                        current_price=_safe_float(row_dict.get("current_price")),
                        buy_date=row_dict.get("buy_date"),
                        last_updated=row_dict.get("last_updated"),
                        target_price=_safe_float(row_dict.get("target_price")),
                        stop_loss=_safe_float(row_dict.get("stop_loss")),
                        scenario=_load_json(row_dict.get("scenario")),
                        trigger_type=row_dict.get("trigger_type"),
                        trigger_mode=row_dict.get("trigger_mode"),
                        sector=row_dict.get("sector"),
                    )
                )

        return all_holdings, columns_by_market
    finally:
        conn.close()


def compare_holdings(
    actual_holdings: list[Holding],
    db_holdings: list[Holding],
    columns_by_market: dict[str, set[str]],
) -> dict[str, Any]:
    actual = {holding.key: holding for holding in actual_holdings}
    db = {holding.key: holding for holding in db_holdings}

    excluded_actual_only: list[tuple[Holding, str]] = []
    actual_only: list[Holding] = []
    for key in sorted(actual.keys() - db.keys(), key=lambda k: (k.market, k.account_key, k.ticker)):
        holding = actual[key]
        reason = EXCLUDED_ACTUAL_ONLY.get((holding.market, holding.ticker))
        if reason:
            excluded_actual_only.append((holding, reason))
        else:
            actual_only.append(holding)

    db_only = [db[key] for key in sorted(db.keys() - actual.keys(), key=lambda k: (k.market, k.account_key, k.ticker))]

    changed: list[Change] = []
    for key in sorted(actual.keys() & db.keys(), key=lambda k: (k.market, k.account_key, k.ticker)):
        actual_holding = actual[key]
        db_holding = db[key]
        fields: dict[str, tuple[Any, Any]] = {}

        if _price_changed(db_holding.buy_price, actual_holding.buy_price, key.market):
            fields["buy_price"] = (db_holding.buy_price, actual_holding.buy_price)
        if _price_changed(db_holding.current_price, actual_holding.current_price, key.market):
            fields["current_price"] = (db_holding.current_price, actual_holding.current_price)

        if "quantity" in columns_by_market.get(key.market, set()):
            if db_holding.quantity != actual_holding.quantity:
                fields["quantity"] = (db_holding.quantity, actual_holding.quantity)

        if fields:
            changed.append(Change(key=key, actual=actual_holding, db=db_holding, fields=fields))

    return {
        "actual_only": actual_only,
        "db_only": db_only,
        "changed": changed,
        "excluded_actual_only": excluded_actual_only,
        "common_count": len(actual.keys() & db.keys()),
        "actual_count": len(actual),
        "db_count": len(db),
    }


def print_report(comparison: dict[str, Any], columns_by_market: dict[str, set[str]], apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n=== 계좌-DB 보유종목 검증 ({mode}) ===")
    print(f"실계좌 보유: {comparison['actual_count']}개")
    print(f"DB 보유: {comparison['db_count']}개")
    print(f"공통 보유: {comparison['common_count']}개")

    for market in columns_by_market:
        if "quantity" not in columns_by_market.get(market, set()):
            print(f"참고: {MARKET_LABELS[market]} DB에는 quantity 컬럼이 없어 수량은 비교/갱신하지 않습니다.")

    if comparison["excluded_actual_only"]:
        print("\n=== 검증 제외 실계좌 보유 ===")
        for holding, reason in comparison["excluded_actual_only"]:
            print(f"- {_format_holding(holding)}")
            print(f"  사유: {reason}")

    if comparison["actual_only"]:
        print("\n=== 실계좌에만 있는 종목 (추가 후보) ===")
        for holding in comparison["actual_only"]:
            print(f"- {_format_holding(holding)}")
    else:
        print("\n실계좌에만 있는 추가 후보는 없습니다.")

    if comparison["db_only"]:
        print("\n=== DB에만 있는 종목 (삭제 후보, 자동 삭제 안 함) ===")
        for holding in comparison["db_only"]:
            print(f"- {_format_holding(holding)}")
    else:
        print("DB에만 있는 삭제 후보는 없습니다.")

    if comparison["changed"]:
        print("\n=== 공통 종목 중 갱신 후보 ===")
        for change in comparison["changed"]:
            print(f"- {_format_holding(change.actual)}")
            for field, (old, new) in change.fields.items():
                if field in {"buy_price", "current_price"}:
                    old_text = _format_price(old, change.key.market)
                    new_text = _format_price(new, change.key.market)
                else:
                    old_text = str(old)
                    new_text = str(new)
                print(f"  {field}: {old_text} -> {new_text}")
    else:
        print("공통 종목 중 갱신 후보는 없습니다.")

    if not apply:
        print("\nDRY-RUN입니다. DB는 변경하지 않았습니다. 실제 반영은 --apply를 붙여 실행하세요.")


def _merge_scenario(existing: dict[str, Any] | None, actual: Holding) -> str:
    scenario = dict(existing or {})
    scenario.update(
        {
            "account_balance_reconciled": True,
            "account_balance_reconciled_at": _now(),
            "actual_quantity": actual.quantity,
            "actual_avg_price": actual.buy_price,
            "manual_purchase": scenario.get("manual_purchase", True),
            "source": "account_balance_sync",
        }
    )
    return json.dumps(scenario, ensure_ascii=False)


def _backup_db(db_path: Path) -> Path:
    backup_dir = PROJECT_ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"stock_tracking_db_before_account_balance_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _insert_holding(
    cursor: sqlite3.Cursor,
    holding: Holding,
    columns: set[str],
) -> None:
    table = MARKET_TABLES[holding.market]
    now = _now()
    scenario = _merge_scenario(
        {
            "note": "실계좌-DB 보유종목 동기화로 추가",
            "tracking_review_required": True,
        },
        holding,
    )

    values: dict[str, Any] = {
        "account_key": holding.account_key,
        "account_name": holding.account_name,
        "ticker": holding.ticker,
        "company_name": holding.company_name,
        "buy_price": holding.buy_price or 0,
        "buy_date": now,
        "current_price": holding.current_price or 0,
        "last_updated": now,
        "scenario": scenario,
        "target_price": 0,
        "stop_loss": 0,
        "trigger_type": "account_reconcile",
        "trigger_mode": "manual",
        "sector": "Unknown" if holding.market == "us" else "알 수 없음",
    }
    if "quantity" in columns:
        values["quantity"] = holding.quantity

    col_names = list(values.keys())
    placeholders = ", ".join("?" for _ in col_names)
    cursor.execute(
        f"""
        INSERT INTO {table} ({", ".join(col_names)})
        VALUES ({placeholders})
        """,
        [values[name] for name in col_names],
    )


def _update_holding(cursor: sqlite3.Cursor, change: Change, columns: set[str]) -> None:
    table = MARKET_TABLES[change.key.market]
    db_scenario = change.db.scenario or {}
    updates: dict[str, Any] = {
        "company_name": change.actual.company_name,
        "buy_price": change.actual.buy_price if "buy_price" in change.fields else change.db.buy_price,
        "current_price": change.actual.current_price if "current_price" in change.fields else change.db.current_price,
        "last_updated": _now(),
        "scenario": _merge_scenario(db_scenario, change.actual),
    }
    if "quantity" in columns and "quantity" in change.fields:
        updates["quantity"] = change.actual.quantity

    assignments = ", ".join(f"{column} = ?" for column in updates)
    cursor.execute(
        f"""
        UPDATE {table}
        SET {assignments}
        WHERE account_key = ? AND ticker = ?
        """,
        [*updates.values(), change.key.account_key, change.key.ticker],
    )


def apply_changes(db_path: Path, comparison: dict[str, Any], columns_by_market: dict[str, set[str]]) -> Path | None:
    if not comparison["actual_only"] and not comparison["changed"]:
        print("\n적용할 추가/갱신 항목이 없습니다.")
        return None

    backup_path = _backup_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        for holding in comparison["actual_only"]:
            _insert_holding(cursor, holding, columns_by_market.get(holding.market, set()))
            print(f"추가 완료: {_format_holding(holding)}")

        for change in comparison["changed"]:
            _update_holding(cursor, change, columns_by_market.get(change.key.market, set()))
            print(f"갱신 완료: {_format_holding(change.actual)}")

        conn.commit()
        return backup_path
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_markets(value: str) -> list[str]:
    if value == "all":
        return ["kr", "us"]
    markets = [item.strip().lower() for item in value.split(",") if item.strip()]
    unknown = sorted(set(markets) - set(MARKET_TABLES))
    if unknown:
        raise argparse.ArgumentTypeError(f"Unknown market(s): {', '.join(unknown)}")
    return markets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare KIS real-account holdings with Prism Insight DB holdings.")
    parser.add_argument("--apply", action="store_true", help="Apply safe add/update changes. Deletion is never automatic.")
    parser.add_argument("--db-path", default=str(DB_PATH), help="SQLite DB path.")
    parser.add_argument("--market", type=_parse_markets, default=["kr", "us"], help="all, kr, us, or comma-separated values.")
    parser.add_argument("--mode", choices=["real", "demo"], default=DEFAULT_MODE, help="KIS mode. Defaults to real.")
    parser.add_argument("--product", default=DEFAULT_PRODUCT, help="KIS account product code. Defaults to 01.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    markets = args.market

    if not db_path.exists():
        print(f"DB 파일을 찾을 수 없습니다: {db_path}", file=sys.stderr)
        return 2

    db_holdings, columns_by_market = read_db_holdings(db_path, markets)
    actual_holdings = fetch_actual_holdings(markets, args.mode, args.product)
    comparison = compare_holdings(actual_holdings, db_holdings, columns_by_market)
    print_report(comparison, columns_by_market, apply=args.apply)

    if args.apply:
        backup_path = apply_changes(db_path, comparison, columns_by_market)
        if backup_path:
            print(f"\nDB 백업 생성: {backup_path}")
        print("삭제 후보는 자동 삭제하지 않았습니다.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
