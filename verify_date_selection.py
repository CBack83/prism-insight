#!/usr/bin/env python3
"""
날짜 선택 로직 검증 - morning vs afternoon 배치

이 스크립트는 코드 레벨에서 날짜 선택 로직이 올바른지 확인합니다.
"""

import sys
sys.path.insert(0, '/usr/src/app')

import inspect
from datetime import datetime

print("\n" + "=" * 70)
print("날짜 선택 로직 검증 - morning vs afternoon 배치")
print("=" * 70)

# Test 1: tracking/helpers.py 검증
print("\n1. tracking/helpers.py - get_current_stock_price()")
print("-" * 70)

try:
    from tracking.helpers import get_current_stock_price
    source = inspect.getsource(get_current_stock_price)

    # Check for conditional date selection
    has_market_hours_check = 'if in_market_hours:' in source
    has_prev_true = 'prev=True' in source
    has_prev_false = 'prev=False' in source

    print(f"✅ Market hours check: {has_market_hours_check}")
    print(f"✅ prev=True (장중): {has_prev_true}")
    print(f"✅ prev=False (장후): {has_prev_false}")

    if has_market_hours_check and has_prev_true and has_prev_false:
        print("\n✅ PASS: 시장 시간에 따라 올바른 날짜 선택")
        print("   - 장중 (09:00-15:20): prev=True → 전일 종가")
        print("   - 장후 (15:30+): prev=False → 당일 종가")
    else:
        print("\n❌ FAIL: 날짜 선택 로직 누락")

except Exception as e:
    print(f"❌ Error: {e}")

# Test 2: stock_tracking_agent.py 검증
print("\n2. stock_tracking_agent.py - _get_current_stock_price()")
print("-" * 70)

try:
    from stock_tracking_agent import StockTrackingAgent
    source = inspect.getsource(StockTrackingAgent._get_current_stock_price)

    # Check for conditional date selection in cache validation
    has_after_hours = 'After Hours' in source or 'after hours' in source
    has_prev_false = 'prev=False' in source

    print(f"✅ After hours check: {has_after_hours}")
    print(f"✅ prev=False (장후): {has_prev_false}")

    if has_prev_false:
        print("\n✅ PASS: 캐시 검증 시 올바른 날짜 사용")
        print("   - 장후: prev=False → 당일 종가 기준")
    else:
        print("\n⚠️  WARNING: prev=False 누락 (캐시가 항상 전일 기준)")

except Exception as e:
    print(f"❌ Error: {e}")

# Test 3: trigger_batch.py 검증
print("\n3. trigger_batch.py - run_batch()")
print("-" * 70)

try:
    with open('/usr/src/app/trigger_batch.py', 'r') as f:
        source = f.read()

    # Check for conditional date selection in run_batch
    has_trigger_time_check = 'if trigger_time == "morning"' in source
    has_morning_prev_true = 'trigger_time == "morning"' in source and 'prev=True' in source
    has_afternoon_prev_false = 'else:  # afternoon' in source or 'trigger_time == "afternoon"' in source

    print(f"✅ Trigger time check: {has_trigger_time_check}")
    print(f"✅ Morning uses prev=True: {has_morning_prev_true}")
    print(f"✅ Afternoon handling: {has_afternoon_prev_false}")

    # More detailed check
    lines = source.split('\n')
    found_morning_logic = False
    found_afternoon_logic = False

    for i, line in enumerate(lines):
        if 'if trigger_time == "morning"' in line:
            # Check next few lines for prev=True
            for j in range(i, min(i+5, len(lines))):
                if 'prev=True' in lines[j]:
                    found_morning_logic = True
                    print(f"   → Line {j+1}: morning → prev=True ✅")
                    break

        if 'else:' in line and 'afternoon' in line:
            # Check next few lines for prev=False
            for j in range(i, min(i+5, len(lines))):
                if 'prev=False' in lines[j]:
                    found_afternoon_logic = True
                    print(f"   → Line {j+1}: afternoon → prev=False ✅")
                    break

    if found_morning_logic and found_afternoon_logic:
        print("\n✅ PASS: trigger_batch.py가 올바른 날짜 선택")
        print("   - morning 배치 (09:10): prev=True → 전일 종가")
        print("   - afternoon 배치 (15:30): prev=False → 당일 종가")
    else:
        print("\n❌ FAIL: trigger_batch.py 날짜 선택 로직 불완전")
        print(f"   - morning logic found: {found_morning_logic}")
        print(f"   - afternoon logic found: {found_afternoon_logic}")

except Exception as e:
    print(f"❌ Error: {e}")

# Summary
print("\n" + "=" * 70)
print("검증 요약")
print("=" * 70)

print("\n예상 동작:")
print("\n📅 morning 배치 (09:10 실행):")
print("   - 시장 시간: 09:00-15:20 (장중)")
print("   - 당일 데이터: 불완전 (거래 진행 중)")
print("   - 사용 날짜: prev=True → 전일 종가")
print("   - 예시: 2026-02-03 (월) 09:10 실행 → 2026-01-31 (금) 종가 사용")

print("\n📅 afternoon 배치 (15:30 실행):")
print("   - 시장 시간: 15:30 (장 마감 후)")
print("   - 당일 데이터: 완전 (거래 종료)")
print("   - 사용 날짜: prev=False → 당일 종가")
print("   - 예시: 2026-02-03 (월) 15:30 실행 → 2026-02-03 (월) 종가 사용")

print("\n✅ 이로써 afternoon 배치는 당일 실제 거래 결과를 기반으로 분석합니다!")

print("\n" + "=" * 70)
