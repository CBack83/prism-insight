#!/usr/bin/env python3
"""
Integration test for real-time pricing feature.

Usage:
    python tests/test_realtime_integration.py
"""

import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_market_hours_detection():
    """Test 1: Market hours detection."""
    from tracking.helpers import is_market_hours

    logger.info("=" * 60)
    logger.info("Test 1: Market Hours Detection")
    logger.info("=" * 60)

    in_market_hours = is_market_hours()
    current_time = datetime.now().strftime("%H:%M:%S")

    logger.info(f"Current time: {current_time}")
    logger.info(f"Is market hours: {in_market_hours}")

    if in_market_hours:
        logger.info("✅ System will use KIS API for real-time pricing")
    else:
        logger.info("✅ System will use KRX historical data")

    return in_market_hours


async def test_kis_api_realtime():
    """Test 2: KIS API real-time price fetch."""
    from tracking.helpers import get_realtime_price_from_kis

    logger.info("=" * 60)
    logger.info("Test 2: KIS API Real-time Price Fetch")
    logger.info("=" * 60)

    test_ticker = "005930"  # Samsung Electronics
    logger.info(f"Testing ticker: {test_ticker}")

    price = await get_realtime_price_from_kis(test_ticker, max_retries=2)

    if price:
        logger.info(f"✅ KIS API SUCCESS: {test_ticker} = {price:,.0f} KRW")
        return True, price
    else:
        logger.warning(f"⚠️ KIS API FAILED: {test_ticker}")
        return False, None


async def test_current_stock_price():
    """Test 3: Integrated price fetch (market hours aware)."""
    from tracking.helpers import get_current_stock_price
    import sqlite3

    logger.info("=" * 60)
    logger.info("Test 3: Integrated Price Fetch (Market Hours Aware)")
    logger.info("=" * 60)

    test_ticker = "005930"  # Samsung Electronics
    logger.info(f"Testing ticker: {test_ticker}")

    # Create temporary DB connection
    conn = sqlite3.connect("stock_tracking_db.sqlite")
    cursor = conn.cursor()

    try:
        price = await get_current_stock_price(cursor, test_ticker, max_retries=3)

        if price > 0:
            logger.info(f"✅ Price fetch SUCCESS: {test_ticker} = {price:,.0f} KRW")
            return True, price
        else:
            logger.error(f"❌ Price fetch FAILED: {test_ticker}")
            return False, None
    finally:
        conn.close()


async def test_gap_detection():
    """Test 4: Gap detection (compare KIS vs KRX)."""
    from tracking.helpers import get_realtime_price_from_kis, is_market_hours
    from krx_data_client import get_nearest_business_day_in_a_week, get_market_ohlcv_by_ticker
    import datetime

    logger.info("=" * 60)
    logger.info("Test 4: Gap Detection (KIS vs KRX)")
    logger.info("=" * 60)

    test_ticker = "005930"  # Samsung Electronics

    # Only run during market hours
    if not is_market_hours():
        logger.info("⚠️ Not market hours - skipping gap detection test")
        return None

    # Get real-time price from KIS
    kis_price = await get_realtime_price_from_kis(test_ticker, max_retries=2)

    if not kis_price:
        logger.warning("⚠️ KIS API failed - cannot test gap detection")
        return None

    # Get previous close from KRX
    today = datetime.datetime.now().strftime("%Y%m%d")
    trade_date = get_nearest_business_day_in_a_week(today, prev=True)

    try:
        df = get_market_ohlcv_by_ticker(trade_date)
        if test_ticker in df.index:
            krx_close = float(df.loc[test_ticker, "Close"])

            gap_amount = kis_price - krx_close
            gap_percent = (gap_amount / krx_close) * 100

            logger.info(f"KRX previous close: {krx_close:,.0f} KRW (date: {trade_date})")
            logger.info(f"KIS real-time price: {kis_price:,.0f} KRW")
            logger.info(f"Gap: {gap_amount:+,.0f} KRW ({gap_percent:+.2f}%)")

            if abs(gap_percent) > 5:
                logger.warning(f"⚠️ LARGE GAP DETECTED: {gap_percent:+.2f}%")
            else:
                logger.info(f"✅ Normal gap: {gap_percent:+.2f}%")

            return gap_percent
        else:
            logger.error(f"❌ {test_ticker} not found in KRX data")
            return None
    except Exception as e:
        logger.error(f"❌ KRX query failed: {e}")
        return None


async def test_cache_ttl():
    """Test 5: Cache TTL validation."""
    from stock_tracking_agent import StockTrackingAgent
    from datetime import datetime
    import time

    logger.info("=" * 60)
    logger.info("Test 5: Cache TTL Validation")
    logger.info("=" * 60)

    # Create agent with cached price
    test_ticker = "005930"
    cached_price = 70000

    price_cache = {
        test_ticker: {
            'price': cached_price,
            'trade_date': datetime.now().strftime("%Y%m%d"),
            'timestamp': datetime.now(),
            'source': 'realtime'
        }
    }

    agent = StockTrackingAgent(price_cache)

    # Test 1: Fresh cache (should hit)
    logger.info("Test 5a: Fresh cache (< 60s)")
    price1 = await agent._get_current_stock_price(test_ticker)
    if price1 == cached_price:
        logger.info(f"✅ Cache HIT: {price1:,.0f} KRW")
    else:
        logger.error(f"❌ Cache MISS: expected {cached_price:,.0f}, got {price1:,.0f}")

    # Test 2: Stale cache (simulate 65s old)
    logger.info("Test 5b: Stale cache (> 60s)")
    from datetime import timedelta
    agent.price_cache[test_ticker]['timestamp'] = datetime.now() - timedelta(seconds=65)

    price2 = await agent._get_current_stock_price(test_ticker)
    if price2 != cached_price:
        logger.info(f"✅ Cache EXPIRED: fetched new price {price2:,.0f} KRW")
    else:
        logger.warning(f"⚠️ Cache still used: {price2:,.0f} KRW")


async def main():
    """Run all integration tests."""
    logger.info("Starting Real-time Pricing Integration Tests")
    logger.info(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")

    results = {}

    # Test 1: Market hours detection
    try:
        in_market_hours = await test_market_hours_detection()
        results['market_hours'] = in_market_hours
    except Exception as e:
        logger.error(f"Test 1 FAILED: {e}", exc_info=True)
        results['market_hours'] = None

    print()

    # Test 2: KIS API real-time (only during market hours)
    if results.get('market_hours'):
        try:
            success, price = await test_kis_api_realtime()
            results['kis_api'] = {'success': success, 'price': price}
        except Exception as e:
            logger.error(f"Test 2 FAILED: {e}", exc_info=True)
            results['kis_api'] = {'success': False, 'price': None}
    else:
        logger.info("⏭️ Skipping Test 2 (KIS API) - not market hours")
        results['kis_api'] = {'success': None, 'price': None}

    print()

    # Test 3: Integrated price fetch
    try:
        success, price = await test_current_stock_price()
        results['integrated'] = {'success': success, 'price': price}
    except Exception as e:
        logger.error(f"Test 3 FAILED: {e}", exc_info=True)
        results['integrated'] = {'success': False, 'price': None}

    print()

    # Test 4: Gap detection (only during market hours)
    if results.get('market_hours'):
        try:
            gap = await test_gap_detection()
            results['gap'] = gap
        except Exception as e:
            logger.error(f"Test 4 FAILED: {e}", exc_info=True)
            results['gap'] = None
    else:
        logger.info("⏭️ Skipping Test 4 (Gap Detection) - not market hours")
        results['gap'] = None

    print()

    # Test 5: Cache TTL (commented out - requires real agent)
    # try:
    #     await test_cache_ttl()
    #     results['cache_ttl'] = True
    # except Exception as e:
    #     logger.error(f"Test 5 FAILED: {e}", exc_info=True)
    #     results['cache_ttl'] = False

    # Summary
    logger.info("=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)
    logger.info(f"Market hours: {results.get('market_hours')}")
    if results.get('kis_api'):
        logger.info(f"KIS API: {results['kis_api']['success']} (price: {results['kis_api']['price']})")
    logger.info(f"Integrated fetch: {results['integrated']['success']} (price: {results['integrated']['price']})")
    if results.get('gap') is not None:
        logger.info(f"Gap detected: {results['gap']:+.2f}%")

    logger.info("")
    logger.info("Integration tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
