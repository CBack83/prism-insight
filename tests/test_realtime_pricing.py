"""
Unit tests for real-time pricing implementation.

Tests:
- is_market_hours() function
- get_realtime_price_from_kis() function
- get_current_stock_price() market hours logic
- Cache TTL validation
"""

import pytest
import asyncio
import datetime as dt_module
from datetime import datetime, time, timedelta
from unittest.mock import Mock, patch, AsyncMock
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _make_mock_datetime(hour, minute):
    """Create a datetime subclass that returns a fixed time for now()."""
    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 2, 5, hour, minute, 0)
    return MockDatetime


class TestMarketHoursDetection:
    """Test market hours detection logic."""

    def test_is_market_hours_during_trading(self):
        """Test: Market hours detection during trading hours (10:00)."""
        from tracking.helpers import is_market_hours

        with patch.object(dt_module, 'datetime', _make_mock_datetime(10, 0)):
            with patch('check_market_day.is_market_day', return_value=True):
                result = is_market_hours()
                assert result is True

    def test_is_market_hours_before_market(self):
        """Test: Market hours detection before market open (08:30)."""
        from tracking.helpers import is_market_hours

        with patch.object(dt_module, 'datetime', _make_mock_datetime(8, 30)):
            with patch('check_market_day.is_market_day', return_value=True):
                result = is_market_hours()
                assert result is False

    def test_is_market_hours_after_market(self):
        """Test: Market hours detection after market close (16:00)."""
        from tracking.helpers import is_market_hours

        with patch.object(dt_module, 'datetime', _make_mock_datetime(16, 0)):
            with patch('check_market_day.is_market_day', return_value=True):
                result = is_market_hours()
                assert result is False

    def test_is_market_hours_non_trading_day(self):
        """Test: Market hours detection on non-trading day (weekend)."""
        from tracking.helpers import is_market_hours

        with patch('check_market_day.is_market_day', return_value=False):
            result = is_market_hours()
            assert result is False


class TestKISAPIRealtime:
    """Test KIS API real-time price fetching."""

    @pytest.mark.asyncio
    async def test_get_realtime_price_success(self):
        """Test: Successful KIS API real-time price fetch."""
        from tracking.helpers import get_realtime_price_from_kis

        with patch('trading.domestic_stock_trading.DomesticStockTrading') as mock_trader_class:
            # Mock successful price response
            mock_trader = Mock()
            mock_trader.get_current_price.return_value = {
                'current_price': 70000,
                'change_rate': 2.5
            }
            mock_trader_class.return_value = mock_trader

            with patch('asyncio.to_thread', new_callable=AsyncMock) as mock_to_thread:
                mock_to_thread.return_value = mock_trader.get_current_price.return_value

                price = await get_realtime_price_from_kis("005930", max_retries=2)

                assert price == 70000
                mock_to_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_realtime_price_timeout(self):
        """Test: KIS API timeout handling."""
        from tracking.helpers import get_realtime_price_from_kis

        with patch('trading.domestic_stock_trading.DomesticStockTrading') as mock_trader_class:
            mock_trader = Mock()
            mock_trader_class.return_value = mock_trader

            with patch('asyncio.to_thread', new_callable=AsyncMock) as mock_to_thread:
                # Simulate timeout
                mock_to_thread.side_effect = asyncio.TimeoutError()

                with patch('asyncio.sleep', new_callable=AsyncMock):
                    price = await get_realtime_price_from_kis("005930", max_retries=2)

                assert price is None
                assert mock_to_thread.call_count == 2  # 2 retries

    @pytest.mark.asyncio
    async def test_get_realtime_price_invalid_data(self):
        """Test: KIS API returns invalid data."""
        from tracking.helpers import get_realtime_price_from_kis

        with patch('trading.domestic_stock_trading.DomesticStockTrading') as mock_trader_class:
            # Mock invalid price response (0 or None)
            mock_trader = Mock()
            mock_trader.get_current_price.return_value = {
                'current_price': 0
            }
            mock_trader_class.return_value = mock_trader

            with patch('asyncio.to_thread', new_callable=AsyncMock) as mock_to_thread:
                mock_to_thread.return_value = mock_trader.get_current_price.return_value

                with patch('asyncio.sleep', new_callable=AsyncMock):
                    price = await get_realtime_price_from_kis("005930", max_retries=2)

                assert price is None
                assert mock_to_thread.call_count == 2  # Retries invalid data


class TestCurrentStockPrice:
    """Test get_current_stock_price() market hours logic."""

    @pytest.mark.asyncio
    async def test_get_price_market_hours_kis_success(self):
        """Test: During market hours, use KIS API successfully."""
        from tracking.helpers import get_current_stock_price

        mock_cursor = Mock()

        with patch('tracking.helpers.is_market_hours', return_value=True):
            with patch('tracking.helpers.get_realtime_price_from_kis', new_callable=AsyncMock) as mock_kis:
                mock_kis.return_value = 70000

                price = await get_current_stock_price(mock_cursor, "005930")

                assert price == 70000
                mock_kis.assert_called_once_with("005930", max_retries=2)

    @pytest.mark.asyncio
    async def test_get_price_market_hours_kis_fails_fallback_krx(self):
        """Test: During market hours, KIS fails, fallback to KRX."""
        from tracking.helpers import get_current_stock_price
        import pandas as pd

        mock_cursor = Mock()
        mock_df = pd.DataFrame({'Close': [68000]}, index=["005930"])

        with patch('tracking.helpers.is_market_hours', return_value=True):
            with patch('tracking.helpers.get_realtime_price_from_kis', new_callable=AsyncMock) as mock_kis:
                mock_kis.return_value = None  # KIS fails

                with patch('krx_data_client.get_nearest_business_day_in_a_week', return_value="20260204"):
                    with patch('tracking.helpers.asyncio.wait_for', new_callable=AsyncMock) as mock_wait:
                        mock_wait.return_value = mock_df

                        with patch('tracking.helpers.asyncio.sleep', new_callable=AsyncMock):
                            price = await get_current_stock_price(mock_cursor, "005930")

                        assert price == 68000
                        mock_kis.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_price_after_hours_krx_only(self):
        """Test: After hours, use KRX only (no KIS attempt)."""
        from tracking.helpers import get_current_stock_price
        import pandas as pd

        mock_cursor = Mock()
        mock_df = pd.DataFrame({'Close': [68000]}, index=["005930"])

        with patch('tracking.helpers.is_market_hours', return_value=False):
            with patch('tracking.helpers.get_realtime_price_from_kis', new_callable=AsyncMock) as mock_kis:
                with patch('krx_data_client.get_nearest_business_day_in_a_week', return_value="20260205"):
                    with patch('tracking.helpers.asyncio.wait_for', new_callable=AsyncMock) as mock_wait:
                        mock_wait.return_value = mock_df

                        with patch('tracking.helpers.asyncio.sleep', new_callable=AsyncMock):
                            price = await get_current_stock_price(mock_cursor, "005930")

                        assert price == 68000
                        mock_kis.assert_not_called()  # Should not call KIS after hours


class TestCacheTTL:
    """Test cache TTL validation logic in StockTrackingAgent."""

    def _create_agent_with_cache(self, cache_data):
        """Create a StockTrackingAgent with injected price_cache (no DB/Telegram)."""
        from stock_tracking_agent import StockTrackingAgent

        agent = StockTrackingAgent.__new__(StockTrackingAgent)
        agent.price_cache = cache_data
        agent.cursor = Mock()
        agent.conn = Mock()
        agent.telegram_bot = None
        agent.telegram_token = None
        agent.enable_journal = False
        agent.db_path = ":memory:"
        agent.max_slots = 10
        agent.message_queue = []
        agent.trading_agent = None
        return agent

    @pytest.mark.asyncio
    async def test_cache_hit_market_hours_fresh(self):
        """Test: Cache hit during market hours with fresh data (< 60s)."""
        agent = self._create_agent_with_cache({
            "005930": {
                'price': 70000,
                'trade_date': datetime.now().strftime("%Y%m%d"),
                'timestamp': datetime.now() - timedelta(seconds=30),  # 30s old
                'source': 'realtime'
            }
        })

        with patch('tracking.helpers.is_market_hours', return_value=True):
            price = await agent._get_current_stock_price("005930")

            assert price == 70000

    @pytest.mark.asyncio
    async def test_cache_expired_market_hours_stale(self):
        """Test: Cache expired during market hours (> 60s)."""
        agent = self._create_agent_with_cache({
            "005930": {
                'price': 70000,
                'trade_date': datetime.now().strftime("%Y%m%d"),
                'timestamp': datetime.now() - timedelta(seconds=120),  # 120s old
                'source': 'realtime'
            }
        })

        with patch('tracking.helpers.is_market_hours', return_value=True):
            with patch('stock_tracking_agent.get_current_stock_price', new_callable=AsyncMock) as mock_get_price:
                mock_get_price.return_value = 71000

                price = await agent._get_current_stock_price("005930")

                assert price == 71000
                mock_get_price.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit_after_hours_no_ttl(self):
        """Test: Cache hit after hours (no TTL check)."""
        current_date = datetime.now().strftime("%Y%m%d")

        agent = self._create_agent_with_cache({
            "005930": {
                'price': 70000,
                'trade_date': current_date,
                'timestamp': datetime.now() - timedelta(hours=3),  # 3 hours old
                'source': 'historical'
            }
        })

        with patch('tracking.helpers.is_market_hours', return_value=False):
            with patch('krx_data_client.get_nearest_business_day_in_a_week', return_value=current_date):
                price = await agent._get_current_stock_price("005930")

                assert price == 70000  # Should use cache despite being old


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
