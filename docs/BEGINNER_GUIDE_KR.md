# 🎓 PRISM-INSIGHT 초보자 학습 가이드

> 코딩 초보자를 위한 체계적인 학습 로드맵

---

## 📌 목차

1. [이 프로젝트는 무엇인가요?](#1-이-프로젝트는-무엇인가요)
2. [필요한 사전 지식](#2-필요한-사전-지식)
3. [개발 환경 설정](#3-개발-환경-설정)
4. [4주 학습 로드맵](#4-4주-학습-로드맵)
5. [핵심 개념 정리](#5-핵심-개념-정리)
6. [실습 예제](#6-실습-예제)
7. [자주 묻는 질문](#7-자주-묻는-질문)

---

## 1. 이 프로젝트는 무엇인가요?

**PRISM-INSIGHT**는 AI를 활용한 주식 분석 자동화 시스템입니다.

### 🎯 주요 기능

- **급등주 자동 탐지**: 매일 거래량/가격 급증 종목 발견
- **AI 분석 보고서**: 12개 전문 AI 에이전트가 협업하여 종합 분석 리포트 생성
- **자동매매 시뮬레이션**: AI가 매수/매도 결정
- **텔레그램 봇**: 실시간 포트폴리오 상담 및 알림

### 📊 시즌1 성과 (시뮬레이션)
- 누적 수익률: **408.60%**
- 승률: 45.1% (51건 거래)

---

## 2. 필요한 사전 지식

### ✅ 필수 사항
- **Python 기초**: 변수, 함수, 클래스, 조건문, 반복문
- **터미널 사용법**: 기본적인 명령어 (cd, ls, python)

### 📚 학습하면 좋은 것들 (순서대로)
1. **Python 중급**
   - 비동기 프로그래밍 (async/await)
   - 예외 처리 (try/except)
   - 파일 입출력

2. **데이터 처리**
   - pandas (데이터프레임 다루기)
   - JSON 형식 이해

3. **API 개념**
   - REST API란?
   - API 키 사용법

4. **AI/LLM 기초**
   - GPT, Claude 같은 LLM이 뭔지
   - 프롬프트 엔지니어링 개념

### 📖 추천 학습 자료
- [점프 투 파이썬](https://wikidocs.net/book/1)
- [파이썬 공식 튜토리얼](https://docs.python.org/ko/3/tutorial/)
- [LangChain 개념](https://python.langchain.com/docs/get_started/introduction)

---

## 3. 개발 환경 설정

### Step 1: Python 설치 확인
```bash
python --version  # Python 3.10 이상이어야 함
```

### Step 2: 의존성 설치
```bash
cd /home/user/prism-insight
pip install -r requirements.txt
```

### Step 3: 환경 변수 설정
```bash
# .env.example을 복사하여 .env 파일 생성
cp .env.example .env

# .env 파일을 열어서 필요한 API 키 입력
# - OPENAI_API_KEY: OpenAI API 키
# - ANTHROPIC_API_KEY: Anthropic Claude API 키
# - TELEGRAM_BOT_TOKEN: 텔레그램 봇 토큰
```

### Step 4: 테스트 실행
```bash
# 간단한 테스트로 환경 확인
python -c "import pandas; print('설치 성공!')"
```

---

## 4. 4주 학습 로드맵

### 📅 1주차: 프로젝트 구조 이해하기

#### 목표
- 전체 프로젝트 구조 파악
- 핵심 파일들의 역할 이해
- 간단한 코드 읽기

#### 할 일
1. **README.md 읽기** (30분)
   - 프로젝트 목적과 아키텍처 이해
   - 실행 방법 따라해보기

2. **프로젝트 구조 탐색** (1시간)
   ```
   prism-insight/
   ├── cores/           ← AI 분석 엔진 (가장 중요!)
   ├── trading/         ← 자동매매 시스템
   ├── examples/        ← 웹 UI (Streamlit)
   ├── docs/            ← 문서들
   └── requirements.txt ← 필요한 라이브러리 목록
   ```

3. **간단한 파일 읽기** (2시간)
   - `cores/utils.py` - 유틸리티 함수들 (쉬움)
   - `cores/stock_chart.py` - 차트 생성 로직
   - `.env.example` - 환경 변수 예제

4. **실습: 주석 달아보기**
   ```python
   # cores/utils.py의 함수들을 읽고
   # 각 함수가 무엇을 하는지 주석으로 정리해보세요
   ```

#### 체크포인트
- [ ] 프로젝트가 무엇을 하는지 설명할 수 있다
- [ ] cores/, trading/ 폴더가 무엇을 담당하는지 안다
- [ ] requirements.txt에 어떤 라이브러리가 있는지 확인했다

---

### 📅 2주차: AI 에이전트 시스템 이해하기

#### 목표
- AI 에이전트가 어떻게 작동하는지 이해
- MCP(Model Context Protocol) 개념 파악
- 실제 분석 프로세스 따라가기

#### 핵심 파일 학습 순서

1. **`cores/main.py`** (★★★ 가장 중요)
   - 전체 분석 프로세스의 시작점
   - `analyze_stock()` 함수 집중 분석

   ```python
   # 주요 함수 흐름:
   # 1. MCP 앱 초기화
   # 2. 6개 분석 에이전트 생성
   # 3. 각 에이전트 실행 (순차적)
   # 4. 결과를 종합하여 투자 전략 도출
   # 5. 품질 검사 및 리포트 생성
   ```

2. **`cores/agents/__init__.py`**
   - 에이전트 생성 로직
   - 각 에이전트의 역할 정의

   ```python
   # 6개 분석 에이전트:
   # 1. 기술적 분석가 (차트, RSI, MACD)
   # 2. 거래 흐름 분석가 (기관/외국인 매매)
   # 3. 재무 분석가 (PER, PBR, ROE)
   # 4. 산업 분석가 (사업 포트폴리오)
   # 5. 정보 분석가 (뉴스, 공시)
   # 6. 시장 분석가 (코스피/코스닥 지수)
   ```

3. **`cores/agents/stock_price_agents.py`** (가장 이해하기 쉬움)
   - 기술적 분석 에이전트
   - 주가, 거래량, 차트 패턴 분석

   ```python
   # 학습 포인트:
   # - create_technical_analyst() 함수 읽기
   # - TECHNICAL_ANALYST_INSTRUCTIONS 프롬프트 분석
   # - 에이전트가 어떤 데이터를 요청하는지 확인
   ```

4. **`cores/analysis.py`**
   - 모든 에이전트 실행 오케스트레이션
   - 에이전트 간 데이터 전달 방식

#### 실습 과제

**과제 1: 에이전트 실행해보기**
```bash
# 샘플 주식(유니온, 000910) 분석 실행
cd cores
python main.py

# 약 60분 소요됨 (타임아웃 보호됨)
# 결과는 outputs/ 폴더에 마크다운 파일로 저장됨
```

**과제 2: 프롬프트 수정 실험**
```python
# cores/agents/stock_price_agents.py 열기
# TECHNICAL_ANALYST_INSTRUCTIONS 찾기
# 프롬프트의 일부를 수정하고 결과가 어떻게 달라지는지 관찰

# 예시: "상세하게" → "간단하게"로 변경
```

**과제 3: 로그 분석**
```python
# main.py 실행 중 출력되는 로그 읽기
# 각 에이전트가:
# - 어떤 데이터를 요청하는지
# - 얼마나 시간이 걸리는지
# - 어떤 결과를 반환하는지
# 메모하기
```

#### 체크포인트
- [ ] 6개 분석 에이전트의 역할을 설명할 수 있다
- [ ] analyze_stock() 함수의 흐름을 이해했다
- [ ] MCP 에이전트가 무엇인지 개념적으로 안다
- [ ] 실제 분석을 1번 이상 실행해봤다

---

### 📅 3주차: 데이터 파이프라인 이해하기

#### 목표
- 급등주 탐지 로직 이해
- 전체 파이프라인 흐름 파악
- 비동기 프로그래밍 개념 익히기

#### 핵심 파일 학습 순서

1. **`trigger_batch.py`** (724줄)
   - 급등주 탐지 시스템
   - 한국 주식 시장 데이터 수집

   ```python
   # 주요 함수:
   # - detect_hot_stocks() : 급등주 스크리닝
   # - 필터링 조건:
   #   * 거래량 급증률 (volume_surge_rate)
   #   * 가격 상승률 (price_increase_percentage)
   #   * 시가총액 (market_cap_threshold)
   #   * 유동성 (liquidity_threshold)
   ```

2. **`stock_analysis_orchestrator.py`**
   - 전체 파이프라인 오케스트레이터
   - 탐지 → 분석 → 리포트 → 텔레그램 전송

   ```python
   # 파이프라인 순서:
   # 1. detect_hot_stocks() - 급등주 탐지
   # 2. analyze_stock() - AI 분석 (각 종목당 60분)
   # 3. generate_report() - 리포트 생성
   # 4. convert_to_pdf() - PDF 변환
   # 5. send_to_telegram() - 텔레그램 전송
   ```

3. **`telegram_summary_agent.py`**
   - 상세 리포트 → 400자 요약 변환
   - 텔레그램 메시지 생성

#### 실습 과제

**과제 1: 급등주 탐지 실행**
```bash
# 오늘의 급등주 탐지
python trigger_batch.py

# 결과 확인:
# - 어떤 종목들이 탐지되었는지
# - 각 종목의 거래량 급증률, 가격 상승률 확인
```

**과제 2: 탐지 조건 수정 실험**
```python
# trigger_batch.py 열기
# detect_hot_stocks() 함수 찾기

# 파라미터 수정 예시:
volume_surge_rate = 5.0  # 거래량 5배 이상 (기본값)
→ volume_surge_rate = 3.0  # 3배로 완화

# 결과가 어떻게 달라지는지 관찰
```

**과제 3: 비동기 함수 이해**
```python
# stock_analysis_orchestrator.py 열기
# async def, await 키워드 찾아보기

# 질문:
# 1. 왜 비동기를 사용할까?
# 2. await는 언제 쓰일까?
# 3. 동기 함수와 비동기 함수의 차이는?
```

#### 체크포인트
- [ ] 급등주 탐지 조건을 설명할 수 있다
- [ ] 전체 파이프라인 흐름을 그림으로 그릴 수 있다
- [ ] async/await가 무엇인지 개념적으로 이해했다
- [ ] 급등주 탐지를 1번 이상 실행해봤다

---

### 📅 4주차: 트레이딩 시스템 이해하기

#### 목표
- AI 기반 매매 결정 로직 이해
- 포트폴리오 관리 방식 파악
- 실제 API 연동 방법 학습

#### 핵심 파일 학습 순서

1. **`stock_tracking_agent.py`** (1,674줄 - 복잡함 주의!)
   - AI 매매 시뮬레이션 엔진
   - GPT-5 기반 매수/매도 결정

   ```python
   # 주요 에이전트:
   # 1. Buy Specialist Agent
   #    - 매수 타이밍 결정
   #    - 포트폴리오 최적화 (최대 10종목)
   #    - 섹터 분산 투자

   # 2. Sell Specialist Agent
   #    - 매도 타이밍 결정
   #    - 손절/익절 시나리오
   #    - 리스크 관리
   ```

2. **`trading/domestic_stock_trading.py`**
   - 실제 매매 주문 실행
   - 한국투자증권 API 연동

   ```python
   # 주요 함수:
   # - buy_stock() : 매수 주문
   # - sell_stock() : 매도 주문
   # - get_balance() : 계좌 잔고 조회
   # - get_current_price() : 현재가 조회
   ```

3. **`trading/kis_auth.py`**
   - API 인증 처리
   - 액세스 토큰 관리

#### 실습 과제

**과제 1: 매매 결정 로직 읽기**
```python
# stock_tracking_agent.py 열기
# BUY_SPECIALIST_INSTRUCTIONS 찾기

# 질문에 답하기:
# 1. AI는 어떤 기준으로 매수를 결정하나?
# 2. 포트폴리오에 최대 몇 종목까지 보유 가능한가?
# 3. 리스크 관리는 어떻게 하나?
```

**과제 2: 시뮬레이션 실행**
```bash
# 주의: 실제 돈을 사용하지 않는 시뮬레이션 모드
python stock_tracking_agent.py

# 로그 관찰:
# - AI가 어떤 종목을 매수하려고 하는지
# - 매수/매도 이유는 무엇인지
# - 포트폴리오가 어떻게 변화하는지
```

**과제 3: 프롬프트 분석**
```python
# SELL_SPECIALIST_INSTRUCTIONS 읽기
# AI에게 주어진 매도 지침 분석

# 분석 포인트:
# - 손절 기준은?
# - 익절 기준은?
# - 포트폴리오 리밸런싱은 언제?
```

#### 체크포인트
- [ ] AI 매매 결정 프로세스를 설명할 수 있다
- [ ] Buy/Sell Specialist의 역할 차이를 안다
- [ ] 포트폴리오 관리 전략을 이해했다
- [ ] 실제 API 연동 방법을 개념적으로 안다

---

## 5. 핵심 개념 정리

### 🤖 1. MCP (Model Context Protocol)

**간단 설명**: AI 에이전트가 외부 데이터에 접근하기 위한 표준 프로토콜

**비유**: 에이전트가 사용하는 "도구 상자"
- 망치 (kospi_kosdaq 서버) → 주식 데이터 가져오기
- 렌치 (firecrawl 서버) → 웹 크롤링
- 드라이버 (sqlite 서버) → 데이터베이스 조작

**코드 예시**:
```python
# mcp_agent.config.yaml에 정의된 서버들
servers:
  kospi_kosdaq:  # 한국 주식 데이터
    command: python
    args: ["-m", "mcp_kospi_kosdaq"]

  sqlite:  # 매매 기록 저장
    command: mcp-server-sqlite
    args: ["--db-path", "prism_db.sqlite"]
```

**학습 자료**:
- [MCP 공식 문서](https://modelcontextprotocol.io/)
- 프로젝트의 `mcp_agent.config.yaml.example` 파일

---

### 🧠 2. Multi-Agent System (다중 에이전트 시스템)

**간단 설명**: 여러 전문 AI가 협업하여 복잡한 문제 해결

**비유**: 주식 분석팀
- 기술적 분석가 (차트 전문)
- 재무 분석가 (숫자 전문)
- 뉴스 분석가 (정보 전문)
- 전략가 (종합 판단)

**장점**:
1. **전문성**: 각 에이전트가 특정 분야에 집중
2. **확장성**: 새로운 에이전트 추가 쉬움
3. **품질**: 여러 관점에서 분석하여 정확도 향상

**코드 흐름**:
```python
# cores/analysis.py

# 1. 기술적 분석 에이전트 실행
technical_result = await technical_agent.run()

# 2. 재무 분석 에이전트 실행 (기술적 분석 결과 참고)
financial_result = await financial_agent.run(
    context=technical_result
)

# 3. 전략 에이전트가 모든 결과 종합
strategy_result = await strategy_agent.run(
    technical=technical_result,
    financial=financial_result,
    news=news_result,
    market=market_result
)
```

---

### 📊 3. 비동기 프로그래밍 (Async/Await)

**간단 설명**: 여러 작업을 동시에 진행하여 시간 절약

**동기 vs 비동기 비유**:

**동기 (Synchronous)**:
```
햄버거 주문 → [대기 5분] → 받음 → 콜라 주문 → [대기 2분] → 받음
총 소요 시간: 7분
```

**비동기 (Asynchronous)**:
```
햄버거 주문 → 콜라 주문 → [동시 대기 5분] → 둘 다 받음
총 소요 시간: 5분
```

**코드 예시**:
```python
# 동기 방식 (느림)
def analyze_stocks(stocks):
    for stock in stocks:
        result = analyze(stock)  # 각 60분 소요
        # 10개 종목 = 600분 (10시간)

# 비동기 방식 (빠름)
async def analyze_stocks(stocks):
    tasks = [analyze(stock) for stock in stocks]
    results = await asyncio.gather(*tasks)
    # 10개 종목 동시 분석 = 60분
```

**학습 자료**:
- [Real Python - Async IO](https://realpython.com/async-io-python/)
- [파이썬 공식 문서 - asyncio](https://docs.python.org/ko/3/library/asyncio.html)

---

### 💡 4. 프롬프트 엔지니어링

**간단 설명**: AI에게 정확한 지시를 내리는 기술

**좋은 프롬프트의 조건**:
1. **구체적**: "분석해줘" ❌ → "PER, PBR, ROE를 계산하고 업계 평균과 비교해줘" ✅
2. **구조적**: 단계별 지시
3. **예시 포함**: 원하는 출력 형식 제시

**실제 예시** (cores/agents/stock_price_agents.py):
```python
TECHNICAL_ANALYST_INSTRUCTIONS = """
## 역할
당신은 20년 경력의 기술적 분석 전문가입니다.

## 분석 항목
1. 주가 및 거래량 분석
   - 최근 1개월, 3개월, 6개월 추세
   - 거래량 변화 패턴

2. 기술적 지표
   - RSI (30 이하 과매도, 70 이상 과매수)
   - MACD 골든크로스/데드크로스
   - 볼린저 밴드 이탈 여부

## 출력 형식
### 1. 주가 동향
- 현재가: XXX원
- 전일 대비: +X.X%
...

### 2. 기술적 지표 분석
...

## 주의사항
- 반드시 실제 데이터를 사용하세요
- 주관적 판단은 근거와 함께 제시하세요
"""
```

**학습 팁**:
- 프로젝트의 `cores/agents/` 폴더의 INSTRUCTIONS 변수들을 읽어보세요
- 프롬프트를 수정하고 결과 변화를 관찰하세요

---

### 📈 5. 주식 데이터 기초

**OHLCV 데이터**:
- **O**pen: 시가 (장 시작 가격)
- **H**igh: 고가 (최고 가격)
- **L**ow: 저가 (최저 가격)
- **C**lose: 종가 (장 마감 가격)
- **V**olume: 거래량

**주요 지표**:
1. **RSI (Relative Strength Index)**: 과매수/과매도 판단
   - 0~100 범위
   - 30 이하: 과매도 (매수 신호)
   - 70 이상: 과매수 (매도 신호)

2. **MACD**: 추세 전환 포착
   - 골든크로스: 상승 신호
   - 데드크로스: 하락 신호

3. **PER (주가수익비율)**: 주가가 비싼지 싼지 판단
   - PER = 주가 / 주당순이익(EPS)
   - 낮을수록 저평가

**코드에서 데이터 가져오기**:
```python
# pykrx 라이브러리 사용
from pykrx import stock

# 삼성전자 (005930) 최근 30일 OHLCV
df = stock.get_market_ohlcv(
    fromdate="20250101",
    todate="20250126",
    ticker="005930"
)
print(df)
```

---

## 6. 실습 예제

### 🎯 예제 1: 나만의 분석 에이전트 만들기

**난이도**: ⭐⭐☆☆☆

**목표**: 간단한 "감성 분석 에이전트" 추가하기

**Step 1**: 새 파일 생성
```bash
touch cores/agents/sentiment_agents.py
```

**Step 2**: 에이전트 정의
```python
# cores/agents/sentiment_agents.py

from mcp_agent import MCPApp

SENTIMENT_ANALYST_INSTRUCTIONS = """
## 역할
당신은 시장 감성 분석 전문가입니다.

## 분석 방법
1. 최근 뉴스 제목과 내용에서 긍정/부정 키워드 추출
2. SNS 언급량 변화 분석
3. 투자자 심리 점수 산출 (0~100점)

## 출력
### 시장 감성 점수
- 점수: XX점
- 평가: [매우 부정 / 부정 / 중립 / 긍정 / 매우 긍정]

### 근거
- 긍정 요인: ...
- 부정 요인: ...
"""

def create_sentiment_analyst(mcp_app: MCPApp):
    """감성 분석 에이전트 생성"""
    return mcp_app.create_agent(
        name="sentiment_analyst",
        instructions=SENTIMENT_ANALYST_INSTRUCTIONS,
        model="gpt-4.1",
    )
```

**Step 3**: 메인 분석에 통합
```python
# cores/analysis.py에 추가

from cores.agents.sentiment_agents import create_sentiment_analyst

async def analyze_stock(stock_code: str):
    # ... 기존 코드 ...

    # 감성 분석 에이전트 추가
    sentiment_agent = create_sentiment_analyst(mcp_app)
    sentiment_result = await sentiment_agent.run(
        f"{stock_code} 종목의 최근 시장 감성을 분석해주세요."
    )

    print(f"감성 분석 결과: {sentiment_result}")
```

**실행 및 확인**:
```bash
cd cores
python main.py
```

---

### 🎯 예제 2: 급등주 탐지 조건 커스터마이징

**난이도**: ⭐⭐⭐☆☆

**목표**: 나만의 급등주 탐지 전략 만들기

**시나리오**: "소형주 중 거래량 폭발 종목" 찾기

**Step 1**: `trigger_batch.py` 복사
```bash
cp trigger_batch.py my_trigger_batch.py
```

**Step 2**: 탐지 조건 수정
```python
# my_trigger_batch.py

async def detect_my_hot_stocks():
    """소형주 거래량 폭발 종목 탐지"""

    # 조건 설정
    volume_surge_rate = 10.0  # 거래량 10배 이상 (기본 5배)
    price_increase_min = 3.0  # 가격 3% 이상 상승
    price_increase_max = 15.0  # 15% 이하 상승 (급등락 제외)
    market_cap_min = 100  # 최소 100억 (초소형주 제외)
    market_cap_max = 5000  # 최대 5천억 (대형주 제외)

    # ... 탐지 로직 ...

    # 필터링
    hot_stocks = [
        stock for stock in all_stocks
        if (
            stock['volume_surge'] >= volume_surge_rate
            and price_increase_min <= stock['price_change'] <= price_increase_max
            and market_cap_min <= stock['market_cap'] <= market_cap_max
        )
    ]

    return hot_stocks
```

**Step 3**: 실행 및 결과 비교
```bash
# 원본
python trigger_batch.py > original_results.txt

# 커스텀
python my_trigger_batch.py > my_results.txt

# 차이 비교
diff original_results.txt my_results.txt
```

---

### 🎯 예제 3: 간단한 백테스팅 스크립트

**난이도**: ⭐⭐⭐⭐☆

**목표**: 과거 데이터로 전략 성과 테스트

**Step 1**: 새 스크립트 생성
```python
# backtesting_simple.py

import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta

def backtest_strategy(stock_code, start_date, end_date):
    """
    간단한 RSI 전략 백테스팅
    - RSI < 30: 매수
    - RSI > 70: 매도
    """

    # 1. 데이터 수집
    df = stock.get_market_ohlcv(start_date, end_date, stock_code)

    # 2. RSI 계산 (14일 기준)
    delta = df['종가'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()

    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 3. 매매 신호 생성
    df['Signal'] = 0
    df.loc[df['RSI'] < 30, 'Signal'] = 1  # 매수
    df.loc[df['RSI'] > 70, 'Signal'] = -1  # 매도

    # 4. 수익률 계산
    initial_capital = 10_000_000  # 초기 자본 1천만원
    position = 0  # 보유 여부
    capital = initial_capital

    for i, row in df.iterrows():
        if row['Signal'] == 1 and position == 0:  # 매수
            position = capital / row['종가']
            capital = 0
            print(f"{i}: 매수 {row['종가']}원")

        elif row['Signal'] == -1 and position > 0:  # 매도
            capital = position * row['종가']
            position = 0
            print(f"{i}: 매도 {row['종가']}원, 잔고: {capital:,.0f}원")

    # 마지막 잔고 계산
    if position > 0:
        capital = position * df.iloc[-1]['종가']

    # 5. 결과 출력
    profit = capital - initial_capital
    profit_rate = (profit / initial_capital) * 100

    print(f"\n=== 백테스팅 결과 ===")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"초기 자본: {initial_capital:,}원")
    print(f"최종 자본: {capital:,.0f}원")
    print(f"수익: {profit:,.0f}원 ({profit_rate:.2f}%)")

    return df

# 실행
if __name__ == "__main__":
    # 삼성전자 최근 1년 백테스팅
    today = datetime.now()
    one_year_ago = today - timedelta(days=365)

    result = backtest_strategy(
        stock_code="005930",  # 삼성전자
        start_date=one_year_ago.strftime("%Y%m%d"),
        end_date=today.strftime("%Y%m%d")
    )
```

**실행**:
```bash
python backtesting_simple.py
```

**개선 아이디어**:
- 다양한 지표 조합 (RSI + MACD)
- 손절/익절 로직 추가
- 여러 종목 동시 백테스팅
- 시각화 (matplotlib)

---

## 7. 자주 묻는 질문

### Q1: Python 비동기 프로그래밍이 어려워요. 꼭 이해해야 하나요?

**A**: 초기에는 개념만 알아도 충분합니다.

**최소한 알아야 할 것**:
- `async def`: 비동기 함수 정의
- `await`: 비동기 함수 실행 대기
- `asyncio.gather()`: 여러 작업 동시 실행

**나중에 학습**:
- Event loop, Future, Task 등 고급 개념

**추천**: 일단 코드를 실행하며 흐름을 이해하고, 필요할 때 깊게 학습하세요.

---

### Q2: AI 에이전트가 너무 복잡해 보여요. 어디서부터 시작할까요?

**A**: 가장 간단한 에이전트부터 시작하세요.

**추천 순서**:
1. `cores/agents/stock_price_agents.py` (기술적 분석)
   - 데이터 가져오기
   - 프롬프트 실행
   - 결과 반환

2. 직접 간단한 에이전트 만들어보기 (예제 1 참고)

3. 복잡한 에이전트 (news, strategy) 분석

**핵심**: 에이전트는 결국 "프롬프트 + 데이터 접근 권한"일 뿐입니다.

---

### Q3: 주식 지식이 없는데 괜찮을까요?

**A**: 코딩 학습 목적이라면 괜찮습니다.

**대안**:
1. **주식 용어 사전 만들기**
   ```python
   # glossary.py
   terms = {
       "PER": "주가수익비율 - 주가 / 주당순이익",
       "RSI": "상대강도지수 - 과매수/과매도 판단",
       # ...
   }
   ```

2. **도메인 지식과 코딩 병행 학습**
   - 코드를 읽으며 모르는 용어 검색
   - 점진적으로 지식 축적

3. **도메인 무관한 부분 집중**
   - 비동기 프로그래밍
   - API 연동
   - 데이터 처리

---

### Q4: 실제로 돈을 벌 수 있나요?

**A**: 이 프로젝트는 **교육 및 연구 목적**입니다.

**주의사항**:
- 시뮬레이션 성과 ≠ 실전 성과
- 실전에서는 슬리피지, 수수료, 세금 등 추가 비용 발생
- AI 판단이 항상 옳은 것은 아님

**권장**:
1. 충분한 백테스팅
2. 소액으로 실전 테스트
3. 리스크 관리 철저히

**법적 책임**: 투자 결과에 대한 책임은 본인에게 있습니다.

---

### Q5: 에러가 계속 나는데 어떻게 해결하나요?

**A**: 체계적 디버깅 방법을 익히세요.

**Step 1: 에러 메시지 읽기**
```
Traceback (most recent call last):
  File "main.py", line 42, in analyze_stock
    result = await agent.run()
TypeError: 'NoneType' object is not callable
```
→ `agent`가 `None`입니다. 생성 과정 확인 필요.

**Step 2: 로그 추가**
```python
print(f"DEBUG: agent = {agent}")
print(f"DEBUG: type(agent) = {type(agent)}")
```

**Step 3: 구글링**
- 에러 메시지 전체 복사
- "Python [에러 메시지]" 검색
- Stack Overflow 답변 참고

**Step 4: 커뮤니티 질문**
- GitHub Issues
- 한국 파이썬 커뮤니티
- 질문 시 에러 로그, 실행 환경 정보 첨부

---

### Q6: 코드 수정 후 결과가 안 바뀌어요.

**A**: 캐싱 또는 이전 프로세스 확인하세요.

**해결 방법**:
1. **파이썬 캐시 삭제**
   ```bash
   find . -type d -name __pycache__ -exec rm -r {} +
   find . -type f -name "*.pyc" -delete
   ```

2. **프로세스 재시작**
   ```bash
   # 실행 중인 Python 프로세스 확인
   ps aux | grep python

   # 종료 후 재실행
   pkill -f python
   python main.py
   ```

3. **환경 변수 확인**
   ```bash
   # .env 파일이 제대로 로드되는지 확인
   python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('OPENAI_API_KEY'))"
   ```

---

### Q7: API 비용이 걱정돼요.

**A**: 비용 관리 방법이 있습니다.

**OpenAI/Anthropic API 비용 절감**:
1. **작은 모델 사용**
   ```python
   # 고비용
   model="gpt-4.1"  # $60/1M tokens

   # 저비용
   model="gpt-4-mini"  # $0.60/1M tokens (100배 저렴)
   ```

2. **프롬프트 길이 줄이기**
   - 불필요한 지시 제거
   - 예시 최소화

3. **캐싱 활용**
   - 동일 분석 재사용

4. **API 사용량 모니터링**
   - [OpenAI Usage Dashboard](https://platform.openai.com/usage)
   - [Anthropic Console](https://console.anthropic.com/)

**예상 비용** (GPT-4.1 기준):
- 종목 1개 분석: 약 $0.50~1.00
- 하루 10종목 분석: 약 $5~10
- 월간: 약 $150~300

---

## 📚 추가 학습 자료

### 공식 문서
- [Python 공식 튜토리얼](https://docs.python.org/ko/3/tutorial/)
- [Pandas 문서](https://pandas.pydata.org/docs/)
- [MCP 프로토콜](https://modelcontextprotocol.io/)
- [OpenAI API](https://platform.openai.com/docs/)
- [Anthropic Claude API](https://docs.anthropic.com/)

### 온라인 강의
- [점프 투 파이썬](https://wikidocs.net/book/1) - 무료
- [파이썬 증권 데이터 분석](https://wikidocs.net/book/110) - 무료
- [Coursera - Python for Everybody](https://www.coursera.org/specializations/python)

### 커뮤니티
- [파이썬 한국 사용자 모임](https://www.facebook.com/groups/pythonkorea/)
- [QuantConnect 포럼](https://www.quantconnect.com/forum/)
- [Reddit - r/algotrading](https://www.reddit.com/r/algotrading/)

### 추천 도서
- **파이썬 기초**: "파이썬 코딩 도장" (남재윤)
- **데이터 분석**: "파이썬 라이브러리를 활용한 데이터 분석" (웨스 맥키니)
- **퀀트 투자**: "파이썬을 이용한 퀀트 투자 포트폴리오 만들기" (강환국)

---

## ✅ 최종 체크리스트

### 1주차
- [ ] README.md 읽음
- [ ] 프로젝트 구조 파악
- [ ] 간단한 파일 3개 이상 읽음
- [ ] 개발 환경 설정 완료

### 2주차
- [ ] cores/main.py 이해
- [ ] 6개 분석 에이전트 역할 파악
- [ ] 실제 분석 1회 이상 실행
- [ ] 프롬프트 수정 실험

### 3주차
- [ ] 급등주 탐지 로직 이해
- [ ] 전체 파이프라인 흐름 파악
- [ ] async/await 개념 학습
- [ ] trigger_batch.py 실행

### 4주차
- [ ] AI 매매 결정 로직 분석
- [ ] Buy/Sell Specialist 차이 이해
- [ ] 시뮬레이션 1회 이상 실행
- [ ] 포트폴리오 관리 전략 파악

### 최종 프로젝트
- [ ] 나만의 에이전트 추가
- [ ] 커스텀 탐지 전략 구현
- [ ] 간단한 백테스팅 완료
- [ ] 학습 내용 정리 (블로그 or 노트)

---

## 🎓 마치며

축하합니다! 이 가이드를 따라오셨다면 이제 다음을 할 수 있습니다:

1. **AI 에이전트 시스템 이해**: Multi-agent 아키텍처 설계 및 구현
2. **비동기 프로그래밍**: Python asyncio를 활용한 효율적인 코드 작성
3. **데이터 파이프라인**: 수집 → 분석 → 리포팅 전 과정 이해
4. **API 연동**: 외부 서비스와 통합하는 방법
5. **프롬프트 엔지니어링**: AI에게 효과적으로 지시하는 기술

### 다음 단계

**프로젝트 아이디어**:
1. 다른 시장 적용 (미국 주식, 암호화폐)
2. 새로운 분석 전략 개발
3. 웹 대시보드 구축 (Streamlit 확장)
4. 모바일 앱 연동

**오픈소스 기여**:
- 버그 리포트
- 문서 개선
- 새 기능 PR (Pull Request)

**학습 공유**:
- 기술 블로그 작성
- YouTube 튜토리얼 제작
- 스터디 그룹 운영

---

**행운을 빕니다!** 🚀

질문이 있으시면 [GitHub Issues](https://github.com/dragon1086/prism-insight/issues)에 남겨주세요.

---

**작성일**: 2025-10-26
**버전**: 1.0.0
**작성자**: Claude (Anthropic AI)
**라이선스**: MIT (PRISM-INSIGHT 프로젝트와 동일)
