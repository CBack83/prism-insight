"""
Test FinanceDataReader Integration (Phase 1)

Validates:
- FDR can fetch data for sample stocks
- Fallback chain works (FDR → KRX)
- Multi-source fetcher is backward compatible
- Error handling is robust
"""

import asyncio
import logging
from datetime import datetime, timedelta

try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    pytest = None

from data_sources.multi_source_fetcher import MultiSourceFetcher

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Sample stocks for testing
SAMPLE_STOCKS = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("035720", "카카오"),
    ("051910", "LG화학"),
]


if PYTEST_AVAILABLE:
    @pytest.mark.asyncio
    async def test_fdr_single_stock():
        """Test FDR can fetch data for a single stock."""
        fetcher = MultiSourceFetcher()

        ticker = "005930"  # 삼성전자
        trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        logger.info(f"Testing FDR for {ticker} on {trade_date}")

        data = await fetcher.fetch_from_fdr(ticker, trade_date)

        assert data is not None, "FDR should return data"
        assert data['ticker'] == ticker
        assert data['close'] > 0, "Close price should be positive"
        assert data['volume'] > 0, "Volume should be positive"
        assert data['data_source'] == "fdr"

        logger.info(f"✅ FDR Test Passed: {ticker} = {data['close']:,.0f}원")


@pytest.mark.asyncio
async def test_fdr_batch_fetch():
    """Test FDR can fetch data for multiple stocks."""
    fetcher = MultiSourceFetcher()
    trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    success_count = 0
    fail_count = 0

    for ticker, name in SAMPLE_STOCKS:
        logger.info(f"Testing {name} ({ticker})...")

        data = await fetcher.fetch_from_fdr(ticker, trade_date)

        if data:
            logger.info(f"✅ {name}: {data['close']:,.0f}원")
            success_count += 1
        else:
            logger.warning(f"❌ {name}: 데이터 없음")
            fail_count += 1

    success_rate = (success_count / len(SAMPLE_STOCKS)) * 100
    logger.info(f"Success Rate: {success_rate:.0f}% ({success_count}/{len(SAMPLE_STOCKS)})")

    assert success_rate >= 80, f"Success rate should be >= 80%, got {success_rate:.0f}%"


@pytest.mark.asyncio
async def test_multi_source_fallback_chain():
    """Test multi-source fallback chain (FDR → KRX)."""
    fetcher = MultiSourceFetcher()

    ticker = "005930"
    trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    logger.info(f"Testing fallback chain for {ticker}...")

    price = await fetcher.get_stock_price(ticker, trade_date)

    assert price is not None, "Fallback chain should return a price"
    assert price > 0, "Price should be positive"

    logger.info(f"✅ Fallback Chain Test Passed: {ticker} = {price:,.0f}원")


@pytest.mark.asyncio
async def test_market_hours_detection():
    """Test market hours detection logic."""
    fetcher = MultiSourceFetcher()

    is_market_hours = fetcher._is_market_hours()

    logger.info(f"Current market hours status: {is_market_hours}")

    # Just verify it doesn't crash
    assert isinstance(is_market_hours, bool)


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling for invalid ticker."""
    fetcher = MultiSourceFetcher()

    # Invalid ticker
    invalid_ticker = "999999"
    trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    logger.info(f"Testing error handling for invalid ticker: {invalid_ticker}")

    data = await fetcher.fetch_from_fdr(invalid_ticker, trade_date)

    # Should return None, not crash
    assert data is None, "Invalid ticker should return None"

    logger.info("✅ Error Handling Test Passed")


def test_import():
    """Test that multi_source_fetcher can be imported."""
    from data_sources.multi_source_fetcher import MultiSourceFetcher, get_stock_price_multi_source

    assert MultiSourceFetcher is not None
    assert get_stock_price_multi_source is not None

    logger.info("✅ Import Test Passed")


# ============================================================
# Quick Integration Test (Run without pytest)
# ============================================================

async def quick_test():
    """Quick integration test (no pytest required)."""
    logger.info("=" * 60)
    logger.info("Phase 1: FDR Integration Quick Test")
    logger.info("=" * 60)

    fetcher = MultiSourceFetcher()
    trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    logger.info(f"\nTest Date: {trade_date}")
    logger.info(f"Sample Stocks: {len(SAMPLE_STOCKS)}\n")

    results = []

    for ticker, name in SAMPLE_STOCKS:
        logger.info(f"Testing {name} ({ticker})...")

        try:
            # Test FDR fetch
            data = await fetcher.fetch_from_fdr(ticker, trade_date)

            if data:
                results.append({
                    "ticker": ticker,
                    "name": name,
                    "price": data['close'],
                    "source": data['data_source'],
                    "status": "✅ Success"
                })
                logger.info(f"  → {data['close']:,.0f}원 (출처: {data['data_source']})")
            else:
                results.append({
                    "ticker": ticker,
                    "name": name,
                    "status": "❌ Failed"
                })
                logger.warning(f"  → 데이터 없음")

        except Exception as e:
            results.append({
                "ticker": ticker,
                "name": name,
                "status": f"❌ Error: {e}"
            })
            logger.error(f"  → 오류: {e}")

        await asyncio.sleep(0.5)  # Rate limit

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)

    success = sum(1 for r in results if "Success" in r.get('status', ''))
    total = len(results)
    success_rate = (success / total) * 100

    logger.info(f"Success Rate: {success_rate:.0f}% ({success}/{total})")

    for r in results:
        logger.info(f"{r['name']:12} ({r['ticker']}): {r['status']}")

    logger.info("\n" + "=" * 60)

    if success_rate >= 80:
        logger.info("✅ Phase 1 Implementation: PASS (>=80% success)")
    else:
        logger.warning(f"⚠️ Phase 1 Implementation: NEEDS ATTENTION ({success_rate:.0f}% < 80%)")

    logger.info("=" * 60)


if __name__ == "__main__":
    # Run quick test without pytest
    asyncio.run(quick_test())
