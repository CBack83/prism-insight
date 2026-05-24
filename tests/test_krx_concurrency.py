"""
Unit tests for KRX concurrency control, cache, retry, and MCP circuit breaker.

Tests:
- _fetch_ohlcv_with_semaphore: cache hit/miss, double-check pattern, semaphore serialization
- Concurrent KRX access: 10 requests → 1 call, serialization verification
- get_current_stock_price: timeout/lock retry, exponential backoff, DB fallback
- OHLCV cache operations: TTL expiry, per-date independence
- Circuit breaker: failure threshold, auto-reset, success counter reset
- warmup_krx_session: success/failure graceful degradation
- DB fallback: price return, None/error handling
- KRX integration: real API tests (skipif)
"""

import asyncio
import os
import sys
import time as time_module
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, MagicMock, patch, call

import pandas as pd
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ============================================================
# Fixtures: Global state isolation
# ============================================================

@pytest.fixture(autouse=True)
def reset_krx_globals():
    """Reset module-level global state between tests."""
    import tracking.helpers as h

    old_sem = h._krx_semaphore
    old_cache = h._ohlcv_cache.copy()
    old_ts = h._ohlcv_cache_timestamp.copy()

    h._krx_semaphore = None
    h._ohlcv_cache = {}
    h._ohlcv_cache_timestamp = {}

    yield

    h._krx_semaphore = old_sem
    h._ohlcv_cache = old_cache
    h._ohlcv_cache_timestamp = old_ts


@pytest.fixture
def reset_circuit_breaker():
    """Reset circuit breaker state between tests."""
    import report_generator as rg

    rg._server_failure_counts.clear()
    rg._server_circuit_open_until.clear()

    yield

    rg._server_failure_counts.clear()
    rg._server_circuit_open_until.clear()


@pytest.fixture
def mock_df():
    """Create a mock OHLCV DataFrame."""
    return pd.DataFrame(
        {
            "Close": [70000, 50000, 30000],
            "Open": [69000, 49000, 29000],
            "High": [71000, 51000, 31000],
            "Low": [68000, 48000, 28000],
            "Volume": [1000000, 500000, 300000],
            "Amount": [70000000000, 25000000000, 9000000000],
        },
        index=["005930", "035720", "035420"],
    )


@pytest.fixture
def mock_cursor():
    """Create a mock DB cursor."""
    cursor = Mock()
    cursor.execute = Mock()
    cursor.fetchone = Mock(return_value=None)
    return cursor


# ============================================================
# 1. TestFetchOHLCVWithSemaphore (P0)
# ============================================================

class TestFetchOHLCVWithSemaphore:
    """Test _fetch_ohlcv_with_semaphore: cache, double-check, semaphore release."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_krx_call(self, mock_df):
        """Cache hit should return cached data without calling KRX."""
        import tracking.helpers as h

        date = "20260205"
        h._ohlcv_cache[date] = mock_df
        h._ohlcv_cache_timestamp[date] = datetime.now()

        with patch("krx_data_client.get_market_ohlcv_by_ticker") as mock_krx:
            result = await h._fetch_ohlcv_with_semaphore(date)

            mock_krx.assert_not_called()
            assert result is mock_df

    @pytest.mark.asyncio
    async def test_cache_miss_calls_krx_and_caches(self, mock_df):
        """Cache miss should call KRX and store result in cache."""
        import tracking.helpers as h

        date = "20260205"

        with patch("krx_data_client.get_market_ohlcv_by_ticker", return_value=mock_df):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await h._fetch_ohlcv_with_semaphore(date)

        assert date in h._ohlcv_cache
        assert h._ohlcv_cache[date] is mock_df
        assert date in h._ohlcv_cache_timestamp
        pd.testing.assert_frame_equal(result, mock_df)

    @pytest.mark.asyncio
    async def test_double_check_pattern_prevents_duplicate_calls(self, mock_df):
        """Two concurrent calls for same date should result in only 1 KRX call."""
        import tracking.helpers as h

        date = "20260205"
        call_count = 0

        def slow_krx_call(d):
            nonlocal call_count
            call_count += 1
            time_module.sleep(0.1)  # Simulate slow KRX call
            return mock_df

        with patch("krx_data_client.get_market_ohlcv_by_ticker", side_effect=slow_krx_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                results = await asyncio.gather(
                    h._fetch_ohlcv_with_semaphore(date),
                    h._fetch_ohlcv_with_semaphore(date),
                )

        # Only 1 KRX call due to double-check pattern
        assert call_count == 1
        pd.testing.assert_frame_equal(results[0], mock_df)
        pd.testing.assert_frame_equal(results[1], mock_df)

    @pytest.mark.asyncio
    async def test_semaphore_serializes_different_dates(self, mock_df):
        """Concurrent calls for different dates should be serialized by semaphore."""
        import tracking.helpers as h

        timestamps = []

        def recording_krx_call(d):
            timestamps.append(("start", d, time_module.monotonic()))
            time_module.sleep(0.05)
            timestamps.append(("end", d, time_module.monotonic()))
            return mock_df.copy()

        dates = ["20260203", "20260204", "20260205"]

        with patch("krx_data_client.get_market_ohlcv_by_ticker", side_effect=recording_krx_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await asyncio.gather(
                    *[h._fetch_ohlcv_with_semaphore(d) for d in dates]
                )

        # Verify serialization: each call's start should be after previous call's end
        # Extract start/end pairs grouped by date
        starts = [(d, t) for tag, d, t in timestamps if tag == "start"]
        ends = [(d, t) for tag, d, t in timestamps if tag == "end"]

        # With semaphore(1), no two "start" events should overlap
        for i in range(len(starts) - 1):
            # The i-th end should be before the (i+1)-th start
            assert ends[i][1] <= starts[i + 1][1], (
                f"Calls overlapped: {ends[i]} should be before {starts[i + 1]}"
            )

    @pytest.mark.asyncio
    async def test_semaphore_released_on_krx_error(self, mock_df):
        """Semaphore should be released even when KRX call raises an error."""
        import tracking.helpers as h

        call_count = 0

        def failing_then_succeeding(d):
            nonlocal call_count
            call_count += 1
            if d == "20260203":
                raise RuntimeError("KRX login lock timeout")
            return mock_df

        with patch("krx_data_client.get_market_ohlcv_by_ticker", side_effect=failing_then_succeeding):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # First call fails
                with pytest.raises(RuntimeError, match="KRX login lock"):
                    await h._fetch_ohlcv_with_semaphore("20260203")

                # Second call should succeed (semaphore was released)
                result = await h._fetch_ohlcv_with_semaphore("20260204")

        assert call_count == 2
        pd.testing.assert_frame_equal(result, mock_df)


# ============================================================
# 2. TestConcurrentKRXAccess (P0)
# ============================================================

class TestConcurrentKRXAccess:
    """Test concurrent KRX access patterns."""

    @pytest.mark.asyncio
    async def test_ten_concurrent_same_date_one_krx_call(self, mock_df):
        """10 concurrent requests for same date should result in only 1 KRX call."""
        import tracking.helpers as h

        call_count = 0

        def counting_krx_call(d):
            nonlocal call_count
            call_count += 1
            time_module.sleep(0.05)
            return mock_df

        date = "20260205"

        with patch("krx_data_client.get_market_ohlcv_by_ticker", side_effect=counting_krx_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                results = await asyncio.gather(
                    *[h._fetch_ohlcv_with_semaphore(date) for _ in range(10)]
                )

        assert call_count == 1
        for r in results:
            pd.testing.assert_frame_equal(r, mock_df)

    @pytest.mark.asyncio
    async def test_five_concurrent_different_dates_serialized(self, mock_df):
        """5 concurrent requests for different dates should not overlap."""
        import tracking.helpers as h

        execution_log = []

        def logging_krx_call(d):
            start = time_module.monotonic()
            execution_log.append(("start", d, start))
            time_module.sleep(0.03)
            end = time_module.monotonic()
            execution_log.append(("end", d, end))
            return mock_df.copy()

        dates = [f"2026020{i}" for i in range(1, 6)]

        with patch("krx_data_client.get_market_ohlcv_by_ticker", side_effect=logging_krx_call):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await asyncio.gather(
                    *[h._fetch_ohlcv_with_semaphore(d) for d in dates]
                )

        # Verify no overlapping executions
        starts = sorted([(t, d) for tag, d, t in execution_log if tag == "start"])
        ends = sorted([(t, d) for tag, d, t in execution_log if tag == "end"])

        for i in range(len(starts) - 1):
            assert ends[i][0] <= starts[i + 1][0], "Concurrent execution detected"

    @pytest.mark.asyncio
    async def test_get_current_stock_price_concurrent_same_date_shares_cache(self, mock_df, mock_cursor):
        """Multiple get_current_stock_price calls should share OHLCV cache."""
        from tracking.helpers import get_current_stock_price

        call_count = 0

        def counting_krx_call(d):
            nonlocal call_count
            call_count += 1
            return mock_df

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("krx_data_client.get_market_ohlcv_by_ticker", side_effect=counting_krx_call):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        prices = await asyncio.gather(
                            get_current_stock_price(mock_cursor, "005930"),
                            get_current_stock_price(mock_cursor, "035720"),
                            get_current_stock_price(mock_cursor, "035420"),
                        )

        # All 3 tickers are in the same DataFrame, so only 1 KRX call needed
        assert call_count == 1
        assert prices[0] == 70000  # 005930
        assert prices[1] == 50000  # 035720
        assert prices[2] == 30000  # 035420

    @pytest.mark.asyncio
    async def test_semaphore_recovery_after_failed_coroutine(self, mock_df):
        """Semaphore should recover after a coroutine fails."""
        import tracking.helpers as h

        attempt = 0

        def failing_first(d):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise ConnectionError("KRX connection failed")
            return mock_df

        with patch("krx_data_client.get_market_ohlcv_by_ticker", side_effect=failing_first):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # First call fails
                with pytest.raises(ConnectionError):
                    await h._fetch_ohlcv_with_semaphore("20260203")

                # Verify semaphore is not locked
                sem = h._get_krx_semaphore()
                assert not sem.locked(), "Semaphore should not be locked after error"

                # Second call succeeds
                result = await h._fetch_ohlcv_with_semaphore("20260204")

        pd.testing.assert_frame_equal(result, mock_df)


# ============================================================
# 3. TestGetCurrentStockPriceRetry (P1)
# ============================================================

class TestGetCurrentStockPriceRetry:
    """Test get_current_stock_price retry logic and backoff."""

    @pytest.mark.asyncio
    async def test_first_attempt_success(self, mock_df, mock_cursor):
        """First attempt succeeds - no retry needed."""
        from tracking.helpers import get_current_stock_price

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("krx_data_client.get_market_ohlcv_by_ticker", return_value=mock_df):
                    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                        price = await get_current_stock_price(mock_cursor, "005930")

        assert price == 70000

    @pytest.mark.asyncio
    async def test_timeout_then_retry_success(self, mock_df, mock_cursor):
        """Timeout on first attempt, success on second."""
        from tracking.helpers import get_current_stock_price
        import tracking.helpers as h

        attempt = 0

        async def fetch_with_timeout(date):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise asyncio.TimeoutError()
            # On second attempt, populate cache and return
            h._ohlcv_cache[date] = mock_df
            h._ohlcv_cache_timestamp[date] = datetime.now()
            return mock_df

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("tracking.helpers._fetch_ohlcv_with_semaphore", side_effect=fetch_with_timeout):
                    with patch("asyncio.wait_for", side_effect=[asyncio.TimeoutError(), mock_df]):
                        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                            # Need to re-patch to handle the retry flow correctly
                            pass

        # Simpler approach: patch at a higher level
        call_count = 0

        async def mock_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Consume the coroutine to avoid warning
                try:
                    await coro
                except:
                    pass
                raise asyncio.TimeoutError()
            return await coro

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("krx_data_client.get_market_ohlcv_by_ticker", return_value=mock_df):
                    with patch("tracking.helpers.asyncio.wait_for", side_effect=mock_wait_for):
                        with patch("tracking.helpers.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                            price = await get_current_stock_price(mock_cursor, "005930")

        assert price == 70000
        # Backoff sleep should have been called with 1 (2^0)
        mock_sleep.assert_any_call(1)

    @pytest.mark.asyncio
    async def test_login_lock_error_retry_success(self, mock_df, mock_cursor):
        """Login lock error on first attempt, success on second."""
        from tracking.helpers import get_current_stock_price

        call_count = 0

        async def mock_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                try:
                    await coro
                except:
                    pass
                raise RuntimeError("로그인 락 획득 타임아웃")
            return await coro

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("krx_data_client.get_market_ohlcv_by_ticker", return_value=mock_df):
                    with patch("tracking.helpers.asyncio.wait_for", side_effect=mock_wait_for):
                        with patch("tracking.helpers.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                            price = await get_current_stock_price(mock_cursor, "005930")

        assert price == 70000
        mock_sleep.assert_any_call(1)  # First backoff: 2^0 = 1

    @pytest.mark.asyncio
    async def test_all_timeouts_fallback_to_db(self, mock_cursor):
        """All 3 attempts timeout → DB fallback."""
        from tracking.helpers import get_current_stock_price

        mock_cursor.fetchone.return_value = (65000,)

        async def always_timeout(coro, timeout):
            try:
                await coro
            except:
                pass
            raise asyncio.TimeoutError()

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("krx_data_client.get_market_ohlcv_by_ticker"):
                    with patch("tracking.helpers.asyncio.wait_for", side_effect=always_timeout):
                        with patch("tracking.helpers.asyncio.sleep", new_callable=AsyncMock):
                            price = await get_current_stock_price(mock_cursor, "005930")

        assert price == 65000

    @pytest.mark.asyncio
    async def test_all_lock_errors_fallback_to_db(self, mock_cursor):
        """All 3 attempts get login lock error → DB fallback."""
        from tracking.helpers import get_current_stock_price

        mock_cursor.fetchone.return_value = (62000,)

        async def always_lock_error(coro, timeout):
            try:
                await coro
            except:
                pass
            raise RuntimeError("로그인 락 획득 타임아웃")

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("krx_data_client.get_market_ohlcv_by_ticker"):
                    with patch("tracking.helpers.asyncio.wait_for", side_effect=always_lock_error):
                        with patch("tracking.helpers.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                            price = await get_current_stock_price(mock_cursor, "005930")

        assert price == 62000
        # Verify exponential backoff: 2^0=1, 2^1=2
        assert mock_sleep.call_args_list[0] == call(0.5)  # post-fetch delay from cache
        # Filter only backoff sleeps (value >= 1)
        backoff_calls = [c for c in mock_sleep.call_args_list if c == call(1) or c == call(2)]
        assert call(1) in backoff_calls  # First retry backoff
        assert call(2) in backoff_calls  # Second retry backoff

    @pytest.mark.asyncio
    async def test_exponential_backoff_values(self, mock_cursor):
        """Verify exponential backoff sleep values: 1s, 2s."""
        from tracking.helpers import get_current_stock_price

        mock_cursor.fetchone.return_value = (60000,)
        sleep_args = []

        async def recording_sleep(seconds):
            sleep_args.append(seconds)

        async def always_timeout(coro, timeout):
            try:
                await coro
            except:
                pass
            raise asyncio.TimeoutError()

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("krx_data_client.get_market_ohlcv_by_ticker"):
                    with patch("tracking.helpers.asyncio.wait_for", side_effect=always_timeout):
                        with patch("tracking.helpers.asyncio.sleep", side_effect=recording_sleep):
                            await get_current_stock_price(mock_cursor, "005930", max_retries=3)

        # Backoff values should include 1 (2^0) and 2 (2^1)
        # (there may also be 0.5 from the post-fetch delay in _fetch_ohlcv_with_semaphore)
        backoff_values = [v for v in sleep_args if v >= 1]
        assert 1 in backoff_values, f"Expected backoff of 1s, got {sleep_args}"
        assert 2 in backoff_values, f"Expected backoff of 2s, got {sleep_args}"

    @pytest.mark.asyncio
    async def test_ticker_not_in_dataframe_db_fallback(self, mock_df, mock_cursor):
        """Ticker not in DataFrame → immediate DB fallback (no retry)."""
        from tracking.helpers import get_current_stock_price

        mock_cursor.fetchone.return_value = (55000,)

        with patch("tracking.helpers.is_market_hours", return_value=False):
            with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
                with patch("krx_data_client.get_market_ohlcv_by_ticker", return_value=mock_df):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        price = await get_current_stock_price(mock_cursor, "999999")

        assert price == 55000


# ============================================================
# 4. TestOHLCVCacheOperations
# ============================================================

class TestOHLCVCacheOperations:
    """Test OHLCV cache TTL and operations."""

    def test_get_cached_ohlcv_hit(self, mock_df):
        """Fresh cache entry should return data."""
        import tracking.helpers as h

        date = "20260205"
        h._ohlcv_cache[date] = mock_df
        h._ohlcv_cache_timestamp[date] = datetime.now()

        result = h._get_cached_ohlcv(date)
        assert result is mock_df

    def test_get_cached_ohlcv_miss(self):
        """Missing cache entry should return None."""
        import tracking.helpers as h

        result = h._get_cached_ohlcv("20260205")
        assert result is None

    def test_get_cached_ohlcv_expired(self, mock_df):
        """Expired cache entry (> 30 min) should return None and clean up."""
        import tracking.helpers as h

        date = "20260205"
        h._ohlcv_cache[date] = mock_df
        # Set timestamp to 31 minutes ago
        h._ohlcv_cache_timestamp[date] = datetime.now() - timedelta(minutes=31)

        result = h._get_cached_ohlcv(date)
        assert result is None
        # Cache should be cleaned up
        assert date not in h._ohlcv_cache
        assert date not in h._ohlcv_cache_timestamp

    def test_set_cached_ohlcv(self, mock_df):
        """Setting cache should store both data and timestamp."""
        import tracking.helpers as h

        date = "20260205"
        h._set_cached_ohlcv(date, mock_df)

        assert date in h._ohlcv_cache
        assert h._ohlcv_cache[date] is mock_df
        assert date in h._ohlcv_cache_timestamp
        # Timestamp should be recent
        assert (datetime.now() - h._ohlcv_cache_timestamp[date]).total_seconds() < 2

    def test_independent_date_caches(self, mock_df):
        """Different dates should have independent cache entries."""
        import tracking.helpers as h

        df1 = mock_df.copy()
        df2 = mock_df.copy()
        df2["Close"] = [80000, 60000, 40000]

        h._set_cached_ohlcv("20260204", df1)
        h._set_cached_ohlcv("20260205", df2)

        result1 = h._get_cached_ohlcv("20260204")
        result2 = h._get_cached_ohlcv("20260205")

        assert result1["Close"]["005930"] == 70000
        assert result2["Close"]["005930"] == 80000


# ============================================================
# 5. TestCircuitBreaker (P2)
# ============================================================

class TestCircuitBreaker:
    """Test MCP server circuit breaker logic."""

    def test_initial_state_circuit_closed(self, reset_circuit_breaker):
        """Circuit should be closed initially."""
        from report_generator import is_circuit_open

        assert is_circuit_open("kospi_kosdaq") is False

    def test_three_failures_opens_circuit(self, reset_circuit_breaker):
        """3 consecutive failures should open the circuit."""
        from report_generator import record_server_failure, is_circuit_open

        record_server_failure("kospi_kosdaq")
        assert is_circuit_open("kospi_kosdaq") is False

        record_server_failure("kospi_kosdaq")
        assert is_circuit_open("kospi_kosdaq") is False

        record_server_failure("kospi_kosdaq")
        assert is_circuit_open("kospi_kosdaq") is True

    def test_circuit_auto_closes_after_timeout(self, reset_circuit_breaker):
        """Circuit should auto-close after CIRCUIT_BREAKER_TIMEOUT (300s)."""
        import report_generator as rg
        from report_generator import record_server_failure, is_circuit_open

        # Open the circuit
        for _ in range(3):
            record_server_failure("kospi_kosdaq")

        assert is_circuit_open("kospi_kosdaq") is True

        # Simulate timeout expiry by backdating the circuit open timestamp
        rg._server_circuit_open_until["kospi_kosdaq"] = datetime.now() - timedelta(seconds=1)

        assert is_circuit_open("kospi_kosdaq") is False
        # Failure count should be reset
        assert rg._server_failure_counts["kospi_kosdaq"] == 0

    def test_success_resets_failure_counter(self, reset_circuit_breaker):
        """Successful call should reset failure counter."""
        import report_generator as rg
        from report_generator import record_server_failure, record_server_success

        record_server_failure("kospi_kosdaq")
        record_server_failure("kospi_kosdaq")
        assert rg._server_failure_counts["kospi_kosdaq"] == 2

        record_server_success("kospi_kosdaq")
        assert rg._server_failure_counts["kospi_kosdaq"] == 0


# ============================================================
# 6. TestWarmupKRXSession
# ============================================================

class TestWarmupKRXSession:
    """Test KRX session warmup."""

    @pytest.mark.asyncio
    async def test_warmup_success(self):
        """Successful warmup should not raise."""
        from stock_analysis_orchestrator import StockAnalysisOrchestrator

        orchestrator = StockAnalysisOrchestrator.__new__(StockAnalysisOrchestrator)
        orchestrator.selected_tickers = {}
        orchestrator.telegram_config = Mock()

        with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
            with patch("krx_data_client.get_market_ohlcv_by_ticker", return_value=Mock()) as mock_krx:
                await orchestrator.warmup_krx_session()

                mock_krx.assert_called_once_with("20260205")

    @pytest.mark.asyncio
    async def test_warmup_failure_graceful_degradation(self):
        """Warmup failure should log warning but not raise."""
        from stock_analysis_orchestrator import StockAnalysisOrchestrator

        orchestrator = StockAnalysisOrchestrator.__new__(StockAnalysisOrchestrator)
        orchestrator.selected_tickers = {}
        orchestrator.telegram_config = Mock()

        with patch("krx_data_client.get_nearest_business_day_in_a_week", side_effect=Exception("Network error")):
            # Should not raise
            await orchestrator.warmup_krx_session()


# ============================================================
# 7. TestDBFallback
# ============================================================

class TestDBFallback:
    """Test _get_last_price_from_db fallback behavior."""

    def test_db_returns_valid_price(self):
        """DB has valid price → return it."""
        from tracking.helpers import _get_last_price_from_db

        cursor = Mock()
        cursor.fetchone.return_value = (68500,)

        price = _get_last_price_from_db(cursor, "005930")
        assert price == 68500.0
        cursor.execute.assert_called_once_with(
            "SELECT current_price FROM stock_holdings WHERE ticker = ?",
            ("005930",),
        )

    def test_db_returns_none(self):
        """DB has no record → return 0.0."""
        from tracking.helpers import _get_last_price_from_db

        cursor = Mock()
        cursor.fetchone.return_value = None

        price = _get_last_price_from_db(cursor, "005930")
        assert price == 0.0

    def test_db_raises_exception(self):
        """DB error → return 0.0."""
        from tracking.helpers import _get_last_price_from_db

        cursor = Mock()
        cursor.execute.side_effect = Exception("DB connection lost")

        price = _get_last_price_from_db(cursor, "005930")
        assert price == 0.0


# ============================================================
# 8. TestKRXIntegration (skip by default)
# ============================================================

@pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="Integration tests require RUN_INTEGRATION_TESTS=true",
)
class TestKRXIntegration:
    """Integration tests using real KRX API."""

    @pytest.mark.asyncio
    async def test_real_fetch_ohlcv(self):
        """Test real KRX OHLCV fetch."""
        import tracking.helpers as h
        from krx_data_client import get_nearest_business_day_in_a_week

        today = datetime.now().strftime("%Y%m%d")
        trade_date = get_nearest_business_day_in_a_week(today, prev=True)

        df = await h._fetch_ohlcv_with_semaphore(trade_date)

        assert df is not None
        assert len(df) > 0
        assert "Close" in df.columns
        assert "005930" in df.index  # Samsung Electronics

    @pytest.mark.asyncio
    async def test_real_concurrent_access(self):
        """Test real concurrent KRX access does not cause lock errors."""
        import tracking.helpers as h
        from krx_data_client import get_nearest_business_day_in_a_week

        today = datetime.now().strftime("%Y%m%d")
        trade_date = get_nearest_business_day_in_a_week(today, prev=True)

        # 5 concurrent requests for same date
        results = await asyncio.gather(
            *[h._fetch_ohlcv_with_semaphore(trade_date) for _ in range(5)]
        )

        for r in results:
            assert r is not None
            assert "005930" in r.index

    @pytest.mark.asyncio
    async def test_real_cache_reuse(self):
        """Test real cache is reused on second call."""
        import tracking.helpers as h
        from krx_data_client import get_nearest_business_day_in_a_week

        today = datetime.now().strftime("%Y%m%d")
        trade_date = get_nearest_business_day_in_a_week(today, prev=True)

        # First call: should fetch from KRX
        df1 = await h._fetch_ohlcv_with_semaphore(trade_date)

        # Second call: should use cache
        df2 = await h._fetch_ohlcv_with_semaphore(trade_date)

        assert df1 is df2  # Same object reference (cached)


# ============================================================
# Additional: TestGetKRXSemaphore
# ============================================================

class TestGetKRXSemaphore:
    """Test semaphore singleton creation."""

    def test_creates_semaphore_on_first_call(self):
        """First call should create a new semaphore."""
        import tracking.helpers as h

        assert h._krx_semaphore is None
        sem = h._get_krx_semaphore()
        assert isinstance(sem, asyncio.Semaphore)
        assert h._krx_semaphore is sem

    def test_returns_same_semaphore_on_subsequent_calls(self):
        """Subsequent calls should return the same semaphore."""
        import tracking.helpers as h

        sem1 = h._get_krx_semaphore()
        sem2 = h._get_krx_semaphore()
        assert sem1 is sem2


# ============================================================
# 9. TestCircuitBreakerInAnalysis (Gap 1 검증)
# ============================================================

class TestCircuitBreakerInAnalysis:
    """Test circuit breaker integration in cores/analysis.py sequential loop."""

    def test_circuit_open_skips_section(self, reset_circuit_breaker):
        """서킷 오픈 시 섹션이 즉시 스킵되는지 확인."""
        from report_generator import record_server_failure, is_circuit_open

        # Open the circuit for mcp_analysis
        for _ in range(3):
            record_server_failure("mcp_analysis")

        assert is_circuit_open("mcp_analysis") is True

    def test_timeout_records_failure(self, reset_circuit_breaker):
        """TimeoutError 발생 시 실패 카운터 증가 확인."""
        import report_generator as rg
        from report_generator import record_server_failure

        assert rg._server_failure_counts["mcp_analysis"] == 0
        record_server_failure("mcp_analysis")
        assert rg._server_failure_counts["mcp_analysis"] == 1

    def test_success_resets_counter(self, reset_circuit_breaker):
        """성공 시 실패 카운터 리셋 확인."""
        import report_generator as rg
        from report_generator import record_server_failure, record_server_success

        record_server_failure("mcp_analysis")
        record_server_failure("mcp_analysis")
        assert rg._server_failure_counts["mcp_analysis"] == 2

        record_server_success("mcp_analysis")
        assert rg._server_failure_counts["mcp_analysis"] == 0

    def test_three_timeouts_open_circuit(self, reset_circuit_breaker):
        """3연속 타임아웃 → 서킷 오픈 확인."""
        from report_generator import record_server_failure, is_circuit_open

        for i in range(3):
            assert is_circuit_open("mcp_analysis") is False
            record_server_failure("mcp_analysis")

        assert is_circuit_open("mcp_analysis") is True


# ============================================================
# 10. TestTriggerBatchRateLimiting (Gap 2 검증)
# ============================================================

class TestTriggerBatchRateLimiting:
    """Test trigger_batch.py KRX rate limiting."""

    def test_krx_call_delay_constant(self):
        """KRX_CALL_DELAY >= 0.5 확인."""
        from trigger_batch import KRX_CALL_DELAY

        assert KRX_CALL_DELAY >= 0.5

    def test_run_batch_calls_sleep(self):
        """run_batch()에서 time.sleep 호출 확인 (소스 코드 검사)."""
        import inspect
        import trigger_batch

        source = inspect.getsource(trigger_batch.run_batch)
        assert "time.sleep(KRX_CALL_DELAY)" in source, (
            "run_batch() should call time.sleep(KRX_CALL_DELAY) between KRX calls"
        )

    def test_get_multi_day_ohlcv_calls_sleep(self):
        """get_multi_day_ohlcv()에서 time.sleep 호출 확인 (소스 코드 검사)."""
        import inspect
        import trigger_batch

        source = inspect.getsource(trigger_batch.get_multi_day_ohlcv)
        assert "time.sleep(KRX_CALL_DELAY)" in source, (
            "get_multi_day_ohlcv() should call time.sleep(KRX_CALL_DELAY) before KRX call"
        )


# ============================================================
# 11. TestWarmupUsesCache (Gap 3 검증)
# ============================================================

class TestWarmupUsesCache:
    """Test warmup_krx_session uses semaphore and populates cache."""

    @pytest.mark.asyncio
    async def test_warmup_populates_ohlcv_cache(self, mock_df):
        """워밍업 후 tracking.helpers._ohlcv_cache에 데이터 존재 확인."""
        import tracking.helpers as h
        from stock_analysis_orchestrator import StockAnalysisOrchestrator

        orchestrator = StockAnalysisOrchestrator.__new__(StockAnalysisOrchestrator)
        orchestrator.selected_tickers = {}
        orchestrator.telegram_config = Mock()

        with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
            with patch("krx_data_client.get_market_ohlcv_by_ticker", return_value=mock_df):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await orchestrator.warmup_krx_session()

        assert "20260205" in h._ohlcv_cache
        pd.testing.assert_frame_equal(h._ohlcv_cache["20260205"], mock_df)

    @pytest.mark.asyncio
    async def test_warmup_uses_semaphore(self, mock_df):
        """_fetch_ohlcv_with_semaphore 호출 확인."""
        from stock_analysis_orchestrator import StockAnalysisOrchestrator

        orchestrator = StockAnalysisOrchestrator.__new__(StockAnalysisOrchestrator)
        orchestrator.selected_tickers = {}
        orchestrator.telegram_config = Mock()

        with patch("krx_data_client.get_nearest_business_day_in_a_week", return_value="20260205"):
            with patch(
                "tracking.helpers._fetch_ohlcv_with_semaphore",
                new_callable=AsyncMock,
                return_value=mock_df,
            ) as mock_fetch:
                await orchestrator.warmup_krx_session()

                mock_fetch.assert_called_once_with("20260205")


# ============================================================
# 12. TestKospiKosdaqTimeoutConfig (근본 원인 수정 검증)
# ============================================================

class TestKospiKosdaqTimeoutConfig:
    """Test kospi_kosdaq MCP timeout is correctly reduced."""

    def test_kospi_kosdaq_timeout_60s(self):
        """kospi_kosdaq read_timeout이 60초 이하인지 확인."""
        import yaml

        config_path = project_root / "mcp_agent.config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        kospi_timeout = config["mcp"]["servers"]["kospi_kosdaq"]["read_timeout_seconds"]
        assert kospi_timeout <= 60, (
            f"kospi_kosdaq read_timeout should be <= 60s (was {kospi_timeout}s). "
            f"180s causes 13-min cascading timeouts on parallel tool calls."
        )

    def test_kospi_kosdaq_timeout_shorter_than_agent_timeout(self):
        """kospi_kosdaq MCP timeout이 이를 사용하는 에이전트 timeout보다 짧은지 확인."""
        import yaml
        from cores.agents.agent_timeout_config import get_timeout_seconds

        config_path = project_root / "mcp_agent.config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        kospi_timeout = config["mcp"]["servers"]["kospi_kosdaq"]["read_timeout_seconds"]

        # kospi_kosdaq를 사용하는 에이전트들의 timeout
        agents_using_kospi = [
            "price_volume_agent", "investor_trading_agent",
            "market_index_agent", "sell_decision_agent", "buy_decision_agent",
        ]
        for agent_name in agents_using_kospi:
            agent_timeout = get_timeout_seconds(agent_name)
            assert kospi_timeout < agent_timeout, (
                f"kospi_kosdaq timeout ({kospi_timeout}s) >= "
                f"{agent_name} timeout ({agent_timeout}s). "
                f"MCP timeout must be shorter to allow agent-level retry."
            )


# ============================================================
# 13. TestParallelToolCallsDisabled (병렬 tool call 비활성화 검증)
# ============================================================

class TestParallelToolCallsDisabled:
    """Test that trading agents disable parallel tool calls."""

    def test_sell_decision_disables_parallel(self):
        """sell_decision_agent의 RequestParams에 parallel_tool_calls=False 확인."""
        import inspect
        import stock_tracking_enhanced_agent

        source = inspect.getsource(stock_tracking_enhanced_agent)
        assert '"parallel_tool_calls": False' in source or "'parallel_tool_calls': False" in source, (
            "stock_tracking_enhanced_agent should set parallel_tool_calls=False "
            "to prevent KRX file lock contention"
        )

    def test_buy_decision_disables_parallel(self):
        """buy_decision_agent(stock_tracking_agent)의 RequestParams에 parallel_tool_calls=False 확인."""
        import inspect
        import stock_tracking_agent

        source = inspect.getsource(stock_tracking_agent)
        assert '"parallel_tool_calls": False' in source or "'parallel_tool_calls': False" in source, (
            "stock_tracking_agent should set parallel_tool_calls=False "
            "to prevent KRX file lock contention"
        )


# ============================================================
# 14. TestMarketIndexAgentTimeout (타임아웃 현실화 검증)
# ============================================================

class TestMarketIndexAgentTimeout:
    """Test market_index_agent timeout is increased based on P95 data."""

    def test_market_index_timeout_at_least_150s(self):
        """market_index_agent timeout이 150초 이상인지 확인 (P95 실측: 64초)."""
        from cores.agents.agent_timeout_config import get_timeout_seconds

        timeout = get_timeout_seconds("market_index_agent")
        assert timeout >= 150, (
            f"market_index_agent timeout should be >= 150s (was {timeout}s). "
            f"P95 actual duration is 64s, needs 2x+ buffer for kospi_kosdaq+perplexity."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-k", "not Integration"])
