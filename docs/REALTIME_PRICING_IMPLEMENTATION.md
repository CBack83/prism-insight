# Real-time Pricing Implementation Guide

## Overview

This document describes the implementation of real-time pricing using KIS API during market hours, addressing the issue of gap-up/gap-down scenarios where Friday's closing price differs significantly from Monday's opening price.

**Implementation Date:** 2026-02-02
**Version:** v2.0 - Real-time Aware

---

## Problem Statement

### Original Issue

**Symptom:**
- System uses `prev=True` setting → uses **previous day's closing price**
- Monday 09:50 batch → analyzes using Friday's closing price
- **Gap up/down and weekend news NOT reflected** ❌

**Example Scenario:**
```
Friday close:        10,000 KRW
Monday 09:50 actual: 13,000 KRW (+30% gap up)
System analysis:     Based on 10,000 KRW
Actual buy execution: 13,000 KRW → immediate loss risk
```

**Risk Level:** 🔴 **HIGH** - Trading decisions based on incorrect price baseline

---

## Solution Architecture

### Core Strategy: Market Hours-Aware Price Source Selection

```
During market hours (09:00-15:20)  →  KIS API real-time ✅
  ├─ Success: Return real-time price
  └─ Failure: Fallback to KRX previous close

After hours (15:30+)               →  KRX previous close ✅
  └─ Cost saving, sufficiently accurate
```

### 3-Tier Fallback Strategy

1. **Primary**: KIS API real-time (market hours only)
2. **Secondary**: KRX previous close
3. **Tertiary**: DB cache (last resort)

---

## Implementation Details

### Phase 1: Core Functions Added

#### 1.1 Market Hours Detection

**File:** `/usr/src/app/tracking/helpers.py`
**Location:** After `_get_last_price_from_db()` function (~Line 160)

**Function:** `is_market_hours()`

```python
def is_market_hours() -> bool:
    """
    Check if Korean stock market is currently in trading hours.

    Market hours: 09:00 - 15:20 KST (trading days only)

    Returns:
        bool: True if within trading hours, False otherwise
    """
```

**Logic:**
- Checks if current date is a trading day (excludes weekends, holidays, Dec 31)
- Checks if current time is within 09:00-15:20
- Returns `True` only if both conditions met

---

#### 1.2 KIS API Real-time Price Fetcher

**File:** `/usr/src/app/tracking/helpers.py`
**Location:** After `is_market_hours()` function

**Function:** `get_realtime_price_from_kis(ticker, max_retries=2)`

```python
async def get_realtime_price_from_kis(ticker: str, max_retries: int = 2) -> float:
    """
    Get real-time stock price from KIS API with retry mechanism.

    Args:
        ticker: Stock code (6 digits)
        max_retries: Maximum retry attempts (default: 2)

    Returns:
        float: Real-time current price, None on failure

    Strategy:
        - Short timeout (10s) - real-time must be fast
        - Limited retries (2 attempts) - half of KRX retries
        - Exponential backoff: 0.5s, 1s
        - Returns None on failure (caller handles fallback)
    """
```

**Key Features:**
- **Fast timeout:** 10 seconds per attempt
- **Limited retries:** 2 attempts (vs 3 for KRX)
- **Exponential backoff:** 0.5s, 1s between retries
- **Safe mode:** Uses `demo` mode (no actual trading)
- **Graceful failure:** Returns `None` on failure (caller handles fallback)

---

#### 1.3 Updated Main Price Query Function

**File:** `/usr/src/app/tracking/helpers.py`
**Function:** `get_current_stock_price()` (modified)

**New Logic Flow:**

```
┌─────────────────────────────────────┐
│   get_current_stock_price()         │
└─────────────────────────────────────┘
              ↓
    ┌─────────────────┐
    │ is_market_hours? │
    └─────────────────┘
         ↙         ↘
      YES          NO
       ↓            ↓
  ┌─────────┐  ┌─────────┐
  │ KIS API │  │   KRX   │
  │ (real)  │  │ (prev)  │
  └─────────┘  └─────────┘
       ↓            ↓
   Success?     Success?
    ↙   ↘         ↙   ↘
  YES   NO      YES   NO
   ↓     ↓       ↓     ↓
Return  KRX    Return  DB
        ↓              ↓
     Success?      Cache
      ↙   ↘
    YES   NO
     ↓     ↓
  Return  DB
         Cache
```

**Key Changes:**
1. Check if market hours first
2. During market hours: Try KIS API → fallback to KRX
3. After hours: Go directly to KRX (skip KIS)
4. Enhanced logging for debugging

---

### Phase 2: Cache Policy Updates

#### 2.1 TTL-Based Cache Validation

**File:** `/usr/src/app/stock_tracking_agent.py`
**Method:** `_get_current_stock_price()` (modified)

**New Cache Logic:**

```python
During market hours:
- TTL: 60 seconds
- Fresh cache (< 60s): Use immediately
- Stale cache (> 60s): Re-fetch

After hours:
- No TTL (historical data is immutable)
- Same trade date: Use cache
- Different trade date: Re-fetch
```

**Cache Entry Structure:**
```python
{
    'price': 70000,
    'trade_date': '20260202',
    'timestamp': datetime.now(),  # NEW: for TTL validation
    'source': 'realtime' or 'historical'  # NEW: tracking
}
```

---

## Files Modified

| File | Change Type | Lines Changed | Priority |
|------|-------------|---------------|----------|
| `/usr/src/app/tracking/helpers.py` | Added 2 functions, modified 1 | ~200 lines | P1 |
| `/usr/src/app/stock_tracking_agent.py` | Modified 1 method | ~50 lines | P2 |
| `/usr/src/app/tests/test_realtime_pricing.py` | New file | ~400 lines | Testing |
| `/usr/src/app/tests/test_realtime_integration.py` | New file | ~350 lines | Testing |

**Total:** 2 files modified, 2 test files added, ~1000 lines of code

---

## Testing

### Unit Tests

**File:** `/usr/src/app/tests/test_realtime_pricing.py`

**Run:**
```bash
# All tests
pytest tests/test_realtime_pricing.py -v

# Specific test
pytest tests/test_realtime_pricing.py::TestMarketHoursDetection::test_is_market_hours_during_trading -v
```

**Test Coverage:**
- ✅ Market hours detection (4 test cases)
- ✅ KIS API success/failure/timeout (3 test cases)
- ✅ Price fetch logic during/after hours (3 test cases)
- ✅ Cache TTL validation (3 test cases)

---

### Integration Tests

**File:** `/usr/src/app/tests/test_realtime_integration.py`

**Run:**
```bash
python tests/test_realtime_integration.py
```

**Tests:**
1. Market hours detection
2. KIS API real-time fetch (market hours only)
3. Integrated price fetch (market hours aware)
4. Gap detection (compare KIS vs KRX)

**Expected Output:**
```
Test 1: Market Hours Detection
Current time: 10:30:15
Is market hours: True
✅ System will use KIS API for real-time pricing

Test 2: KIS API Real-time Price Fetch
Testing ticker: 005930
✅ KIS API SUCCESS: 005930 = 70,000 KRW

Test 3: Integrated Price Fetch (Market Hours Aware)
Testing ticker: 005930
✅ Price fetch SUCCESS: 005930 = 70,000 KRW

Test 4: Gap Detection (KIS vs KRX)
KRX previous close: 68,000 KRW (date: 20260131)
KIS real-time price: 70,000 KRW
Gap: +2,000 KRW (+2.94%)
✅ Normal gap: +2.94%
```

---

### Manual Testing Scenarios

#### Scenario 1: Market Hours Test (Monday 10:00)

```bash
# Run orchestrator in no-telegram mode
python stock_analysis_orchestrator.py --mode morning --no-telegram

# Check logs for KIS API usage
grep "KIS API" orchestrator_$(date +%Y%m%d).log
grep "real-time" orchestrator_$(date +%Y%m%d).log

# Expected log output:
# [KIS API] 005930 real-time price query attempt 1/2
# ✅ [KIS API] 005930 real-time price: 70,000 KRW (attempt 1)
# ✅ [Real-time] 005930 = 70,000 KRW (source: KIS API)
```

---

#### Scenario 2: After Hours Test (Monday 17:00)

```bash
# Run orchestrator
python stock_analysis_orchestrator.py --mode afternoon --no-telegram

# Check logs for KRX usage
grep "KRX" orchestrator_$(date +%Y%m%d).log
grep "Historical Data" orchestrator_$(date +%Y%m%d).log

# Expected log output:
# [Historical Data] 005930 using KRX previous close (date: 20260131)
# ✅ 005930 price: 70,000 KRW (source: KRX, attempt 1)
```

---

#### Scenario 3: Gap Detection Test

```bash
# Python script to compare Friday close vs Monday real-time
python3 << 'EOF'
import asyncio
from tracking.helpers import get_current_stock_price, get_realtime_price_from_kis
import sqlite3
from krx_data_client import get_nearest_business_day_in_a_week, get_market_ohlcv_by_ticker
import datetime

async def test_gap():
    # Get KIS real-time (Monday 10:00)
    kis_price = await get_realtime_price_from_kis("005930")

    # Get KRX previous close (Friday)
    today = datetime.datetime.now().strftime("%Y%m%d")
    trade_date = get_nearest_business_day_in_a_week(today, prev=True)
    df = get_market_ohlcv_by_ticker(trade_date)
    krx_price = float(df.loc["005930", "Close"])

    gap = ((kis_price - krx_price) / krx_price) * 100

    print(f"Friday close: {krx_price:,.0f} KRW")
    print(f"Monday real-time: {kis_price:,.0f} KRW")
    print(f"Gap: {gap:+.2f}%")

asyncio.run(test_gap())
EOF
```

---

## Verification Checklist

| Item | Method | Expected Result |
|------|--------|-----------------|
| Market hours detection | `python3 -c "from tracking.helpers import is_market_hours; print(is_market_hours())"` | Market hours: `True`, After hours: `False` |
| KIS API calls | `grep "KIS API" orchestrator_*.log` | Appears during market hours only |
| KRX fallback | `grep "KRX previous close" orchestrator_*.log` | After hours or KIS failure |
| Cache TTL | `grep "Cache EXPIRED" orchestrator_*.log` | Appears when > 60s old during market hours |
| Price accuracy | Compare with Naver Finance | Within ±0.5% |

---

## Rollback Strategy

### Immediate Rollback (< 5 minutes)

**Option 1: Git Rollback**
```bash
# Revert specific files
git checkout HEAD~1 tracking/helpers.py
git checkout HEAD~1 stock_tracking_agent.py

# Commit rollback
git commit -m "rollback: Revert KIS API real-time pricing"
```

**Option 2: Feature Flag**
```bash
# Add to .env
USE_REALTIME_PRICING=false

# Or set at runtime
USE_REALTIME_PRICING=false python stock_analysis_orchestrator.py --mode morning
```

---

### Gradual Rollout (Recommended)

**Week 1: Afternoon batch only**
```bash
# Morning: Feature disabled
USE_REALTIME_PRICING=false python stock_analysis_orchestrator.py --mode morning

# Afternoon: Feature enabled (low risk - market just closed)
USE_REALTIME_PRICING=true python stock_analysis_orchestrator.py --mode afternoon
```

**Week 2: Analyze logs, then enable morning**
```bash
# Check KIS API success rate
success=$(grep -c "✅ \[KIS API\]" orchestrator_*.log)
failure=$(grep -c "❌ \[KIS API\]" orchestrator_*.log)
total=$((success + failure))
percentage=$(echo "scale=2; $success * 100 / $total" | bc)

echo "KIS API success rate: ${percentage}%"

# If > 90%, enable morning batch
if (( $(echo "$percentage > 90" | bc -l) )); then
    echo "✅ Enable morning batch"
else
    echo "⚠️ Success rate insufficient - improve first"
fi
```

**Week 3: Full deployment**
```bash
# Update crontab
crontab -e

# Morning batch (09:10)
10 9 * * 1-5 cd /usr/src/app && /usr/bin/python3 stock_analysis_orchestrator.py --mode morning

# Afternoon batch (15:30)
30 15 * * 1-5 cd /usr/src/app && /usr/bin/python3 stock_analysis_orchestrator.py --mode afternoon
```

---

### Rollback Triggers

Immediately rollback if any of the following occurs:

1. **KIS API success rate < 80%** (3 consecutive days)
2. **System error rate increase** (> 2x baseline)
3. **Buy failure rate > 50%**
4. **Price deviation > 5%** (vs actual execution price)
5. **Critical user feedback** (data corruption, trading losses)

---

## Risk Assessment

### Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| KIS API failure | Medium | Medium | KRX fallback, 2 retries |
| API cost increase | Low | Low | Market hours only, demo mode |
| Price deviation | Low | Medium | Real-time data, 60s TTL |
| Performance degradation | Medium | Low | 10s timeout, async |
| Auth failure | Low | High | Demo mode, existing auth reuse |

### Safety Mechanisms

1. **Demo mode default**: No actual trading
2. **3-tier fallback**: KIS → KRX → DB
3. **Timeouts**: All API calls 10s limit
4. **Retries**: 2-3 retries with exponential backoff
5. **Detailed logging**: All decisions logged
6. **Feature flag**: Environment variable for instant disable

---

## Expected Benefits

### Technical Improvements

✅ **Gap detection**: Accurately reflect gap-up/gap-down scenarios
✅ **Weekend news**: Capture market impact of weekend news
✅ **Price accuracy**: Significant improvement in buy price accuracy
✅ **System reliability**: Maintain stability with fallback mechanisms

### Business Impact

- **Monday morning trades**: Use real-time price instead of Friday close
- **Gap scenarios**: Detect +30% gap-ups early, avoid bad entries
- **News-driven moves**: React to weekend news immediately
- **Risk management**: Better entry prices = lower immediate loss risk

---

## Performance Characteristics

### Timing Analysis

**Before (KRX only):**
- Query time: ~5-10 seconds
- Retries: 3 attempts
- Total max: ~37 seconds

**After (KIS + KRX):**
- Market hours: 10s (KIS) + 10s (fallback) = ~20s max
- After hours: ~5-10s (KRX direct, same as before)
- Cache hit: < 1s

### API Cost Estimate

**KIS API calls:**
- Morning batch: ~10-20 stocks × 1 call = 10-20 calls/day
- Afternoon batch: ~10-20 stocks × 1 call = 10-20 calls/day
- Total: ~40 calls/day (market hours only)
- Demo mode: **FREE** (no actual trading)

---

## Success Criteria

### Technical Metrics

- ✅ KIS API success rate > 90% (market hours)
- ✅ Average response time < 3s
- ✅ Fallback mechanism working correctly
- ✅ Price deviation < 1% (vs Naver Finance)

### Business Metrics

- ✅ Gap up/down accurately detected
- ✅ Buy decision accuracy improved
- ✅ System stability maintained (error rate at baseline)

---

## Monitoring & Logging

### Key Log Patterns

**Market hours detection:**
```
{ticker} price query: market_hours = True
[Market Hours] {ticker} attempting KIS API real-time price
```

**KIS API success:**
```
✅ [KIS API] {ticker} real-time price: {price} KRW (attempt {n})
✅ [Real-time] {ticker} = {price} KRW (source: KIS API)
```

**KIS API failure (fallback):**
```
❌ [KIS API] {ticker} all attempts failed (2 retries)
⚠️ [Market Hours] {ticker} KIS API failed, falling back to KRX previous close
```

**After hours (KRX direct):**
```
[Historical Data] {ticker} using KRX previous close (date: {date})
✅ {ticker} price: {price} KRW (source: KRX, attempt {n})
```

**Cache behavior:**
```
✅ Cache HIT (real-time): {ticker} = {price} KRW (age: {seconds}s)
⚠️ Cache EXPIRED (real-time): {ticker} (age: {seconds}s > 60s TTL)
✅ Cache HIT (historical): {ticker} = {price} KRW (date: {date})
```

---

## Troubleshooting

### Issue 1: KIS API Always Fails

**Symptoms:**
- All KIS API calls fail
- Always falls back to KRX

**Diagnosis:**
```bash
# Check KIS API credentials
cat trading/config/kis_devlp.yaml | grep -E "kis_app_key|kis_account"

# Test KIS API directly
python3 << 'EOF'
from trading.domestic_stock_trading import DomesticStockTrading
trader = DomesticStockTrading(mode="demo")
print(trader.get_current_price("005930"))
EOF
```

**Solution:**
- Verify `kis_app_key` and `kis_app_secret` in `trading/config/kis_devlp.yaml`
- Check KIS API token expiration
- Run `python trading/kis_auth.py` to refresh token

---

### Issue 2: Cache Always Expires

**Symptoms:**
- Cache never hits during market hours
- Constant re-fetching

**Diagnosis:**
```bash
# Check cache timestamps in logs
grep "Cache EXPIRED" orchestrator_*.log

# Check system time sync
date
timedatectl status
```

**Solution:**
- Ensure system time is correct (NTP sync)
- Verify `datetime.now()` returns correct time
- Check `trigger_batch.py` is updating cache correctly

---

### Issue 3: Price Deviation > 5%

**Symptoms:**
- Fetched price differs significantly from Naver Finance

**Diagnosis:**
```bash
# Compare prices
python3 << 'EOF'
import asyncio
from tracking.helpers import get_realtime_price_from_kis

async def check():
    kis = await get_realtime_price_from_kis("005930")
    print(f"KIS: {kis:,.0f} KRW")
    print("Compare with Naver Finance manually")

asyncio.run(check())
EOF
```

**Solution:**
- Check if stock is halted (circuit breaker)
- Verify ticker code is correct
- Check market hours (after-hours quotes may differ)

---

## Future Enhancements

### Phase 3: Advanced Features (Optional)

1. **WebSocket Real-time Feed**
   - Replace polling with WebSocket streaming
   - Sub-second latency
   - Reduced API calls

2. **Predictive Gap Detection**
   - Pre-market futures data
   - Foreign exchange pre-market
   - News sentiment analysis

3. **Dynamic TTL**
   - High volatility: 30s TTL
   - Low volatility: 120s TTL
   - Adaptive based on market conditions

4. **Multi-Source Pricing**
   - KIS API + Naver Finance + Daum Finance
   - Median price for accuracy
   - Outlier detection

---

## References

### Internal Documentation

- [CLAUDE.md](../CLAUDE.md) - Project overview
- [CLAUDE_AGENTS.md](CLAUDE_AGENTS.md) - AI agents documentation
- [CLAUDE_TASKS.md](CLAUDE_TASKS.md) - Common tasks guide
- [CLAUDE_TROUBLESHOOTING.md](CLAUDE_TROUBLESHOOTING.md) - Troubleshooting guide

### External APIs

- [KIS API Documentation](https://apiportal.koreainvestment.com/) - Korea Investment & Securities API
- [KRX Market Data](https://www.krx.co.kr/) - Korea Exchange data

---

## Change Log

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v2.0 | 2026-02-02 | Claude Code | Initial implementation - Real-time pricing with KIS API |

---

## Support

For questions or issues:

1. **GitHub Issues**: [prism-insight/issues](https://github.com/dragon1086/prism-insight/issues)
2. **Logs**: Check `orchestrator_YYYYMMDD.log` for detailed execution logs
3. **Tests**: Run integration tests for diagnostics

---

**Document Status:** ✅ **IMPLEMENTATION COMPLETE**
**Last Updated:** 2026-02-02
**Maintained By:** PRISM-INSIGHT Development Team
