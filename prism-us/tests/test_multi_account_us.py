import atexit
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import time
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

PRISM_US_DIR = Path(__file__).parent.parent
PROJECT_ROOT = PRISM_US_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PRISM_US_DIR))

from order_ledger_safety import sanitize_order_payload, sanitize_reason

CONFIG_DIR = PROJECT_ROOT / "trading" / "config"
CONFIG_FILE = CONFIG_DIR / "kis_devlp.yaml"
_CREATED_TEST_CONFIG = False

if not CONFIG_FILE.exists():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        textwrap.dedent(
            """
            my_agent: test-agent
            default_mode: demo
            auto_trading: true
            default_product_code: "01"
            default_unit_amount: 100000
            default_unit_amount_usd: 250
            my_app: PSREALKEY
            my_sec: real-secret
            paper_app: PSVTTESTKEY
            paper_sec: paper-secret
            my_htsid: test-user
            prod: https://example.com
            vps: https://example.com
            ops: wss://example.com
            vops: wss://example.com
            accounts:
              - name: bootstrap-demo
                mode: demo
                account: "12345678"
                product: "01"
                market: us
                primary: true
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    _CREATED_TEST_CONFIG = True


if _CREATED_TEST_CONFIG:
    atexit.register(lambda: CONFIG_FILE.unlink(missing_ok=True))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


us_schema = _load_module("prism_us_tracking_db_schema", PRISM_US_DIR / "tracking" / "db_schema.py")
ust = _load_module("prism_us_us_stock_trading", PRISM_US_DIR / "trading" / "us_stock_trading.py")
pending_batch = _load_module("prism_us_pending_order_batch", PRISM_US_DIR / "us_pending_order_batch.py")
bootstrap_ledger = _load_module(
    "prism_us_bootstrap_us_order_ledger",
    PRISM_US_DIR / "bootstrap_us_order_ledger.py",
)


class FakeUSTrader:
    init_calls = []

    def __init__(
        self,
        mode=None,
        buy_amount=None,
        auto_trading=None,
        account_name=None,
        account_index=None,
        product_code="01",
    ):
        self.mode = mode or "demo"
        self.buy_amount = buy_amount
        self.auto_trading = auto_trading
        self.account_name = account_name
        self.account_index = account_index
        self.product_code = product_code
        self.account_key = f"vps:{account_name}:{product_code}" if account_name else "window-checker"
        type(self).init_calls.append(
            {
                "mode": self.mode,
                "buy_amount": buy_amount,
                "auto_trading": auto_trading,
                "account_name": account_name,
                "product_code": product_code,
            }
        )

    async def async_buy_stock(self, ticker, buy_amount=None, exchange=None, timeout=30.0, limit_price=None):
        success = self.account_name != "us-secondary"
        quantity = 1 if success else 0
        return {
            "success": success,
            "ticker": ticker,
            "quantity": quantity,
            "estimated_amount": quantity * 100.0,
            "message": "ok" if success else "rejected",
        }

    async def async_sell_stock(self, ticker, exchange=None, timeout=30.0, limit_price=None, use_moo=False):
        return {
            "success": True,
            "ticker": ticker,
            "quantity": 1,
            "estimated_amount": 100.0,
            "message": "sold",
        }

    def get_portfolio(self):
        return [{"account_name": self.account_name}]

    def get_account_summary(self):
        return {"account_name": self.account_name}

    def get_current_price(self, ticker, exchange=None):
        return {"ticker": ticker, "account_name": self.account_name}

    def calculate_buy_quantity(self, ticker, buy_amount=None, exchange=None):
        return 4

    def get_holding_quantity(self, ticker):
        return 2

    def is_reserved_order_available(self):
        return True

    def buy_reserved_order(self, ticker, limit_price, buy_amount=None, exchange=None, **kwargs):
        return {"success": True, "message": f"queued-buy-{self.account_name}", "ticker": ticker}

    def sell_reserved_order(self, ticker, limit_price=None, exchange=None):
        return {"success": True, "message": f"queued-sell-{self.account_name}", "ticker": ticker}


@pytest.fixture
def initialized_us_temp_database():
    temp_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    db_path = temp_file.name
    temp_file.close()

    cursor, conn = us_schema.initialize_us_database(db_path)
    try:
        yield cursor, conn, db_path
    finally:
        conn.close()
        path = Path(db_path)
        if path.exists():
            path.unlink()


@pytest.mark.asyncio
async def test_async_us_trading_context_returns_single_account_trader(monkeypatch):
    FakeUSTrader.init_calls = []
    monkeypatch.setattr(ust, "USStockTrading", FakeUSTrader)

    async with ust.AsyncUSTradingContext(mode="demo", buy_amount=150.0, account_name="us-main") as trader:
        assert isinstance(trader, FakeUSTrader)
        assert trader.account_name == "us-main"

    assert FakeUSTrader.init_calls == [
        {
            "mode": "demo",
            "buy_amount": 150.0,
            "auto_trading": ust.AsyncUSTradingContext.AUTO_TRADING,
            "account_name": "us-main",
            "product_code": "01",
        }
    ]


@pytest.mark.asyncio
async def test_multi_account_us_context_fans_out_orders_but_reads_primary(monkeypatch):
    FakeUSTrader.init_calls = []
    accounts = [
        {"name": "us-primary", "account_key": "vps:us-primary:01", "product": "01"},
        {"name": "us-secondary", "account_key": "vps:us-secondary:01", "product": "01"},
    ]
    monkeypatch.setattr(ust, "USStockTrading", FakeUSTrader)
    monkeypatch.setattr(ust.ka, "get_configured_accounts", lambda **kwargs: accounts)
    monkeypatch.setattr(ust.ka, "resolve_account", lambda **kwargs: accounts[0])

    async with ust.MultiAccountUSTradingContext(mode="demo", buy_amount=300.0) as trader:
        result = await trader.async_buy_stock("AAPL")

        assert result["success"] is False
        assert result["partial_success"] is True
        assert result["successful_accounts"] == ["us-primary"]
        assert result["failed_accounts"] == ["us-secondary"]
        assert [item["account_key"] for item in result["account_results"]] == [
            "vps:us-primary:01",
            "vps:us-secondary:01",
        ]
        assert trader.get_portfolio() == [{"account_name": "us-primary"}]
        assert trader.get_account_summary() == {"account_name": "us-primary"}
        assert trader.get_current_price("AAPL") == {"ticker": "AAPL", "account_name": "us-primary"}
        assert trader.calculate_buy_quantity("AAPL") == 4
        assert trader.get_holding_quantity("AAPL") == 2


def test_us_trader_uses_account_buy_amount_override(monkeypatch):
    account = {
        "name": "us-override",
        "account_key": "vps:90909090:01",
        "product": "01",
        "buy_amount_usd": 456.78,
    }
    monkeypatch.setattr(ust.ka, "resolve_account", lambda **kwargs: account)
    monkeypatch.setattr(ust.ka, "auth", lambda **kwargs: None)
    monkeypatch.setattr(
        ust.ka,
        "getTREnv",
        lambda: SimpleNamespace(my_acct="90909090", my_prod="01", my_token="token"),
    )

    trader = ust.USStockTrading(mode="demo", account_name="us-override")

    assert trader.buy_amount == 456.78
    assert trader.account_key == "vps:90909090:01"


def test_us_schema_migration_backfills_primary_account_scope(monkeypatch):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE us_stock_holdings (
            ticker TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            buy_price REAL NOT NULL,
            buy_date TEXT NOT NULL,
            current_price REAL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE us_pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            order_type TEXT NOT NULL,
            limit_price REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO us_stock_holdings (ticker, company_name, buy_price, buy_date, current_price)
        VALUES ('AAPL', 'Apple Inc.', 180.5, '2026-03-01', 185.0)
        """
    )
    cursor.execute(
        """
        INSERT INTO us_pending_orders (ticker, order_type, limit_price, created_at)
        VALUES ('MSFT', 'buy', 410.0, '2026-03-02 09:00:00')
        """
    )
    conn.commit()

    monkeypatch.setattr(
        us_schema,
        "_get_primary_account_scope",
        lambda: ("vps:us-primary:01", "US Primary", "01", "demo"),
    )

    us_schema.migrate_multi_account_schema(cursor, conn)

    cursor.execute("SELECT account_key, account_name, ticker FROM us_stock_holdings")
    assert cursor.fetchone() == ("vps:us-primary:01", "US Primary", "AAPL")

    cursor.execute("SELECT account_key, account_name, product_code, mode, ticker FROM us_pending_orders")
    assert cursor.fetchone() == ("vps:us-primary:01", "US Primary", "01", "demo", "MSFT")


def test_us_schema_migration_handles_quoted_account_names_retains_backups_and_preserves_ids(monkeypatch):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE us_stock_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            company_name TEXT NOT NULL,
            buy_price REAL NOT NULL,
            buy_date TEXT NOT NULL,
            current_price REAL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE us_pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            order_type TEXT NOT NULL,
            limit_price REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO us_stock_holdings (id, ticker, company_name, buy_price, buy_date, current_price)
        VALUES (7, 'AAPL', 'Apple Inc.', 180.5, '2026-03-01', 185.0)
        """
    )
    cursor.execute(
        """
        INSERT INTO us_pending_orders (ticker, order_type, limit_price, created_at)
        VALUES ('MSFT', 'buy', 410.0, '2026-03-02 09:00:00')
        """
    )
    conn.commit()

    monkeypatch.setattr(
        us_schema,
        "_get_primary_account_scope",
        lambda: ("vps:us-primary:01", "O'Brien US", "01", "demo"),
    )

    us_schema.migrate_multi_account_schema(cursor, conn)

    cursor.execute("SELECT id, account_key, account_name FROM us_stock_holdings")
    assert cursor.fetchone() == (7, "vps:us-primary:01", "O'Brien US")
    cursor.execute("SELECT account_key, account_name, product_code, mode FROM us_pending_orders")
    assert cursor.fetchone() == ("vps:us-primary:01", "O'Brien US", "01", "demo")
    assert us_schema._table_exists(cursor, "us_stock_holdings_pre_multi_account_backup")
    assert us_schema._table_exists(cursor, "us_pending_orders_pre_multi_account_backup")


def test_us_schema_recovers_interrupted_migration(monkeypatch):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE us_stock_holdings_legacy (
            ticker TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            buy_price REAL NOT NULL,
            buy_date TEXT NOT NULL,
            current_price REAL
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO us_stock_holdings_legacy (ticker, company_name, buy_price, buy_date, current_price)
        VALUES ('AAPL', 'Apple Inc.', 180.5, '2026-03-01', 185.0)
        """
    )
    cursor.execute(us_schema.TABLE_US_STOCK_HOLDINGS)
    conn.commit()

    monkeypatch.setattr(
        us_schema,
        "_get_primary_account_scope",
        lambda: ("vps:us-primary:01", "US Primary", "01", "demo"),
    )

    us_schema.migrate_multi_account_schema(cursor, conn)

    cursor.execute("SELECT account_key, account_name, ticker FROM us_stock_holdings")
    assert cursor.fetchone() == ("vps:us-primary:01", "US Primary", "AAPL")
    assert not us_schema._table_exists(cursor, "us_stock_holdings_legacy")


def test_us_schema_requires_primary_account_when_migration_needed(monkeypatch):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE us_stock_holdings (
            ticker TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            buy_price REAL NOT NULL,
            buy_date TEXT NOT NULL,
            current_price REAL
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO us_stock_holdings (ticker, company_name, buy_price, buy_date, current_price)
        VALUES ('AAPL', 'Apple Inc.', 180.5, '2026-03-01', 185.0)
        """
    )
    conn.commit()

    def _raise_scope_error():
        raise RuntimeError("KIS auth unavailable")

    monkeypatch.setattr(us_schema, "_get_primary_account_scope", _raise_scope_error)

    with pytest.raises(RuntimeError, match="KIS auth unavailable"):
        us_schema.migrate_multi_account_schema(cursor, conn)

    cursor.execute("PRAGMA table_info(us_stock_holdings)")
    assert "account_key" not in {row[1] for row in cursor.fetchall()}


def test_us_schema_loads_root_kis_auth_even_when_prism_us_precedes_sys_path():
    module = us_schema._load_root_kis_auth_module()
    monkeypatch = pytest.MonkeyPatch()

    try:
        assert Path(module.__file__).resolve() == (PROJECT_ROOT / "trading" / "kis_auth.py").resolve()
        monkeypatch.setattr(module, "getEnv", lambda: {"default_mode": "demo"})
        monkeypatch.setattr(
            module,
            "resolve_account",
            lambda **kwargs: {
                "svr": "vps",
                "account_key": "vps:us-primary:01",
                "name": "US Primary",
                "product": "01",
            },
        )

        original_path = list(sys.path)
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            sys.path.insert(0, str(PRISM_US_DIR))
            scope = us_schema._get_primary_account_scope()
        finally:
            sys.path[:] = original_path

        assert scope == ("vps:us-primary:01", "US Primary", "01", "demo")
    finally:
        monkeypatch.undo()


def test_us_schema_skips_scope_resolution_when_already_migrated(monkeypatch):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    us_schema.create_us_tables(cursor, conn)

    def _raise_scope_error():
        raise AssertionError("Primary account resolution should not be called")

    monkeypatch.setattr(us_schema, "_get_primary_account_scope", _raise_scope_error)

    us_schema.migrate_multi_account_schema(cursor, conn)


def test_initialize_us_database_runs_multi_account_migration_once(monkeypatch):
    calls = []
    temp_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()

    def fake_migration(cursor, conn):
        calls.append("migrated")

    monkeypatch.setattr(us_schema, "migrate_multi_account_schema", fake_migration)

    cursor, conn = us_schema.initialize_us_database(str(temp_path))
    try:
        assert calls == ["migrated"]
    finally:
        conn.close()
        temp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_async_initialize_us_database_migrates_legacy_schema(monkeypatch):
    temp_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()

    try:
        conn = sqlite3.connect(str(temp_path))
        conn.execute(
            """
            CREATE TABLE us_stock_holdings (
                ticker TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                buy_price REAL NOT NULL,
                buy_date TEXT NOT NULL,
                current_price REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO us_stock_holdings (ticker, company_name, buy_price, buy_date, current_price)
            VALUES ('AAPL', 'Apple Inc.', 180.5, '2026-03-01', 185.0)
            """
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(
            us_schema,
            "_get_primary_account_scope",
            lambda: ("vps:us-primary:01", "US Primary", "01", "demo"),
        )

        async_conn = await us_schema.async_initialize_us_database(str(temp_path))
        async_cursor = await async_conn.execute(
            "SELECT account_key, account_name, ticker FROM us_stock_holdings"
        )
        row = await async_cursor.fetchone()
        await async_cursor.close()
        await async_conn.close()

        assert row == ("vps:us-primary:01", "US Primary", "AAPL")
    finally:
        temp_path.unlink(missing_ok=True)


def test_us_schema_allows_same_ticker_across_accounts(initialized_us_temp_database):
    cursor, conn, _ = initialized_us_temp_database

    cursor.executemany(
        """
        INSERT INTO us_stock_holdings
        (account_key, account_name, ticker, company_name, buy_price, buy_date, current_price)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("vps:us-one:01", "US One", "AAPL", "Apple Inc.", 180.5, "2026-03-01", 185.0),
            ("vps:us-two:01", "US Two", "AAPL", "Apple Inc.", 181.0, "2026-03-02", 186.0),
        ],
    )
    conn.commit()

    assert us_schema.get_us_holdings_count(cursor, account_key="vps:us-one:01") == 1
    assert us_schema.get_us_holdings_count(cursor, account_key="vps:us-two:01") == 1
    assert us_schema.is_us_ticker_in_holdings(cursor, "AAPL", account_key="vps:us-one:01") is True
    assert us_schema.is_us_ticker_in_holdings(cursor, "AAPL", account_key="vps:us-two:01") is True


def test_us_order_ledger_unique_active_buy(initialized_us_temp_database):
    cursor, conn, _ = initialized_us_temp_database

    cursor.execute(
        """
        INSERT INTO us_order_ledger
        (account_key, ticker, side, status, source, created_at, updated_at)
        VALUES ('vps:us-one:01', 'AAPL', 'buy', 'queued', 'pending_queue', '2099-01-01', '2099-01-01')
        """
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO us_order_ledger
            (account_key, ticker, side, status, source, created_at, updated_at)
            VALUES ('vps:us-one:01', 'AAPL', 'buy', 'open', 'kis_open_orders', '2099-01-01', '2099-01-01')
            """
        )


def test_us_schema_raises_when_critical_active_buy_index_cannot_be_created(monkeypatch):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE ledger_guard (account_key TEXT, ticker TEXT)")
    cursor.executemany(
        "INSERT INTO ledger_guard VALUES (?, ?)",
        [("acct", "AAPL"), ("acct", "AAPL")],
    )
    conn.commit()
    monkeypatch.setattr(
        us_schema,
        "US_INDEXES",
        [
            "CREATE UNIQUE INDEX ux_us_order_ledger_active_buy_v2 "
            "ON ledger_guard(account_key, ticker)"
        ],
    )

    with pytest.raises(sqlite3.IntegrityError):
        us_schema.create_us_indexes(cursor, conn)

    conn.close()


def test_bootstrap_pending_orders_to_ledger_blocks_legacy_pending(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE us_pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_key TEXT NOT NULL,
            account_name TEXT,
            product_code TEXT,
            mode TEXT,
            ticker TEXT NOT NULL,
            order_type TEXT NOT NULL,
            limit_price REAL NOT NULL,
            buy_amount REAL,
            exchange TEXT,
            status TEXT DEFAULT 'pending',
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            executed_at TEXT,
            order_result TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO us_pending_orders
        (account_key, account_name, product_code, mode, ticker, order_type, limit_price, buy_amount, exchange, created_at)
        VALUES ('vps:us-one:01', 'US One', '01', 'demo', 'AAPL', 'buy', 190.0, 500.0, 'NASD', '2099-01-01')
        """
    )
    conn.commit()

    assert ust._bootstrap_pending_orders_to_ledger(conn) == 1
    row = conn.execute(
        "SELECT status, source, pending_order_id FROM us_order_ledger WHERE account_key='vps:us-one:01' AND ticker='AAPL'"
    ).fetchone()
    assert row == ("queued", "pending_queue", 1)
    conn.close()


def _bare_us_trader():
    trader = ust.USStockTrading.__new__(ust.USStockTrading)
    trader.account_key = "vps:us-one:01"
    trader.account_name = "US One"
    trader.product_code = "01"
    trader.mode = "demo"
    return trader


def test_preflight_buy_guard_fail_closed_on_unverified_open_orders(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    monkeypatch.setattr(ust, "_order_ledger_db_path", lambda: db_path)
    trader = _bare_us_trader()

    def fake_unfilled(*args, **kwargs):
        trader._last_unfilled_order_inquiry_ok = False
        return []

    trader.get_unfilled_orders = fake_unfilled

    result = trader._preflight_buy_order_guard("AAPL")

    assert result is not None
    assert result["success"] is False
    assert "could not verify KIS open orders" in result["message"]


def test_preflight_buy_guard_bootstraps_live_open_buy(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    monkeypatch.setattr(ust, "_order_ledger_db_path", lambda: db_path)
    trader = _bare_us_trader()

    def fake_unfilled(*args, **kwargs):
        trader._last_unfilled_order_inquiry_ok = True
        return [
            {
                "order_no": "KIS123",
                "ticker": "AAPL",
                "nccs_qty": 3,
                "ord_unpr": 190.0,
                "sll_buy_dvsn_cd": "02",
                "exchange": "NASD",
            }
        ]

    trader.get_unfilled_orders = fake_unfilled

    result = trader._preflight_buy_order_guard("AAPL")

    assert result is not None
    assert result["success"] is False
    assert "active buy order exists" in result["message"]

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, source, order_no FROM us_order_ledger WHERE account_key='vps:us-one:01' AND ticker='AAPL'"
    ).fetchone()
    conn.close()
    assert row == ("open", "kis_open_orders", "KIS123")


def test_missing_open_order_stays_active_until_execution_history_verifies_closure(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    monkeypatch.setattr(ust, "_order_ledger_db_path", lambda: db_path)
    trader = _bare_us_trader()

    conn = sqlite3.connect(str(db_path))
    ust._ensure_us_order_ledger(conn)
    ust._record_us_order_ledger(
        conn,
        account_key=trader.account_key,
        ticker="AAPL",
        side="buy",
        status="open",
        source="kis_open_orders",
        order_no="KIS123",
    )

    trader._reconcile_active_buy_ledger(conn, "AAPL", set())

    row = conn.execute(
        "SELECT status FROM us_order_ledger WHERE order_no = 'KIS123'"
    ).fetchone()
    active = trader._get_active_buy_ledger_row(conn, "AAPL")
    conn.close()

    assert row == ("closed_unverified",)
    assert active is not None
    assert active["status"] == "closed_unverified"


def test_bootstrap_dry_run_does_not_modify_database(tmp_path):
    db_path = tmp_path / "orders.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE us_pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_key TEXT NOT NULL,
            account_name TEXT,
            product_code TEXT,
            mode TEXT,
            ticker TEXT NOT NULL,
            order_type TEXT NOT NULL,
            limit_price REAL NOT NULL,
            buy_amount REAL,
            exchange TEXT,
            status TEXT DEFAULT 'pending',
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            executed_at TEXT,
            order_result TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO us_pending_orders
        (account_key, ticker, order_type, limit_price, created_at)
        VALUES ('vps:us-one:01', 'AAPL', 'buy', 190.0, '2099-01-01')
        """
    )
    conn.commit()
    conn.close()
    before = db_path.read_bytes()

    assert bootstrap_ledger.bootstrap("demo", "01", db_path, apply=False) == 0

    assert db_path.read_bytes() == before
    conn = sqlite3.connect(str(db_path))
    ledger_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='us_order_ledger'"
    ).fetchone()
    conn.close()
    assert ledger_table is None


def test_bootstrap_apply_query_failure_leaves_database_unchanged(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE us_pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_key TEXT NOT NULL,
            account_name TEXT,
            product_code TEXT,
            mode TEXT,
            ticker TEXT NOT NULL,
            order_type TEXT NOT NULL,
            limit_price REAL NOT NULL,
            buy_amount REAL,
            exchange TEXT,
            status TEXT DEFAULT 'pending',
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            executed_at TEXT,
            order_result TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO us_pending_orders
        (account_key, ticker, order_type, limit_price, created_at)
        VALUES ('vps:us-one:01', 'AAPL', 'buy', 190.0, '2099-01-01')
        """
    )
    conn.commit()
    conn.close()
    before = db_path.read_bytes()

    accounts = [
        {"name": "ok-account", "product": "01"},
        {"name": "failed-account", "product": "01"},
    ]
    monkeypatch.setattr(
        bootstrap_ledger.ust.ka,
        "get_configured_accounts",
        lambda **kwargs: accounts,
    )

    class BootstrapTrader:
        def __init__(self, mode, account_name, product_code):
            self.mode = mode
            self.account_name = account_name
            self.product_code = product_code
            self.account_key = f"vps:{account_name}:{product_code}"
            self._last_unfilled_order_inquiry_ok = False

        def get_unfilled_orders(self, exchange=None):
            self._last_unfilled_order_inquiry_ok = self.account_name == "ok-account"
            return []

    monkeypatch.setattr(bootstrap_ledger.ust, "USStockTrading", BootstrapTrader)

    assert bootstrap_ledger.bootstrap("demo", "01", db_path, apply=True) == 2
    assert db_path.read_bytes() == before


def test_pending_batch_dry_run_does_not_expire_or_create_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE us_pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_key TEXT NOT NULL,
            account_name TEXT,
            product_code TEXT,
            mode TEXT,
            ticker TEXT NOT NULL,
            order_type TEXT NOT NULL,
            limit_price REAL NOT NULL,
            buy_amount REAL,
            exchange TEXT,
            status TEXT DEFAULT 'pending',
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            executed_at TEXT,
            order_result TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO us_pending_orders
        (account_key, ticker, order_type, limit_price, status, created_at)
        VALUES ('vps:us-one:01', 'AAPL', 'buy', 190.0, 'pending', '2000-01-01')
        """
    )
    conn.commit()
    conn.close()
    before = db_path.read_bytes()
    monkeypatch.setattr(pending_batch, "DB_PATH", db_path)

    pending_batch.process_pending_orders(dry_run=True)

    assert db_path.read_bytes() == before
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT status FROM us_pending_orders").fetchone() == ("pending",)
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='us_order_ledger'"
    ).fetchone() is None
    conn.close()


def test_pending_and_ledger_status_update_rolls_back_together(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    conn = sqlite3.connect(str(db_path))
    us_schema.create_us_tables(conn.cursor(), conn)
    conn.execute(
        """
        INSERT INTO us_pending_orders
        (account_key, ticker, order_type, limit_price, status, created_at)
        VALUES ('vps:us-one:01', 'AAPL', 'buy', 190.0, 'pending', '2099-01-01')
        """
    )
    conn.commit()
    order = {
        "id": 1,
        "account_key": "vps:us-one:01",
        "ticker": "AAPL",
        "order_type": "buy",
        "limit_price": 190.0,
    }

    monkeypatch.setattr(
        pending_batch,
        "sync_ledger_for_pending_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected crash")),
    )

    with pytest.raises(RuntimeError, match="injected crash"):
        pending_batch.update_order_and_ledger_status(
            conn,
            order,
            "executed",
            result={"success": True, "order_no": "KIS123"},
        )

    assert conn.execute("SELECT status FROM us_pending_orders WHERE id = 1").fetchone() == ("pending",)
    conn.close()


def test_direct_buy_submission_requires_matching_claim_before_request():
    trader = _bare_us_trader()
    trader.auto_trading = True
    trader.mode = "demo"
    trader.buy_amount = 1000.0
    trader.trenv = SimpleNamespace(my_acct="00000000", my_prod="01")
    request_calls = []

    def forbidden_request(*args, **kwargs):
        request_calls.append((args, kwargs))
        raise AssertionError("KIS request must not run without a claim")

    trader._request = forbidden_request

    result = trader.buy_limit_price("AAPL", 100.0, 1000.0, "NASD")

    assert result["success"] is False
    assert "submission claim" in result["message"].lower()
    assert request_calls == []


def test_direct_buy_with_matching_claim_reaches_request(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    monkeypatch.setattr(ust, "_order_ledger_db_path", lambda: db_path)
    trader = _bare_us_trader()
    trader.auto_trading = True
    trader.mode = "demo"
    trader.buy_amount = 1000.0
    trader.trenv = SimpleNamespace(my_acct="00000000", my_prod="01")
    ledger_id = trader._claim_buy_submission("AAPL", 10, 100.0, "NASD")
    assert ledger_id is not None
    request_calls = []

    class AcceptedResponse:
        def isOK(self):
            return True

        def getBody(self):
            return SimpleNamespace(output={"ODNO": "KIS-CLAIMED"})

    def accepted_request(*args, **kwargs):
        request_calls.append((args, kwargs))
        return AcceptedResponse()

    trader._request = accepted_request

    result = trader.buy_limit_price(
        "AAPL",
        100.0,
        1000.0,
        "NASD",
        submission_ledger_id=ledger_id,
    )

    assert result["success"] is True
    assert result["order_no"] == "KIS-CLAIMED"
    assert len(request_calls) == 1


def test_forced_reserved_route_requires_matching_claim_before_request():
    trader = _bare_us_trader()
    trader.auto_trading = True
    trader.mode = "demo"
    trader.buy_amount = 1000.0
    trader.trenv = SimpleNamespace(my_acct="00000000", my_prod="01")
    request_calls = []

    def forbidden_request(*args, **kwargs):
        request_calls.append((args, kwargs))
        raise AssertionError("KIS request must not run without a claim")

    trader._request = forbidden_request

    result = trader.smart_buy(
        "AAPL",
        1000.0,
        "NASD",
        100.0,
        route="direct_reserved",
    )

    assert result["success"] is False
    assert "submission claim" in result["message"].lower()
    assert request_calls == []


def test_sanitizer_masks_key_value_credentials_and_allowlisted_message():
    basic_value = "".join(("QWxhZGRp", "bjpvcGVu", "IHNlc2FtZQ=="))
    header_name = "".join(("Author", "ization"))
    auth_scheme = "".join(("Bas", "ic"))
    basic_header = f"{header_name}: {auth_scheme} {basic_value}"
    secret_message = " ".join(
        (
            "authorization=secret-token-abc",
            "app_secret=my-secret-value",
            "access_token=abc.def.ghi",
            "account=1234-5678-90",
            basic_header,
            '"refresh_token": "json-refresh-secret"',
            "htsid=test-user-id",
        )
    )
    assert basic_value in secret_message
    assert basic_header in secret_message

    reason = sanitize_reason(secret_message)
    payload = sanitize_order_payload({"order_no": "123", "message": secret_message})
    assert reason is not None
    assert payload is not None

    for secret in (
        "secret-token-abc",
        "my-secret-value",
        "abc.def.ghi",
        "1234-5678-90",
        basic_value,
        "json-refresh-secret",
        "test-user-id",
    ):
        assert secret not in reason
        assert secret not in payload["message"]
    assert payload["order_no"] == "123"


def test_pending_queue_exception_is_sanitized_before_log_and_result(monkeypatch, caplog):
    trader = _bare_us_trader()
    secret = "authorization=secret-token-abc"

    def fail_connect(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    caplog.set_level("ERROR")

    result = trader._queue_pending_order(
        ticker="AAPL",
        order_type="buy",
        limit_price=100.0,
        buy_amount=500.0,
        exchange="NASD",
    )

    assert result["success"] is False
    assert "secret-token-abc" not in result["message"]
    assert "secret-token-abc" not in caplog.text
    assert "[REDACTED]" in result["message"]
    assert "[REDACTED]" in caplog.text


def test_order_ledger_persists_only_sanitized_broker_fields(tmp_path):
    db_path = tmp_path / "orders.sqlite"
    conn = sqlite3.connect(str(db_path))

    ust._record_us_order_ledger(
        conn,
        account_key="vps:us-one:01",
        ticker="AAPL",
        side="buy",
        status="submitted",
        source="kis_submit",
        raw_order={
            "order_no": "KIS123",
            "response_code": "0",
            "message": "accepted",
            "ticker": "AAPL",
            "exchange": "NASD",
            "requested_quantity": 2,
            "requested_price": 190.0,
            "filled_quantity": 0,
            "account_number": "12345678",
            "authorization": "Bearer secret-token",
            "app_secret": "secret",
        },
    )

    payload = conn.execute("SELECT raw_order_json FROM us_order_ledger").fetchone()[0]
    conn.close()

    assert payload is not None
    assert json.loads(payload) == {
        "order_no": "KIS123",
        "response_code": "0",
        "message": "accepted",
        "ticker": "AAPL",
        "exchange": "NASD",
        "requested_quantity": 2,
        "requested_price": 190.0,
        "filled_quantity": 0,
    }


def test_pending_queue_creation_rolls_back_if_ledger_insert_crashes(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: real_connect(str(db_path)))
    monkeypatch.setattr(
        ust,
        "_record_us_order_ledger",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected crash")),
    )
    trader = _bare_us_trader()

    result = trader._queue_pending_order("AAPL", "buy", 190.0, 500.0, "NASD")

    assert result["success"] is False
    conn = real_connect(str(db_path))
    pending_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='us_pending_orders'"
    ).fetchone()
    pending_count = 0 if pending_table is None else conn.execute(
        "SELECT COUNT(*) FROM us_pending_orders"
    ).fetchone()[0]
    conn.close()
    assert pending_count == 0


def test_concurrent_active_buy_inserts_leave_only_one_row(initialized_us_temp_database):
    _cursor, conn, db_path = initialized_us_temp_database
    conn.commit()
    barrier = threading.Barrier(2)
    outcomes = []

    def insert(source):
        worker_conn = sqlite3.connect(db_path, timeout=5)
        try:
            barrier.wait()
            ust._record_us_order_ledger(
                worker_conn,
                account_key="vps:us-one:01",
                ticker="AAPL",
                side="buy",
                status="open",
                source=source,
            )
            outcomes.append("inserted")
        except (sqlite3.IntegrityError, sqlite3.OperationalError):
            outcomes.append("blocked")
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=insert, args=(f"worker-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["blocked", "inserted"]
    assert conn.execute(
        "SELECT COUNT(*) FROM us_order_ledger WHERE account_key='vps:us-one:01' AND ticker='AAPL'"
    ).fetchone() == (1,)


def test_concurrent_submission_claim_only_one_wins(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    monkeypatch.setattr(ust, "_order_ledger_db_path", lambda: db_path)
    barrier = threading.Barrier(2)
    claims = []

    def claim():
        trader = _bare_us_trader()
        barrier.wait()
        claims.append(trader._claim_buy_submission("AAPL", 2, 190.0, "NASD"))

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert sum(claim is not None for claim in claims) == 1
    conn = sqlite3.connect(str(db_path))
    assert conn.execute(
        "SELECT status, COUNT(*) FROM us_order_ledger GROUP BY status"
    ).fetchone() == ("submitting", 1)
    conn.close()


@pytest.mark.asyncio
async def test_async_buy_timeout_after_claim_stays_submission_uncertain(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    monkeypatch.setattr(ust, "_order_ledger_db_path", lambda: db_path)
    trader = _bare_us_trader()
    trader.buy_amount = 500.0
    trader._global_lock = ust.asyncio.Lock()
    trader._semaphore = ust.asyncio.Semaphore(1)
    trader._stock_locks = {}
    trader._preflight_buy_order_guard = lambda *args, **kwargs: None
    trader.get_current_price = lambda *args, **kwargs: {"current_price": 100.0}
    trader.is_market_open = lambda: True
    trader.is_reserved_order_available = lambda: False

    def slow_submission(*args, **kwargs):
        time.sleep(0.2)
        return {"success": True, "order_no": "KIS-LATE", "message": "accepted"}

    trader.smart_buy = slow_submission

    async def no_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(ust.asyncio, "sleep", no_sleep)

    result = await trader.async_buy_stock("AAPL", timeout=0.05, exchange="NASD")

    assert result["success"] is False
    assert "timeout" in result["message"].lower()
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT status, quarantine_reason FROM us_order_ledger WHERE ticker='AAPL'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "submission_uncertain"
    assert "timed out" in row[1]


@pytest.mark.asyncio
async def test_async_buy_uses_single_routing_snapshot_at_time_boundary(monkeypatch):
    trader = _bare_us_trader()
    trader.buy_amount = 500.0
    trader._global_lock = ust.asyncio.Lock()
    trader._semaphore = ust.asyncio.Semaphore(1)
    trader._stock_locks = {}
    trader._preflight_buy_order_guard = lambda *args, **kwargs: None
    trader.get_current_price = lambda *args, **kwargs: {"current_price": 100.0}
    trader.is_market_open = lambda: False
    availability_calls = []

    def changing_reserved_window():
        availability_calls.append(True)
        return len(availability_calls) > 1

    trader.is_reserved_order_available = changing_reserved_window
    trader._claim_buy_submission = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("local queue route must not claim direct KIS submission")
    )
    captured = {}

    def routed_buy(*args, **kwargs):
        captured["route"] = kwargs.get("route")
        return {
            "success": True,
            "order_no": "PENDING-1",
            "order_type": "queued_buy",
            "message": "queued",
        }

    trader.smart_buy = routed_buy
    trader._record_successful_buy_order = lambda *args, **kwargs: None

    async def no_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(ust.asyncio, "sleep", no_sleep)

    result = await trader._execute_buy_stock("AAPL", exchange="NASD")

    assert result["success"] is True
    assert captured["route"] == "local_queue"
    assert len(availability_calls) == 1


def test_concurrent_pending_batch_claim_only_one_worker_wins(tmp_path):
    db_path = tmp_path / "orders.sqlite"
    conn = sqlite3.connect(str(db_path))
    us_schema.create_us_tables(conn.cursor(), conn)
    conn.execute(
        """
        INSERT INTO us_pending_orders
        (account_key, ticker, order_type, limit_price, status, created_at)
        VALUES ('vps:us-one:01', 'AAPL', 'buy', 190.0, 'pending', '2099-01-01')
        """
    )
    pending_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    ust._record_us_order_ledger(
        conn,
        account_key="vps:us-one:01",
        ticker="AAPL",
        side="buy",
        status="queued",
        source="pending_queue",
        pending_order_id=pending_id,
    )
    conn.close()
    order = {
        "id": pending_id,
        "account_key": "vps:us-one:01",
        "ticker": "AAPL",
        "order_type": "buy",
    }
    barrier = threading.Barrier(2)
    claims = []

    def claim():
        worker_conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            barrier.wait()
            claims.append(pending_batch.claim_pending_order(worker_conn, order))
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert claims.count(None) == 1
    winning_claims = [claim_id for claim_id in claims if claim_id is not None]
    assert len(winning_claims) == 1
    assert isinstance(winning_claims[0], int) and winning_claims[0] > 0
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT status FROM us_pending_orders WHERE id = ?", (pending_id,)).fetchone() == ("processing",)
    assert conn.execute("SELECT status FROM us_order_ledger WHERE pending_order_id = ?", (pending_id,)).fetchone() == ("submitting",)
    conn.close()


def test_expire_old_orders_rolls_back_pending_and_ledger_together(tmp_path, monkeypatch):
    db_path = tmp_path / "orders.sqlite"
    conn = sqlite3.connect(str(db_path))
    us_schema.create_us_tables(conn.cursor(), conn)
    conn.execute(
        """
        INSERT INTO us_pending_orders
        (account_key, ticker, order_type, limit_price, status, created_at)
        VALUES ('vps:us-one:01', 'AAPL', 'buy', 190.0, 'pending', '2000-01-01')
        """
    )
    conn.commit()
    monkeypatch.setattr(
        pending_batch,
        "ensure_order_ledger",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected expiry crash")),
    )

    with pytest.raises(RuntimeError, match="injected expiry crash"):
        pending_batch.expire_old_orders(conn, "2099-01-01")

    assert conn.execute("SELECT status FROM us_pending_orders").fetchone() == ("pending",)
    conn.close()


def test_pending_batch_ambiguous_failure_classification():
    assert pending_batch.submission_failure_status(
        {"message": "Reserved buy order error: connection reset by peer"}
    ) == "submission_uncertain"
    assert pending_batch.submission_failure_status(
        {"message": "Reserved buy order failed: APBK0952 - insufficient funds"}
    ) == "failed"


def test_pending_order_batch_uses_stored_account_context(monkeypatch):
    temp_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()

    try:
        conn = sqlite3.connect(str(temp_path))
        conn.execute(
            """
            CREATE TABLE us_pending_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_key TEXT NOT NULL,
                account_name TEXT,
                product_code TEXT,
                mode TEXT,
                ticker TEXT NOT NULL,
                order_type TEXT NOT NULL,
                limit_price REAL NOT NULL,
                buy_amount REAL,
                exchange TEXT,
                status TEXT DEFAULT 'pending',
                failure_reason TEXT,
                created_at TEXT NOT NULL,
                executed_at TEXT,
                order_result TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO us_pending_orders
            (account_key, account_name, product_code, mode, ticker, order_type, limit_price, buy_amount, exchange, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                "vps:batch-account:01",
                "batch-account",
                "03",
                "real",
                "AAPL",
                "buy",
                190.0,
                500.0,
                "NASD",
                "2099-03-27 10:00:00",
            ),
        )
        conn.commit()
        conn.close()

        FakeUSTrader.init_calls = []
        monkeypatch.setattr(pending_batch, "DB_PATH", temp_path)
        monkeypatch.setattr(ust, "USStockTrading", FakeUSTrader)
        trading_package = sys.modules.get("trading")
        if trading_package is None:
            trading_package = _load_module("trading", PROJECT_ROOT / "trading" / "__init__.py")
        monkeypatch.setitem(sys.modules, "trading.us_stock_trading", ust)
        monkeypatch.setattr(trading_package, "us_stock_trading", ust, raising=False)

        frozen_now = ust.datetime.datetime(2099, 3, 27, 10, 5, 0, tzinfo=pending_batch.KST)

        class FrozenDateTime(ust.datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen_now if tz else frozen_now.replace(tzinfo=None)

        monkeypatch.setattr(pending_batch.datetime, "datetime", FrozenDateTime)

        pending_batch.process_pending_orders(dry_run=False)

        assert any(
            call["account_name"] is None for call in FakeUSTrader.init_calls
        )
        assert {
            "mode": "real",
            "buy_amount": None,
            "auto_trading": None,
            "account_name": "batch-account",
            "product_code": "03",
        } in FakeUSTrader.init_calls

        conn = sqlite3.connect(str(temp_path))
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM us_pending_orders WHERE ticker = 'AAPL'")
        assert cursor.fetchone()[0] == "executed"
        conn.close()
    finally:
        if temp_path.exists():
            temp_path.unlink()
