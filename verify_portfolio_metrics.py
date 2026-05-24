#!/usr/bin/env python3
"""
포트폴리오 수익률 및 승률 검증 스크립트

실제 거래 내역과 AI가 제공하는 메트릭이 일치하는지 확인합니다.

개선 사항:
- 비동기 일관성 유지 (async/await 패턴)
- 강화된 에러 처리 및 graceful degradation
- 환경 변수 지원 (DB 경로)
- 금액 기반 수익률 계산 추가
- DB/API 데이터 일관성 검증
- 최적화된 로깅 및 JSON 출력
"""

import asyncio
import aiosqlite
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
import sys
import os
from dataclasses import dataclass
from datetime import datetime
import json

# Add trading directory to path
sys.path.insert(0, str(Path(__file__).parent / "trading"))

from domestic_stock_trading import DomesticStockTrading

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== Configuration ====================

# Database path with environment variable support
PRISM_DB = Path(os.getenv("PRISM_DB_PATH",
                          Path(__file__).parent / "stock_tracking_db.sqlite"))

# Default trading mode ('demo' or 'real')
DEFAULT_MODE = os.getenv("PRISM_MODE", "demo")

# Default buy amount from config
DEFAULT_BUY_AMOUNT = 10_000  # 1만원 단위

# Output configuration
ENABLE_JSON_OUTPUT = os.getenv("PRISM_VERIFICATION_JSON", "true").lower() == "true"
JSON_OUTPUT_PATH = Path("portfolio_verification_result.json")


# ==================== Data Classes ====================

@dataclass
class PortfolioMetrics:
    """포트폴리오 메트릭 데이터 클래스"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    cumulative_return: float = 0.0
    avg_return_per_trade: float = 0.0
    avg_holding_days: float = 0.0
    # 금액 기반 메트릭 추가
    total_invested_amount: float = 0.0
    total_profit_amount: float = 0.0
    actual_return_by_amount: float = 0.0


# ==================== Database Functions ====================

async def get_prism_trades() -> List[Dict]:
    """
    PRISM 트레이딩 DB에서 거래 내역 조회

    Returns:
        청산 완료된 거래 내역 리스트
    """
    # DB 파일 존재 여부 확인
    if not PRISM_DB.exists():
        logger.error(f"❌ DB 파일이 존재하지 않습니다: {PRISM_DB}")
        logger.info("💡 먼저 트레이딩 시스템을 실행하여 DB를 생성하세요.")
        return []

    try:
        async with aiosqlite.connect(PRISM_DB) as db:
            db.row_factory = aiosqlite.Row

            # 청산 완료된 모든 거래 조회
            async with db.execute("""
                SELECT
                    id,
                    ticker,
                    company_name,
                    buy_price,
                    buy_date,
                    sell_price,
                    sell_date,
                    profit_rate,
                    holding_days,
                    scenario
                FROM trading_history
                ORDER BY id
            """) as cursor:
                rows = await cursor.fetchall()
                trades = [dict(row) for row in rows]
                logger.debug(f"DB에서 {len(trades)}건의 거래 내역 조회 완료")
                return trades

    except aiosqlite.Error as e:
        logger.error(f"❌ DB 조회 실패: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"❌ 예상치 못한 오류: {e}", exc_info=True)
        return []


async def get_current_holdings() -> List[Dict]:
    """
    현재 보유 종목 조회

    Returns:
        현재 보유 중인 종목 리스트
    """
    if not PRISM_DB.exists():
        logger.error(f"❌ DB 파일이 존재하지 않습니다: {PRISM_DB}")
        return []

    try:
        async with aiosqlite.connect(PRISM_DB) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("""
                SELECT
                    ticker,
                    company_name,
                    buy_price,
                    buy_date,
                    scenario
                FROM stock_holdings
                ORDER BY buy_date
            """) as cursor:
                rows = await cursor.fetchall()
                holdings = [dict(row) for row in rows]
                logger.debug(f"DB에서 {len(holdings)}개 보유 종목 조회 완료")
                return holdings

    except aiosqlite.Error as e:
        logger.error(f"❌ 보유 종목 조회 실패: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"❌ 예상치 못한 오류: {e}", exc_info=True)
        return []


# ==================== Metrics Calculation ====================

async def calculate_metrics_manually(trades: List[Dict]) -> PortfolioMetrics:
    """
    거래 내역으로부터 수동으로 메트릭 계산

    Args:
        trades: 거래 내역 리스트

    Returns:
        계산된 포트폴리오 메트릭
    """
    if not trades:
        return PortfolioMetrics()

    # 기본 통계
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t['profit_rate'] > 0)
    losing_trades = sum(1 for t in trades if t['profit_rate'] <= 0)

    # 승률 계산
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    # 평균 수익률 계산
    avg_return = sum(t['profit_rate'] for t in trades) / total_trades

    # 평균 보유일
    avg_holding_days = sum(t['holding_days'] for t in trades) / total_trades

    # 누적 수익률 계산 (복리) - 개선된 수식
    cumulative_multiplier = 1.0
    for trade in trades:
        cumulative_multiplier *= (1 + trade['profit_rate'] / 100)
    cumulative_return = (cumulative_multiplier - 1) * 100

    # 금액 기반 수익률 계산 (각 거래에 동일 금액 투자 가정)
    total_invested = DEFAULT_BUY_AMOUNT * total_trades
    total_profit = sum(
        DEFAULT_BUY_AMOUNT * (trade['profit_rate'] / 100)
        for trade in trades
    )
    actual_return = (total_profit / total_invested * 100) if total_invested > 0 else 0.0

    return PortfolioMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        cumulative_return=cumulative_return,
        avg_return_per_trade=avg_return,
        avg_holding_days=avg_holding_days,
        total_invested_amount=total_invested,
        total_profit_amount=total_profit,
        actual_return_by_amount=actual_return
    )


# ==================== KIS API Functions ====================

async def get_api_portfolio_data() -> Tuple[List[Dict], Dict]:
    """
    KIS API를 통해 실시간 포트폴리오 데이터 조회 (비동기 래퍼)

    Returns:
        (portfolio, account_summary) 튜플
    """
    try:
        # asyncio.to_thread로 동기 API를 비동기로 실행
        loop = asyncio.get_event_loop()

        def _fetch_data():
            trader = DomesticStockTrading(mode=DEFAULT_MODE)
            portfolio = trader.get_portfolio()
            account_summary = trader.get_account_summary()
            return portfolio, account_summary

        portfolio, account_summary = await loop.run_in_executor(None, _fetch_data)

        logger.debug(f"KIS API 조회 성공: 포트폴리오 {len(portfolio)}개 종목")
        return portfolio, account_summary

    except Exception as e:
        logger.error(f"❌ KIS API 조회 실패: {e}", exc_info=True)
        logger.warning("⚠️  API 조회 실패로 인해 실시간 데이터를 가져올 수 없습니다.")
        return [], {}


# ==================== Data Consistency Validation ====================

def validate_data_consistency(
    db_holdings: List[Dict],
    api_portfolio: List[Dict]
) -> List[Dict]:
    """
    DB와 API 데이터 일관성 검증

    Args:
        db_holdings: DB에서 조회한 보유 종목
        api_portfolio: KIS API에서 조회한 포트폴리오

    Returns:
        불일치 항목 리스트
    """
    inconsistencies = []

    if not api_portfolio:
        logger.debug("API 포트폴리오 데이터가 없어 일관성 검증을 건너뜁니다.")
        return inconsistencies

    # 1. DB 종목이 API에 있는지 확인 (DB -> API)
    for db_holding in db_holdings:
        api_stock = next(
            (s for s in api_portfolio if s['stock_code'] == db_holding['ticker']),
            None
        )

        if api_stock:
            price_diff = abs(api_stock['avg_price'] - db_holding['buy_price'])

            # 100원 이상 차이나는 경우 경고
            if price_diff > 100:
                inconsistency = {
                    'ticker': db_holding['ticker'],
                    'company_name': db_holding['company_name'],
                    'db_avg_price': db_holding['buy_price'],
                    'api_avg_price': api_stock['avg_price'],
                    'difference': price_diff,
                    'issue': '평단가 불일치'
                }
                inconsistencies.append(inconsistency)
                logger.warning(
                    f"⚠️  평단가 불일치: {db_holding['company_name']} ({db_holding['ticker']}) - "
                    f"DB: {db_holding['buy_price']:,.0f}원 vs "
                    f"API: {api_stock['avg_price']:,.0f}원 "
                    f"(차이: {price_diff:,.0f}원)"
                )
        else:
            # DB에는 있는데 API에는 없는 경우
            inconsistency = {
                'ticker': db_holding['ticker'],
                'company_name': db_holding['company_name'],
                'issue': 'DB에는 있으나 API 포트폴리오에 없음'
            }
            inconsistencies.append(inconsistency)
            logger.warning(
                f"⚠️  종목 불일치: {db_holding['company_name']} ({db_holding['ticker']}) - "
                f"DB에는 있으나 실제 계좌에 없음"
            )

    # 2. API 종목이 DB에 있는지 확인 (API -> DB)
    for api_stock in api_portfolio:
        db_holding = next(
            (h for h in db_holdings if h['ticker'] == api_stock['stock_code']),
            None
        )

        if not db_holding:
            # API에는 있는데 DB에는 없는 경우
            inconsistency = {
                'ticker': api_stock['stock_code'],
                'company_name': api_stock['stock_name'],
                'issue': '실제 계좌에는 있으나 DB에는 없음'
            }
            inconsistencies.append(inconsistency)
            logger.warning(
                f"⚠️  종목 불일치: {api_stock['stock_name']} ({api_stock['stock_code']}) - "
                f"실제 계좌에는 있으나 DB에는 기록이 없음"
            )

    if not inconsistencies:
        logger.info("✅ DB와 API 데이터 일관성 검증 통과")
    else:
        logger.warning(f"⚠️  {len(inconsistencies)}개 항목에서 불일치 발견")

    return inconsistencies


# ==================== Output Functions ====================

def save_verification_result(
    all_trades: List[Dict],
    current_holdings: List[Dict],
    metrics: PortfolioMetrics,
    api_portfolio: List[Dict],
    api_account_summary: Dict,
    inconsistencies: List[Dict]
):
    """
    검증 결과를 JSON 파일로 저장

    Args:
        all_trades: 모든 거래 내역
        current_holdings: 현재 보유 종목
        metrics: 계산된 메트릭
        api_portfolio: API 포트폴리오
        api_account_summary: API 계좌 요약
        inconsistencies: 불일치 항목
    """
    if not ENABLE_JSON_OUTPUT:
        return

    try:
        result = {
            'timestamp': datetime.now().isoformat(),
            'database_path': str(PRISM_DB),
            'metrics': {
                'total_trades': metrics.total_trades,
                'winning_trades': metrics.winning_trades,
                'losing_trades': metrics.losing_trades,
                'win_rate': round(metrics.win_rate, 2),
                'cumulative_return': round(metrics.cumulative_return, 2),
                'avg_return_per_trade': round(metrics.avg_return_per_trade, 2),
                'avg_holding_days': round(metrics.avg_holding_days, 1),
                'total_invested_amount': metrics.total_invested_amount,
                'total_profit_amount': round(metrics.total_profit_amount, 2),
                'actual_return_by_amount': round(metrics.actual_return_by_amount, 2)
            },
            'current_holdings': current_holdings,
            'recent_trades': all_trades[-10:] if len(all_trades) > 10 else all_trades,
            'api_account_summary': api_account_summary,
            'data_inconsistencies': inconsistencies
        }

        with open(JSON_OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ 검증 결과 저장 완료: {JSON_OUTPUT_PATH}")

    except Exception as e:
        logger.error(f"❌ JSON 저장 실패: {e}", exc_info=True)


# ==================== Main Verification Logic ====================

async def verify_metrics():
    """메트릭 검증 메인 로직"""
    logger.info("=" * 80)
    logger.info("포트폴리오 수익률 및 승률 검증 시작")
    logger.info("=" * 80)
    logger.info(f"DB 경로: {PRISM_DB}")
    logger.info(f"검증 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 모든 청산 완료 거래 내역 조회
    logger.info("\n" + "─" * 80)
    logger.info("[1] 청산 완료 거래 내역 조회 중...")
    all_trades = await get_prism_trades()

    if not all_trades:
        logger.warning("⚠️  청산 완료된 거래 내역이 없습니다.")
    else:
        logger.info(f"✅ 총 청산 완료 거래: {len(all_trades)}건")

    # 2. 현재 보유 종목 조회
    logger.info("\n" + "─" * 80)
    logger.info("[2] 현재 보유 종목 조회 중...")
    current_holdings = await get_current_holdings()

    if not current_holdings:
        logger.info("📭 현재 보유 종목 없음 (All Cash)")
    else:
        logger.info(f"✅ 현재 보유 종목: {len(current_holdings)}개")
        for holding in current_holdings:
            logger.info(
                f"   - {holding['company_name']} ({holding['ticker']}): "
                f"{holding['buy_price']:,.0f}원 @ {holding['buy_date'][:10]}"
            )

    # 3. 수동 메트릭 계산
    logger.info("\n" + "─" * 80)
    logger.info("[3] DB 거래 내역으로 메트릭 수동 계산 중...")
    manual_metrics = await calculate_metrics_manually(all_trades)

    logger.info("\n📊 수동 계산 결과 (DB 거래 내역 기반):")
    logger.info(f"   총 청산 완료 거래: {manual_metrics.total_trades}건")
    logger.info(f"   승: {manual_metrics.winning_trades}건 | 패: {manual_metrics.losing_trades}건")
    logger.info(f"   승률: {manual_metrics.win_rate:.2f}%")
    logger.info(f"   평균 수익률/거래: {manual_metrics.avg_return_per_trade:+.2f}%")
    logger.info(f"   누적 수익률 (복리): {manual_metrics.cumulative_return:+.2f}%")
    logger.info(f"   평균 보유일: {manual_metrics.avg_holding_days:.1f}일")
    logger.info(f"\n💰 금액 기반 메트릭 (거래당 {DEFAULT_BUY_AMOUNT:,}원 투자 가정):")
    logger.info(f"   총 투자 금액: {manual_metrics.total_invested_amount:,.0f}원")
    logger.info(f"   총 수익 금액: {manual_metrics.total_profit_amount:+,.0f}원")
    logger.info(f"   실제 수익률: {manual_metrics.actual_return_by_amount:+.2f}%")

    # 4. KIS API 조회 (실시간 데이터)
    logger.info("\n" + "─" * 80)
    logger.info("[4] KIS API 실시간 포트폴리오 조회 중...")
    portfolio, account_summary = await get_api_portfolio_data()

    logger.info("\n📊 KIS API 결과 (실시간):")
    if account_summary:
        logger.info(f"   총 평가액: {account_summary.get('total_eval_amount', 0):,.0f}원")
        logger.info(f"   평가손익: {account_summary.get('total_profit_amount', 0):+,.0f}원")
        logger.info(f"   수익률: {account_summary.get('total_profit_rate', 0):+.2f}%")
        logger.info(f"   주문가능금액: {account_summary.get('available_amount', 0):,.0f}원")
    else:
        logger.warning("   ⚠️  계좌 정보를 가져올 수 없습니다")

    if portfolio:
        logger.info(f"\n   현재 보유 종목 ({len(portfolio)}개):")
        for stock in portfolio:
            logger.info(
                f"      {stock['stock_name']} ({stock['stock_code']}): "
                f"{stock['current_price']:,.0f}원 "
                f"(평단: {stock['avg_price']:,.0f}원, 손익: {stock['profit_rate']:+.2f}%)"
            )
    else:
        logger.warning("   ⚠️  포트폴리오 정보를 가져올 수 없습니다")

    # 5. 데이터 일관성 검증
    logger.info("\n" + "─" * 80)
    logger.info("[5] DB와 API 데이터 일관성 검증 중...")
    inconsistencies = validate_data_consistency(current_holdings, portfolio)

    # 6. 최근 청산 거래 상세 정보 (로그 레벨에 따라 출력)
    if logger.isEnabledFor(logging.INFO) and all_trades:
        logger.info("\n" + "=" * 80)
        logger.info(f"[6] 최근 청산 거래 상세 (최대 10건)")
        logger.info("=" * 80)

        recent_trades = all_trades[-10:]

        for i, trade in enumerate(recent_trades, 1):
            trade_num = len(all_trades) - len(recent_trades) + i
            logger.info(f"\n거래 #{trade_num}:")
            logger.info(f"   매수: {trade['buy_date'][:10]} @ {trade['buy_price']:,.0f}원")
            logger.info(f"   매도: {trade['sell_date'][:10]} @ {trade['sell_price']:,.0f}원")
            logger.info(f"   종목: {trade['company_name']} ({trade['ticker']})")
            logger.info(f"   수익률: {trade['profit_rate']:+.2f}%")
            logger.info(f"   보유일: {trade['holding_days']}일")

    # 7. JSON 결과 저장
    save_verification_result(
        all_trades,
        current_holdings,
        manual_metrics,
        portfolio,
        account_summary,
        inconsistencies
    )

    logger.info("\n" + "=" * 80)
    logger.info("✅ 검증 완료")
    logger.info("=" * 80)


async def main():
    """메인 함수"""
    try:
        await verify_metrics()
    except KeyboardInterrupt:
        logger.warning("\n⚠️  사용자에 의해 중단되었습니다.")
    except Exception as e:
        logger.error(f"❌ 예상치 못한 오류 발생: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
