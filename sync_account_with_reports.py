#!/usr/bin/env python3
"""
실계좌-DB 동기화 (기존 보고서 재사용 또는 AI 분석 자동 실행)

이 스크립트는:
1. KIS API로 실계좌 잔고 조회
2. DB와 비교하여 차이점 발견
3. 차이가 있는 종목에 대해 최근 생성된 보고서 검색
4. 보고서가 있으면 재사용하여 목표가/손절가 추출
5. 보고서가 없으면:
   - 기본 동작: 목표가/손절가를 0으로 설정 (수동 설정 필요)
   - --auto-analyze 옵션: AI 분석 자동 실행 후 보고서 생성
6. DB 동기화 (실제 매수가/수량 반영)

사용 시나리오:
- 배치에서 매수 신호 발생 → 매수 실패 → 사용자 수동 매수
- 실계좌와 DB의 불일치를 빠르게 해소
- 이미 생성된 보고서를 재사용하여 시간 절약 (AI 분석 재실행 불필요)

사용법:
    # 기본 모드: 보고서 재사용만
    python sync_account_with_reports.py

    # AI 분석 자동 실행 모드: 보고서가 없으면 AI 분석 실행
    python sync_account_with_reports.py --auto-analyze
"""

import sys
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta
import json
import asyncio
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from trading.domestic_stock_trading import DomesticStockTrading
from stock_tracking_agent import StockTrackingAgent
from cores.analysis import analyze_stock

class AccountReportSync:
    """실계좌-DB 동기화 (보고서 재사용)"""
    
    def __init__(self, db_path: str = "stock_tracking_db.sqlite", auto_analyze: bool = False):
        self.db_path = Path(PROJECT_ROOT) / db_path
        self.report_dir = Path(PROJECT_ROOT) / "pdf_reports"
        self.markdown_report_dir = Path(PROJECT_ROOT) / "reports"  # 마크다운 원본 우선 사용
        self.trader = None
        self.tracking_agent = None
        self.auto_analyze = auto_analyze  # AI 분석 자동 실행 여부
        
    def get_actual_portfolio(self):
        """실계좌 잔고 조회"""
        logger.info("=== 실계좌 잔고 조회 ===")
        self.trader = DomesticStockTrading(mode="real")
        portfolio = self.trader.get_portfolio()
        
        logger.info(f"보유 종목: {len(portfolio)}개")
        for stock in portfolio:
            logger.info(f"  {stock['stock_name']}({stock['stock_code']}): "
                       f"{stock['quantity']}주 @ {stock['avg_price']:,.0f}원")
        
        return portfolio
    
    def get_db_portfolio(self):
        """DB 잔고 조회"""
        logger.info("\n=== DB 잔고 조회 ===")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT ticker, company_name, quantity, buy_price, 
                   target_price, stop_loss, buy_date
            FROM stock_holdings
        """)
        
        rows = cursor.fetchall()
        db_stocks = {}
        
        logger.info(f"DB 보유 종목: {len(rows)}개")
        for row in rows:
            ticker, name, qty, buy_price, target, stop, buy_date = row
            logger.info(f"  {name}({ticker}): {qty}주 @ {buy_price:,.0f}원")
            db_stocks[ticker] = {
                'company_name': name,
                'quantity': qty,
                'buy_price': buy_price,
                'target_price': target,
                'stop_loss': stop,
                'buy_date': buy_date
            }
        
        conn.close()
        return db_stocks
    
    def find_recent_report(self, ticker: str, company_name: str, days: int = 7):
        """
        최근 생성된 보고서 찾기 (마크다운 원본 우선)

        PDF는 Playwright로 이미지 렌더링되어 텍스트 추출이 어려우므로
        마크다운 원본을 우선 검색합니다.

        Args:
            ticker: 종목 코드
            company_name: 종목명
            days: 검색 기간 (일)

        Returns:
            Path or None: 보고서 경로
        """
        logger.info(f"\n📄 {company_name}({ticker}) 보고서 검색 (최근 {days}일)")

        # 1. 마크다운 원본 검색 (우선)
        md_patterns = [
            f"{ticker}_{company_name}_*.md",
            f"{ticker}_*.md"
        ]

        found_md_reports = []
        for pattern in md_patterns:
            found_md_reports.extend(self.markdown_report_dir.glob(pattern))

        if found_md_reports:
            # 최근 마크다운 파일 찾기
            cutoff_time = datetime.now() - timedelta(days=days)
            recent_md = []

            for report in found_md_reports:
                mtime = datetime.fromtimestamp(report.stat().st_mtime)
                if mtime >= cutoff_time:
                    recent_md.append((report, mtime))

            if recent_md:
                most_recent, mtime = max(recent_md, key=lambda x: x[1])
                logger.info(f"  ✅ 마크다운 보고서 발견: {most_recent.name}")
                logger.info(f"     생성일: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
                return most_recent
            elif found_md_reports:
                most_recent = max(found_md_reports, key=lambda p: p.stat().st_mtime)
                mtime = datetime.fromtimestamp(most_recent.stat().st_mtime)
                logger.info(f"  📄 가장 최근 마크다운 사용: {most_recent.name} ({mtime})")
                return most_recent

        # 2. PDF 검색 (마크다운 없을 때만)
        pdf_patterns = [
            f"{ticker}_{company_name}_*.pdf",
            f"{ticker}_*.pdf"
        ]

        found_pdf_reports = []
        for pattern in pdf_patterns:
            found_pdf_reports.extend(self.report_dir.glob(pattern))

        if not found_pdf_reports:
            logger.warning(f"  ❌ 보고서를 찾을 수 없습니다 (마크다운/PDF 모두 없음)")
            return None

        # 최근 PDF 파일 찾기
        cutoff_time = datetime.now() - timedelta(days=days)
        recent_pdf = []

        for report in found_pdf_reports:
            mtime = datetime.fromtimestamp(report.stat().st_mtime)
            if mtime >= cutoff_time:
                recent_pdf.append((report, mtime))

        if not recent_pdf:
            logger.warning(f"  ⚠️  최근 {days}일 이내 보고서 없음 (전체: {len(found_pdf_reports)}개)")
            most_recent = max(found_pdf_reports, key=lambda p: p.stat().st_mtime)
            mtime = datetime.fromtimestamp(most_recent.stat().st_mtime)
            logger.info(f"  📄 가장 최근 PDF 사용: {most_recent.name} ({mtime})")
            logger.warning(f"  ⚠️  PDF는 텍스트 추출이 제한적일 수 있습니다")
            return most_recent

        most_recent, mtime = max(recent_pdf, key=lambda x: x[1])
        logger.info(f"  ✅ PDF 보고서 발견: {most_recent.name}")
        logger.info(f"     생성일: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.warning(f"  ⚠️  PDF는 텍스트 추출이 제한적일 수 있습니다")

        return most_recent
    
    async def analyze_report_for_sync(self, report_path: Path, ticker: str, company_name: str):
        """
        보고서 분석하여 목표가/손절가 추출
        
        Args:
            report_path: 보고서 경로
            ticker: 종목 코드
            company_name: 종목명
        
        Returns:
            dict: {target_price, stop_loss, scenario}
        """
        logger.info(f"\n🤖 {company_name}({ticker}) 보고서 분석 중...")
        
        try:
            # StockTrackingAgent 초기화 (한 번만)
            if self.tracking_agent is None:
                self.tracking_agent = StockTrackingAgent()
                await self.tracking_agent.initialize()
            
            # 보고서 분석
            analysis_result = await self.tracking_agent.analyze_report(str(report_path))
            
            if not analysis_result.get('success'):
                logger.error(f"  ❌ 분석 실패: {analysis_result.get('error')}")
                return None
            
            scenario = analysis_result.get('scenario', {})
            target_price = scenario.get('target_price', 0)
            stop_loss = scenario.get('stop_loss', 0)
            
            logger.info(f"  ✅ 분석 완료")
            logger.info(f"     목표가: {target_price:,.0f}원")
            logger.info(f"     손절가: {stop_loss:,.0f}원")
            
            return {
                'target_price': target_price,
                'stop_loss': stop_loss,
                'scenario': scenario,
                'report_path': str(report_path),
                'report_date': datetime.fromtimestamp(report_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            logger.error(f"  ❌ 분석 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def analyze_new_stock(self, ticker: str, company_name: str):
        """
        신규 종목에 대한 AI 분석 수행 및 보고서 생성

        Args:
            ticker: 종목 코드
            company_name: 종목명

        Returns:
            dict: 분석 결과 (target_price, stop_loss, scenario, report_path)
        """
        logger.info(f"\n🤖 {company_name}({ticker}) AI 분석 시작...")

        try:
            # 1. AI 분석 및 보고서 생성
            today = datetime.now().strftime('%Y%m%d')
            report_result = await analyze_stock(ticker, company_name, today)

            if not report_result.get('success'):
                logger.error(f"  ❌ AI 분석 실패: {report_result.get('error', '알 수 없는 오류')}")
                return None

            # 생성된 보고서 파일 경로
            pdf_path = report_result.get('pdf_path')
            if not pdf_path or not Path(pdf_path).exists():
                logger.error(f"  ❌ 보고서 파일을 찾을 수 없습니다: {pdf_path}")
                return None

            logger.info(f"  ✅ 보고서 생성 완료: {pdf_path}")

            # 2. StockTrackingAgent 초기화 (한 번만)
            if self.tracking_agent is None:
                self.tracking_agent = StockTrackingAgent()
                await self.tracking_agent.initialize()

            # 3. 보고서 분석하여 매매 시나리오 추출
            analysis_result = await self.tracking_agent.analyze_report(str(pdf_path))

            if not analysis_result.get('success'):
                logger.error(f"  ❌ 매매 시나리오 추출 실패")
                return None

            scenario = analysis_result.get('scenario', {})
            target_price = scenario.get('target_price', 0)
            stop_loss = scenario.get('stop_loss', 0)

            logger.info(f"  ✅ AI 분석 완료")
            logger.info(f"     목표가: {target_price:,.0f}원")
            logger.info(f"     손절가: {stop_loss:,.0f}원")

            return {
                'target_price': target_price,
                'stop_loss': stop_loss,
                'scenario': scenario,
                'report_path': str(pdf_path),
                'report_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"  ❌ AI 분석 중 오류 발생: {e}")
            import traceback
            traceback.print_exc()
            return None

    def compare_portfolios(self, actual_portfolio, db_stocks):
        """실계좌와 DB 비교"""
        logger.info("\n=== 잔고 비교 ===")
        
        actual_tickers = {stock['stock_code'] for stock in actual_portfolio}
        db_tickers = set(db_stocks.keys())
        
        # 실계좌에만 있는 종목 (추가 필요)
        only_in_actual = actual_tickers - db_tickers
        
        # DB에만 있는 종목 (quantity=0 제외)
        only_in_db = {t for t in db_tickers - actual_tickers 
                      if db_stocks[t]['quantity'] > 0}
        
        # 공통 종목 중 수량 차이
        quantity_diffs = []
        for ticker in actual_tickers & db_tickers:
            actual_stock = next(s for s in actual_portfolio if s['stock_code'] == ticker)
            db_stock = db_stocks[ticker]
            
            if actual_stock['quantity'] != db_stock['quantity']:
                quantity_diffs.append({
                    'ticker': ticker,
                    'name': actual_stock['stock_name'],
                    'actual_qty': actual_stock['quantity'],
                    'db_qty': db_stock['quantity'],
                    'actual_price': actual_stock['avg_price'],
                    'db_price': db_stock['buy_price']
                })
        
        logger.info(f"실계좌에만 있음: {len(only_in_actual)}개 - {only_in_actual}")
        logger.info(f"DB에만 있음: {len(only_in_db)}개 - {only_in_db}")
        logger.info(f"수량 차이: {len(quantity_diffs)}개")
        
        return {
            'only_in_actual': only_in_actual,
            'only_in_db': only_in_db,
            'quantity_diffs': quantity_diffs,
            'actual_portfolio': actual_portfolio,
            'db_stocks': db_stocks
        }
    
    async def sync_with_reports(self, sync_data):
        """보고서 기반 동기화 실행"""
        logger.info("\n" + "="*70)
        logger.info("🔄 보고서 기반 동기화 시작")
        logger.info("="*70)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 1. DB에만 있는 종목 삭제
            if sync_data['only_in_db']:
                logger.info(f"\n🗑️  DB에서 삭제할 종목 ({len(sync_data['only_in_db'])}개)")
                for ticker in sync_data['only_in_db']:
                    name = sync_data['db_stocks'][ticker]['company_name']
                    logger.info(f"  - {name}({ticker})")
                    cursor.execute("DELETE FROM stock_holdings WHERE ticker = ?", (ticker,))
            
            # 2. 실계좌에만 있는 종목 추가 (보고서 재사용)
            if sync_data['only_in_actual']:
                logger.info(f"\n➕ 실계좌에만 있는 종목 ({len(sync_data['only_in_actual'])}개)")
                
                for ticker in sync_data['only_in_actual']:
                    actual_stock = next(s for s in sync_data['actual_portfolio'] 
                                       if s['stock_code'] == ticker)
                    company_name = actual_stock['stock_name']
                    
                    logger.info(f"\n📌 {company_name}({ticker}) 처리 중...")
                    
                    # 최근 보고서 찾기
                    report_path = self.find_recent_report(ticker, company_name, days=7)
                    
                    if report_path:
                        # 보고서 분석
                        analysis = await self.analyze_report_for_sync(
                            report_path, ticker, company_name
                        )

                        if analysis:
                            # 시나리오에 수동 매수 정보 추가
                            scenario = analysis['scenario'].copy()
                            scenario['manual_purchase'] = True
                            scenario['sync_note'] = f"실계좌 동기화 (보고서: {analysis['report_date']})"

                            target_price = analysis['target_price']
                            stop_loss = analysis['stop_loss']
                        else:
                            logger.warning(f"  ⚠️  보고서 분석 실패 - 기본값 사용")
                            scenario = {'note': 'HTS 수동 매수 (보고서 분석 실패)'}
                            target_price = 0
                            stop_loss = 0
                    else:
                        # 보고서가 없는 경우
                        if self.auto_analyze:
                            # AI 분석 자동 실행
                            logger.info(f"  🤖 보고서 없음 - AI 분석 자동 실행")
                            analysis = await self.analyze_new_stock(ticker, company_name)

                            if analysis:
                                scenario = analysis['scenario'].copy()
                                scenario['manual_purchase'] = True
                                scenario['sync_note'] = f"실계좌 동기화 (AI 분석: {analysis['report_date']})"

                                target_price = analysis['target_price']
                                stop_loss = analysis['stop_loss']
                            else:
                                logger.warning(f"  ⚠️  AI 분석 실패 - 기본값 사용")
                                scenario = {'note': 'HTS 수동 매수 (AI 분석 실패)'}
                                target_price = 0
                                stop_loss = 0
                        else:
                            # 기본값 사용
                            logger.warning(f"  ⚠️  보고서 없음 - 기본값 사용")
                            logger.info(f"     (--auto-analyze 옵션으로 AI 분석 자동 실행 가능)")
                            scenario = {'note': 'HTS 수동 매수 (보고서 없음)'}
                            target_price = 0
                            stop_loss = 0
                    
                    # DB 삽입
                    cursor.execute("""
                        INSERT INTO stock_holdings (
                            ticker, company_name, quantity, buy_price, current_price,
                            buy_date, last_updated, scenario, target_price, stop_loss
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        ticker,
                        company_name,
                        actual_stock['quantity'],
                        actual_stock['avg_price'],
                        actual_stock['current_price'],
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        json.dumps(scenario, ensure_ascii=False),
                        target_price,
                        stop_loss
                    ))
                    
                    logger.info(f"  ✅ DB 추가 완료")
            
            # 3. 수량 차이 업데이트
            if sync_data['quantity_diffs']:
                logger.info(f"\n🔄 수량 차이 업데이트 ({len(sync_data['quantity_diffs'])}개)")
                
                for diff in sync_data['quantity_diffs']:
                    logger.info(f"  {diff['name']}({diff['ticker']}): "
                               f"{diff['db_qty']}주 → {diff['actual_qty']}주")
                    
                    # 매수가도 차이나면 업데이트
                    actual_stock = next(s for s in sync_data['actual_portfolio'] 
                                       if s['stock_code'] == diff['ticker'])
                    
                    if abs(diff['actual_price'] - diff['db_price']) > 1:
                        logger.info(f"    매수가도 업데이트: "
                                   f"{diff['db_price']:,.0f}원 → {diff['actual_price']:,.0f}원")
                        cursor.execute("""
                            UPDATE stock_holdings
                            SET quantity = ?, 
                                buy_price = ?,
                                current_price = ?,
                                last_updated = ?
                            WHERE ticker = ?
                        """, (
                            actual_stock['quantity'],
                            actual_stock['avg_price'],
                            actual_stock['current_price'],
                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            diff['ticker']
                        ))
                    else:
                        cursor.execute("""
                            UPDATE stock_holdings
                            SET quantity = ?,
                                current_price = ?,
                                last_updated = ?
                            WHERE ticker = ?
                        """, (
                            actual_stock['quantity'],
                            actual_stock['current_price'],
                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            diff['ticker']
                        ))
            
            conn.commit()
            logger.info("\n✅ 동기화 완료!")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"\n❌ 동기화 실패: {e}")
            import traceback
            traceback.print_exc()
        finally:
            conn.close()
    
    def print_summary(self):
        """최종 상태 출력"""
        logger.info("\n" + "="*70)
        logger.info("📊 최종 포트폴리오 상태")
        logger.info("="*70)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT ticker, company_name, quantity, buy_price, current_price,
                   target_price, stop_loss, buy_date
            FROM stock_holdings
            WHERE quantity > 0
            ORDER BY buy_date DESC
        """)
        
        rows = cursor.fetchall()
        
        if rows:
            for i, row in enumerate(rows, 1):
                ticker, name, qty, buy_price, cur_price, target, stop, buy_date = row
                profit_pct = (cur_price/buy_price - 1) * 100 if buy_price > 0 else 0
                target_pct = (target/buy_price - 1) * 100 if buy_price > 0 and target > 0 else 0
                stop_pct = (stop/buy_price - 1) * 100 if buy_price > 0 and stop > 0 else 0
                
                logger.info(f"\n{i}. {name}({ticker})")
                logger.info(f"   수량: {qty}주")
                logger.info(f"   매수가: {buy_price:,.0f}원")
                logger.info(f"   현재가: {cur_price:,.0f}원 (수익률: {profit_pct:+.2f}%)")
                if target > 0:
                    logger.info(f"   목표가: {target:,.0f}원 (+{target_pct:.1f}%)")
                if stop > 0:
                    logger.info(f"   손절가: {stop:,.0f}원 ({stop_pct:.1f}%)")
                logger.info(f"   매수일: {buy_date}")
        else:
            logger.info("보유 종목 없음")
        
        conn.close()

async def main():
    """메인 실행 함수"""
    import argparse

    # CLI 인자 파싱
    parser = argparse.ArgumentParser(
        description="실계좌-DB 동기화 (보고서 재사용 또는 AI 분석 자동 실행)"
    )
    parser.add_argument(
        "--auto-analyze",
        action="store_true",
        help="보고서가 없는 종목에 대해 AI 분석 자동 실행"
    )
    args = parser.parse_args()

    # AccountReportSync 초기화
    syncer = AccountReportSync(auto_analyze=args.auto_analyze)

    if args.auto_analyze:
        logger.info("🤖 AI 분석 자동 실행 모드 활성화")

    try:
        # 1. 실계좌 조회
        actual_portfolio = syncer.get_actual_portfolio()
        
        # 2. DB 조회
        db_stocks = syncer.get_db_portfolio()
        
        # 3. 비교
        sync_data = syncer.compare_portfolios(actual_portfolio, db_stocks)
        
        # 4. 동기화 필요 여부 확인
        needs_sync = (sync_data['only_in_actual'] or 
                     sync_data['only_in_db'] or 
                     sync_data['quantity_diffs'])
        
        if needs_sync:
            # 5. 동기화 실행
            await syncer.sync_with_reports(sync_data)
            
            # 6. 결과 출력
            syncer.print_summary()
        else:
            logger.info("\n✅ 실계좌와 DB가 완전히 일치합니다. 동기화 불필요.")
            syncer.print_summary()
        
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  사용자 중단")
    except Exception as e:
        logger.error(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
