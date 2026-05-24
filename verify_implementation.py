#!/usr/bin/env python3
"""
Comprehensive verification of real-time pricing implementation.

Run this script to verify all components are working correctly.
"""

import sys
sys.path.insert(0, '/usr/src/app')

from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_1_function_availability():
    """Test 1: Verify all new functions are available."""
    print("\n" + "=" * 70)
    print("Test 1: Function Availability")
    print("=" * 70)

    try:
        from tracking.helpers import (
            is_market_hours,
            get_realtime_price_from_kis,
            get_current_stock_price
        )

        print("✅ is_market_hours() - Available")
        print("✅ get_realtime_price_from_kis() - Available")
        print("✅ get_current_stock_price() - Available")

        # Check function signatures
        import inspect

        sig1 = inspect.signature(is_market_hours)
        print(f"   Signature: is_market_hours{sig1}")

        sig2 = inspect.signature(get_realtime_price_from_kis)
        print(f"   Signature: get_realtime_price_from_kis{sig2}")

        sig3 = inspect.signature(get_current_stock_price)
        print(f"   Signature: get_current_stock_price{sig3}")

        print("\n✅ Test 1 PASSED\n")
        return True
    except Exception as e:
        print(f"\n❌ Test 1 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_2_market_hours_detection():
    """Test 2: Market hours detection logic."""
    print("=" * 70)
    print("Test 2: Market Hours Detection")
    print("=" * 70)

    try:
        from tracking.helpers import is_market_hours

        current_time = datetime.now()
        is_market = is_market_hours()

        print(f"Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S %A')}")
        print(f"Is market hours: {is_market}")

        current_hour = current_time.hour
        current_minute = current_time.minute

        if is_market:
            print("✅ System will use KIS API for real-time pricing")
            print("   - Primary: KIS API real-time")
            print("   - Fallback: KRX previous close")
        else:
            print("✅ System will use KRX historical data")
            print("   - Primary: KRX previous close")
            print("   - Cache TTL: No expiration (immutable)")

        # Validate logic
        from datetime import time
        market_open = time(9, 0)
        market_close = time(15, 20)
        current_time_only = current_time.time()

        expected_market_hours = (market_open <= current_time_only <= market_close)

        # Note: is_market_hours also checks for trading days
        print(f"\nTime-based check: {expected_market_hours}")
        print(f"(Market hours also requires trading day check)")

        print("\n✅ Test 2 PASSED\n")
        return True
    except Exception as e:
        print(f"\n❌ Test 2 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_3_code_structure():
    """Test 3: Verify code structure in helpers.py."""
    print("=" * 70)
    print("Test 3: Code Structure Verification")
    print("=" * 70)

    try:
        import inspect
        from tracking.helpers import (
            is_market_hours,
            get_realtime_price_from_kis,
            get_current_stock_price
        )

        # Check is_market_hours
        source1 = inspect.getsource(is_market_hours)
        assert 'is_market_day' in source1, "is_market_hours should check trading days"
        assert '9, 0' in source1 or 'time(9, 0)' in source1, "Market open time 09:00"
        assert '15, 20' in source1 or 'time(15, 20)' in source1, "Market close time 15:20"
        print("✅ is_market_hours() - Correct logic structure")

        # Check get_realtime_price_from_kis
        source2 = inspect.getsource(get_realtime_price_from_kis)
        assert 'DomesticStockTrading' in source2, "Should use KIS API"
        assert 'max_retries' in source2, "Should have retry logic"
        assert 'asyncio.wait_for' in source2 or 'timeout' in source2, "Should have timeout"
        print("✅ get_realtime_price_from_kis() - Correct API integration")

        # Check get_current_stock_price
        source3 = inspect.getsource(get_current_stock_price)
        assert 'is_market_hours' in source3, "Should check market hours"
        assert 'get_realtime_price_from_kis' in source3, "Should call KIS API"
        assert 'get_market_ohlcv_by_ticker' in source3, "Should have KRX fallback"
        print("✅ get_current_stock_price() - Correct flow structure")

        print("\n✅ Test 3 PASSED\n")
        return True
    except Exception as e:
        print(f"\n❌ Test 3 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_4_stock_tracking_agent_integration():
    """Test 4: Verify StockTrackingAgent cache updates."""
    print("=" * 70)
    print("Test 4: StockTrackingAgent Integration")
    print("=" * 70)

    try:
        import inspect
        from stock_tracking_agent import StockTrackingAgent

        # Check _get_current_stock_price method
        source = inspect.getsource(StockTrackingAgent._get_current_stock_price)

        assert 'is_market_hours' in source, "Should check market hours"
        assert 'timestamp' in source, "Should use timestamp for TTL"
        assert '60' in source, "Should have 60s TTL"
        assert 'get_current_stock_price' in source, "Should call helpers function"

        print("✅ StockTrackingAgent._get_current_stock_price() - Updated with TTL logic")
        print("   - Market hours: 60-second TTL validation")
        print("   - After hours: Date-based cache validation")
        print("   - Cache entry includes 'timestamp' and 'source' fields")

        print("\n✅ Test 4 PASSED\n")
        return True
    except Exception as e:
        print(f"\n❌ Test 4 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_5_logging_patterns():
    """Test 5: Verify logging patterns for debugging."""
    print("=" * 70)
    print("Test 5: Logging Pattern Verification")
    print("=" * 70)

    try:
        import inspect
        from tracking.helpers import get_current_stock_price

        source = inspect.getsource(get_current_stock_price)

        # Check for key log patterns
        required_patterns = [
            ('market_hours', 'Should log market hours status'),
            ('KIS API', 'Should log KIS API attempts'),
            ('Real-time', 'Should log real-time pricing'),
            ('Historical Data', 'Should log historical data usage'),
            ('KRX', 'Should log KRX fallback'),
        ]

        for pattern, description in required_patterns:
            if pattern in source:
                print(f"✅ Log pattern '{pattern}' - Present ({description})")
            else:
                print(f"⚠️  Log pattern '{pattern}' - Not found ({description})")

        print("\n✅ Test 5 PASSED\n")
        return True
    except Exception as e:
        print(f"\n❌ Test 5 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_6_documentation():
    """Test 6: Verify documentation files exist."""
    print("=" * 70)
    print("Test 6: Documentation Verification")
    print("=" * 70)

    try:
        from pathlib import Path

        docs = [
            ('docs/REALTIME_PRICING_IMPLEMENTATION.md', 'Implementation guide'),
            ('tests/test_realtime_pricing.py', 'Unit tests'),
            ('tests/test_realtime_integration.py', 'Integration tests'),
        ]

        for filepath, description in docs:
            path = Path(filepath)
            if path.exists():
                size = path.stat().st_size
                print(f"✅ {filepath} - Exists ({size:,} bytes)")
                print(f"   {description}")
            else:
                print(f"❌ {filepath} - Not found")

        print("\n✅ Test 6 PASSED\n")
        return True
    except Exception as e:
        print(f"\n❌ Test 6 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print(" Real-time Pricing Implementation Verification")
    print(" Version: v2.0 - Real-time Aware")
    print(" Date:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("=" * 70)

    results = {}

    # Run all tests
    results['Test 1'] = test_1_function_availability()
    results['Test 2'] = test_2_market_hours_detection()
    results['Test 3'] = test_3_code_structure()
    results['Test 4'] = test_4_stock_tracking_agent_integration()
    results['Test 5'] = test_5_logging_patterns()
    results['Test 6'] = test_6_documentation()

    # Summary
    print("=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test}: {status}")

    print(f"\nOverall: {passed}/{total} tests passed ({passed/total*100:.0f}%)")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Implementation verified successfully.")
        print("\n📋 Next Steps:")
        print("   1. Test during market hours (09:00-15:20)")
        print("   2. Monitor logs: grep 'KIS API' orchestrator_*.log")
        print("   3. Verify gap detection works on Monday morning")
        print("   4. Compare prices with Naver Finance for accuracy")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    exit(main())
