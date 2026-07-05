#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Surge Detector Module

Data retrieval and caching functions for US stock surge detection.
Uses yfinance for market data access.
"""

import datetime
import logging
import os
import pandas as pd
import numpy as np
import yfinance as yf
import sys
import time
from pathlib import Path
from typing import Tuple, Optional, List

# Import check_market_day functions for US holiday handling
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_market_day import get_last_trading_day, get_next_trading_day, is_us_market_day

# Logger setup
logger = logging.getLogger(__name__)

# yfinance can open small SQLite cache files for cookies/timezones. Cron/launchd
# environments often have a different HOME/XDG setup than an interactive shell,
# and yfinance's parallel downloader may then emit noisy
# "OperationalError: unable to open database file" failures. Pin the cache to a
# project-local writable directory before any download calls.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
YFINANCE_CACHE_DIR = PROJECT_ROOT / ".cache" / "yfinance"
YFINANCE_BATCH_SIZE = int(os.getenv("PRISM_US_YF_BATCH_SIZE", "50"))
YFINANCE_RETRIES = int(os.getenv("PRISM_US_YF_RETRIES", "2"))
YFINANCE_RETRY_SLEEP_SECONDS = float(os.getenv("PRISM_US_YF_RETRY_SLEEP_SECONDS", "1.0"))
YFINANCE_MIN_COVERAGE = float(os.getenv("PRISM_US_YF_MIN_COVERAGE", "0.80"))


def _configure_yfinance_cache() -> None:
    """Use a stable, writable yfinance cache location for scheduled batches."""
    try:
        YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("XDG_CACHE_HOME", str(PROJECT_ROOT / ".cache"))
        if hasattr(yf, "set_tz_cache_location"):
            yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
        try:
            import yfinance.cache as yf_cache
            if hasattr(yf_cache, "set_cache_location"):
                yf_cache.set_cache_location(str(YFINANCE_CACHE_DIR))
        except Exception as cache_error:
            logger.debug(f"Unable to set yfinance.cache location: {cache_error}")
        test_file = YFINANCE_CACHE_DIR / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        logger.debug(f"yfinance cache directory: {YFINANCE_CACHE_DIR}")
    except Exception as e:
        logger.error(f"Failed to initialize yfinance cache directory {YFINANCE_CACHE_DIR}: {e}")
        raise


_configure_yfinance_cache()


def _ticker_chunks(tickers: List[str], size: int = YFINANCE_BATCH_SIZE):
    """Yield non-empty ticker chunks while preserving order."""
    for i in range(0, len(tickers), size):
        chunk = tickers[i:i + size]
        if chunk:
            yield chunk


def _download_ohlcv_batch(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    """Download one yfinance chunk with conservative concurrency settings."""
    return yf.download(
        tickers,
        start=start,
        end=end,
        progress=False,
        threads=False,
        group_by="column",
    )


def _extract_rows_for_date(data: pd.DataFrame, tickers: List[str], target_date: str,
                           label: str) -> Tuple[pd.DataFrame, str]:
    """Extract one OHLCV row per ticker for target_date from a yf.download result."""
    if data is None or data.empty:
        return pd.DataFrame(), ""

    available_dates = data.index.strftime('%Y%m%d').tolist()
    if target_date not in available_dates:
        logger.warning(
            f"{label}: target date {target_date} not available in yfinance response "
            f"(available: {available_dates[-3:] if available_dates else []})"
        )
        return pd.DataFrame(), ""

    target_idx = data.index[available_dates.index(target_date)]
    rows = []

    if isinstance(data.columns, pd.MultiIndex):
        for ticker in tickers:
            try:
                row = {
                    'Ticker': ticker,
                    'Open': data.loc[target_idx, ('Open', ticker)],
                    'High': data.loc[target_idx, ('High', ticker)],
                    'Low': data.loc[target_idx, ('Low', ticker)],
                    'Close': data.loc[target_idx, ('Close', ticker)],
                    'Volume': data.loc[target_idx, ('Volume', ticker)],
                }
                rows.append(row)
            except Exception:
                continue
    elif len(tickers) == 1:
        ticker = tickers[0]
        try:
            row = {
                'Ticker': ticker,
                'Open': data.loc[target_idx, 'Open'],
                'High': data.loc[target_idx, 'High'],
                'Low': data.loc[target_idx, 'Low'],
                'Close': data.loc[target_idx, 'Close'],
                'Volume': data.loc[target_idx, 'Volume'],
            }
            rows.append(row)
        except Exception:
            pass

    snapshot = pd.DataFrame(rows)
    if snapshot.empty:
        return snapshot, target_date

    snapshot = snapshot.set_index('Ticker')
    snapshot['Amount'] = snapshot['Close'] * snapshot['Volume']
    snapshot = snapshot.dropna()
    snapshot = snapshot[(snapshot['Close'] > 0) & (snapshot['Volume'] >= 0)]
    return snapshot, target_date


def _download_snapshot_with_retries(tickers: List[str], start_date: datetime.date,
                                    target_date: datetime.date, label: str) -> pd.DataFrame:
    """Chunked yfinance OHLCV retrieval with retry and fail-closed coverage gate."""
    target_str = target_date.strftime('%Y%m%d')
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = (target_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    expected = len(tickers)
    collected = []
    remaining = list(dict.fromkeys(tickers))

    for attempt in range(YFINANCE_RETRIES + 1):
        if not remaining:
            break
        attempt_rows = []
        logger.info(
            f"{label}: yfinance download attempt {attempt + 1}/{YFINANCE_RETRIES + 1} "
            f"for {len(remaining)} ticker(s), chunk_size={YFINANCE_BATCH_SIZE}"
        )
        for chunk in _ticker_chunks(remaining):
            try:
                data = _download_ohlcv_batch(chunk, start_str, end_str)
                rows, _ = _extract_rows_for_date(data, chunk, target_str, label)
                if not rows.empty:
                    attempt_rows.append(rows)
            except Exception as e:
                logger.warning(f"{label}: yfinance chunk failed ({len(chunk)} tickers): {e}")

        if attempt_rows:
            attempt_df = pd.concat(attempt_rows)
            collected.append(attempt_df)
            found = set(pd.concat(collected).index.tolist())
            remaining = [ticker for ticker in tickers if ticker not in found]
            logger.info(
                f"{label}: retrieved {len(found)}/{expected} ticker(s); "
                f"remaining={len(remaining)}"
            )

        if remaining and attempt < YFINANCE_RETRIES:
            time.sleep(YFINANCE_RETRY_SLEEP_SECONDS * (attempt + 1))

    if not collected:
        raise ValueError(f"{label}: No OHLCV data for {target_str}")

    snapshot = pd.concat(collected)
    snapshot = snapshot[~snapshot.index.duplicated(keep='first')]
    coverage = len(snapshot) / expected if expected else 1.0
    failed = [ticker for ticker in tickers if ticker not in set(snapshot.index)]
    if failed:
        logger.warning(
            f"{label}: {len(failed)} ticker(s) missing after retries "
            f"(coverage={coverage:.1%}); sample={failed[:20]}"
        )

    if coverage < YFINANCE_MIN_COVERAGE:
        raise ValueError(
            f"{label}: yfinance coverage {coverage:.1%} below fail-closed threshold "
            f"{YFINANCE_MIN_COVERAGE:.0%} ({len(snapshot)}/{expected})"
        )

    logger.info(f"{label}: final yfinance coverage {coverage:.1%} ({len(snapshot)}/{expected})")
    return snapshot


def get_sp500_tickers() -> List[str]:
    """
    Get list of S&P 500 tickers from Wikipedia.

    Returns:
        List of ticker symbols
    """
    import requests
    from io import StringIO

    try:
        # Wikipedia requires User-Agent header to avoid 403 Forbidden
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse HTML tables
        tables = pd.read_html(StringIO(response.text))
        table = tables[0]

        tickers = table['Symbol'].tolist()
        # Clean up tickers (some have dots that need to be replaced with dashes for yfinance)
        tickers = [t.replace('.', '-') for t in tickers]
        logger.info(f"Loaded {len(tickers)} S&P 500 tickers from Wikipedia")
        return tickers
    except Exception as e:
        logger.error(f"Failed to load S&P 500 tickers: {e}")
        # Fallback to major stocks
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
            "UNH", "JNJ", "JPM", "V", "PG", "XOM", "HD", "CVX", "MA", "ABBV",
            "MRK", "LLY", "PEP", "KO", "COST", "AVGO", "MCD", "TMO", "WMT",
            "CSCO", "ACN", "ABT", "DHR", "NEE", "LIN", "PM", "TXN", "CMCSA"
        ]


def get_nasdaq100_tickers() -> List[str]:
    """
    Get list of NASDAQ-100 tickers.

    Returns:
        List of ticker symbols
    """
    import requests
    from io import StringIO

    try:
        # Wikipedia requires User-Agent header to avoid 403 Forbidden
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        url = 'https://en.wikipedia.org/wiki/Nasdaq-100'

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Parse HTML tables (NASDAQ-100 table is usually the 4th or 5th table)
        tables = pd.read_html(StringIO(response.text))
        # Find the table with 'Ticker' column
        for table in tables:
            if 'Ticker' in table.columns:
                tickers = table['Ticker'].tolist()
                tickers = [t.replace('.', '-') for t in tickers]
                logger.info(f"Loaded {len(tickers)} NASDAQ-100 tickers from Wikipedia")
                return tickers

        logger.warning("Could not find NASDAQ-100 table with 'Ticker' column")
        return []
    except Exception as e:
        logger.error(f"Failed to load NASDAQ-100 tickers: {e}")
        return []


def get_major_tickers() -> List[str]:
    """
    Get combined list of major US stock tickers (S&P 500 + NASDAQ-100).
    Removes duplicates.

    Returns:
        List of unique ticker symbols
    """
    sp500 = set(get_sp500_tickers())
    nasdaq100 = set(get_nasdaq100_tickers())
    combined = sp500.union(nasdaq100)
    logger.info(f"Total unique tickers: {len(combined)}")
    return list(combined)


def get_snapshot(trade_date: str, tickers: List[str] = None) -> pd.DataFrame:
    """
    Get OHLCV snapshot for all specified tickers on the given date.

    Args:
        trade_date: Trading date in YYYYMMDD format
        tickers: List of ticker symbols (default: S&P 500)

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume, Amount
        Index: Ticker symbols
    """
    logger.debug(f"get_snapshot called: {trade_date}")

    if tickers is None:
        tickers = get_sp500_tickers()

    end_date = datetime.datetime.strptime(trade_date, '%Y%m%d').date()
    start_date = end_date - datetime.timedelta(days=5)  # Get a few days for safety

    try:
        snapshot = _download_snapshot_with_retries(
            tickers=tickers,
            start_date=start_date,
            target_date=end_date,
            label=f"snapshot[{trade_date}]",
        )

        logger.debug(f"Snapshot data sample:\n{snapshot.head()}")
        logger.info(f"Retrieved snapshot for {len(snapshot)} tickers")
        return snapshot

    except Exception as e:
        logger.error(f"Error getting snapshot: {e}")
        raise ValueError(f"Failed to get snapshot for {trade_date}: {e}")

def get_previous_snapshot(trade_date: str, tickers: List[str] = None) -> Tuple[pd.DataFrame, str]:
    """
    Get OHLCV snapshot for the previous trading day.

    Args:
        trade_date: Trading date in YYYYMMDD format
        tickers: List of ticker symbols

    Returns:
        Tuple of (DataFrame, previous_date_string)
    """
    if tickers is None:
        tickers = get_sp500_tickers()

    # Calculate previous trading day using US market calendar.
    date_obj = datetime.datetime.strptime(trade_date, '%Y%m%d').date()
    prev_date_obj = get_last_trading_day(date_obj - datetime.timedelta(days=1))
    prev_date = prev_date_obj.strftime('%Y%m%d')
    logger.info(f"Previous snapshot: trade_date={trade_date}, prev_trading_day={prev_date}")

    start_date = prev_date_obj - datetime.timedelta(days=7)

    try:
        snapshot = _download_snapshot_with_retries(
            tickers=tickers,
            start_date=start_date,
            target_date=prev_date_obj,
            label=f"previous_snapshot[{prev_date}]",
        )

        logger.debug(f"Previous trading day: {prev_date}")
        logger.info(f"Retrieved previous snapshot for {len(snapshot)} tickers")
        return snapshot, prev_date

    except Exception as e:
        logger.error(f"Error getting previous snapshot: {e}")
        raise ValueError(f"Failed to get previous snapshot: {e}")

def get_multi_day_ohlcv(ticker: str, end_date: str, days: int = 10) -> pd.DataFrame:
    """
    Get N days of OHLCV data for a specific ticker.

    Args:
        ticker: Stock ticker symbol
        end_date: End date in YYYYMMDD format
        days: Number of trading days to retrieve

    Returns:
        DataFrame with OHLCV data
    """
    end_dt = datetime.datetime.strptime(end_date, '%Y%m%d')
    start_dt = end_dt - datetime.timedelta(days=days * 2)  # Extra buffer for non-trading days

    try:
        data = yf.download(
            ticker,
            start=start_dt.strftime('%Y-%m-%d'),
            end=(end_dt + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
            progress=False,
            threads=False
        )

        if data.empty:
            logger.warning(f"No {days}-day data for {ticker}")
            return pd.DataFrame()

        return data.tail(days)

    except Exception as e:
        logger.error(f"Error getting multi-day data for {ticker}: {e}")
        return pd.DataFrame()


def get_market_cap_df(tickers: List[str] = None) -> pd.DataFrame:
    """
    Get market capitalization data for all tickers.

    Args:
        tickers: List of ticker symbols

    Returns:
        DataFrame with market cap data, indexed by ticker
    """
    if tickers is None:
        tickers = get_sp500_tickers()

    logger.debug(f"Getting market cap for {len(tickers)} tickers")

    market_caps = {}

    # Process in batches for efficiency
    batch_size = 50
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]

        for ticker in batch:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                market_cap = info.get('marketCap', 0)
                if market_cap and market_cap > 0:
                    market_caps[ticker] = {'MarketCap': market_cap}
            except Exception as e:
                logger.debug(f"Error getting market cap for {ticker}: {e}")
                continue

    if not market_caps:
        logger.error("No market cap data retrieved")
        return pd.DataFrame()

    cap_df = pd.DataFrame.from_dict(market_caps, orient='index')
    logger.info(f"Retrieved market cap for {len(cap_df)} tickers")

    return cap_df


def get_ticker_name(ticker: str) -> str:
    """
    Get company name for a ticker symbol.

    Args:
        ticker: Stock ticker symbol

    Returns:
        Company name or empty string if not found
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return info.get('shortName', info.get('longName', ''))
    except Exception:
        return ''


def get_nearest_business_day(date_str: str, prev: bool = True) -> str:
    """
    Get the nearest business day (handles weekends AND US market holidays).

    Uses pandas-market-calendars NYSE calendar to properly handle:
    - Weekends (Saturday, Sunday)
    - US Market Holidays (MLK Day, Presidents Day, Good Friday, etc.)

    Args:
        date_str: Date in YYYYMMDD format
        prev: If True, look for previous/current trading day; if False, look for next

    Returns:
        Date string in YYYYMMDD format
    """
    date_obj = datetime.datetime.strptime(date_str, '%Y%m%d').date()

    if prev:
        # Get most recent trading day ON OR BEFORE the given date
        result = get_last_trading_day(date_obj)
    else:
        # Get next trading day AFTER the given date
        result = get_next_trading_day(date_obj)

    return result.strftime('%Y%m%d')


def filter_low_liquidity(df: pd.DataFrame, threshold: float = 0.2) -> pd.DataFrame:
    """
    Filter out stocks with volume in the bottom N percentile.

    Args:
        df: DataFrame with Volume column
        threshold: Percentile threshold (default: bottom 20%)

    Returns:
        Filtered DataFrame
    """
    volume_cutoff = np.percentile(df['Volume'], threshold * 100)
    return df[df['Volume'] > volume_cutoff]


def apply_absolute_filters(df: pd.DataFrame, min_value: float = 10000000) -> pd.DataFrame:
    """
    Apply absolute value filters:
    - Minimum trading value (default: $10M)
    - Sufficient liquidity (>20% of market average volume)

    Args:
        df: DataFrame with Amount and Volume columns
        min_value: Minimum trading value in USD (default: $10M)

    Returns:
        Filtered DataFrame
    """
    # Minimum trading value filter ($10M)
    filtered_df = df[df['Amount'] >= min_value].copy()

    # Filter for stocks with >= 20% of market average volume
    avg_volume = df['Volume'].mean()
    min_volume = avg_volume * 0.2
    filtered_df = filtered_df[filtered_df['Volume'] >= min_volume]

    return filtered_df


def normalize_and_score(df: pd.DataFrame, ratio_col: str, abs_col: str,
                       ratio_weight: float = 0.6, abs_weight: float = 0.4,
                       ascending: bool = False) -> pd.DataFrame:
    """
    Calculate composite score using normalized values.

    Args:
        df: DataFrame with specified columns
        ratio_col: Column name for ratio metric
        abs_col: Column name for absolute metric
        ratio_weight: Weight for ratio (default: 0.6)
        abs_weight: Weight for absolute (default: 0.4)
        ascending: Sort order (default: False for descending)

    Returns:
        DataFrame with composite score column
    """
    if df.empty:
        return df

    result = df.copy()

    # Normalize columns
    ratio_max = result[ratio_col].max()
    ratio_min = result[ratio_col].min()
    abs_max = result[abs_col].max()
    abs_min = result[abs_col].min()

    ratio_range = ratio_max - ratio_min if ratio_max > ratio_min else 1
    abs_range = abs_max - abs_min if abs_max > abs_min else 1

    result[f"{ratio_col}_norm"] = (result[ratio_col] - ratio_min) / ratio_range
    result[f"{abs_col}_norm"] = (result[abs_col] - abs_min) / abs_range

    # Calculate composite score
    result["CompositeScore"] = (
        result[f"{ratio_col}_norm"] * ratio_weight +
        result[f"{abs_col}_norm"] * abs_weight
    )

    return result.sort_values("CompositeScore", ascending=ascending)


def enhance_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add company names to DataFrame.

    Args:
        df: DataFrame indexed by ticker symbols

    Returns:
        DataFrame with CompanyName column added
    """
    if not df.empty:
        result = df.copy()
        result["CompanyName"] = result.index.map(get_ticker_name)
        return result
    return df
