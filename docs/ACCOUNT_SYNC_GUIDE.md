# 실계좌-DB 동기화 가이드 (보고서 재사용 + AI 분석 자동 실행)

## 📌 개요

`sync_account_with_reports.py`는 실제 증권 계좌와 DB의 불일치를 자동으로 해소하는 범용 스크립트입니다.

### 핵심 기능

1. **KIS API 연동**: 실제 계좌 잔고 자동 조회
2. **보고서 재사용**: 이미 생성된 분석 보고서에서 목표가/손절가 추출
3. **AI 분석 자동 실행** ⭐ NEW: 보고서가 없을 때 자동으로 AI 분석 수행 (`--auto-analyze` 옵션)
4. **완전 자동화**: 차이점 발견 → 보고서 검색 → 분석 → DB 업데이트
5. **시간 절약**: AI 분석 재실행 불필요 (5-10분 → 30초)

---

## 🎯 사용 시나리오

### 시나리오 1: 매수 실패 후 수동 매수
```
배치 실행 → 매수 신호 발생 → API 매수 실패 → HTS 수동 매수
```

**문제**: 실계좌에는 있지만 DB에는 없어서 시스템이 관리 못함
**해결**: `sync_account_with_reports.py` 실행

### 시나리오 2: 부분 매도/추가 매수
```
시스템 보유 중 → HTS에서 부분 매도 → 수량 불일치
```

**문제**: DB 수량과 실제 수량이 다름
**해결**: `sync_account_with_reports.py` 실행

### 시나리오 3: 긴급 수동 매매
```
급락장 → HTS 긴급 손절 → DB에는 여전히 보유 중으로 기록
```

**문제**: 실계좌에는 없지만 DB에는 남아있음
**해결**: `sync_account_with_reports.py` 실행

---

## 🚀 사용법

### 기본 모드 (보고서 재사용만)

```bash
python sync_account_with_reports.py
```

- 최근 7일 이내 보고서: 재사용
- 7일 이전 보고서: Fallback으로 가장 최근 보고서 사용
- **보고서 없음**: 목표가/손절가를 0으로 설정 (수동 설정 필요)

### AI 분석 자동 실행 모드 ⭐ NEW

```bash
python sync_account_with_reports.py --auto-analyze
```

- 최근 7일 이내 보고서: 재사용
- 7일 이전 보고서: Fallback으로 가장 최근 보고서 사용
- **보고서 없음**: AI 분석 자동 실행 → 보고서 생성 → 목표가/손절가 추출

**장점**:
- 완전 자동화: 보고서가 없어도 자동으로 생성
- 정확한 목표가/손절가: AI 분석 기반 데이터
- 수동 작업 불필요

**주의사항**:
- 시간 소요: 종목당 5-10분
- API 비용: OpenAI API 호출 발생
- 급한 경우: 기본 모드 사용 후 수동 설정 권장

### 실행 결과 예시

```
=== 실계좌 잔고 조회 ===
보유 종목: 3개
  SK텔레콤(017670): 6주 @ 68,600원
  iM금융지주(139130): 21주 @ 14,250원
  에코프로비엠(247540): 2주 @ 215,000원

=== DB 잔고 조회 ===
DB 보유 종목: 2개
  iM금융지주(139130): 21주 @ 14,250원
  에코프로비엠(247540): 0주 @ 209,000원

=== 잔고 비교 ===
실계좌에만 있음: 1개 - {'017670'}
DB에만 있음: 0개
수량 차이: 1개

🔄 보고서 기반 동기화 시작
======================================================================

➕ 실계좌에만 있는 종목 (1개)

📌 SK텔레콤(017670) 처리 중...

📄 SK텔레콤(017670) 보고서 검색 (최근 7일)
  ✅ 보고서 발견: 017670_SK텔레콤_20260128_morning_gpt5.2.pdf
     생성일: 2026-01-28 00:46:23

🤖 SK텔레콤(017670) 보고서 분석 중...
  ✅ 분석 완료
     목표가: 72,500원
     손절가: 64,700원

  ✅ DB 추가 완료

✅ 동기화 완료!
```

### AI 분석 자동 실행 예시 (`--auto-analyze`)

```
📌 현대차(005380) 처리 중...

📄 현대차(005380) 보고서 검색 (최근 7일)
  ❌ 보고서를 찾을 수 없습니다
  🤖 보고서 없음 - AI 분석 자동 실행

🤖 현대차(005380) AI 분석 시작...
  ✅ 보고서 생성 완료: pdf_reports/005380_현대차_20260128_morning_gpt5.2.pdf
  ✅ AI 분석 완료
     목표가: 285,000원
     손절가: 248,500원

  ✅ DB 추가 완료

✅ 동기화 완료!
```

---

## 🔧 작동 원리

### 1단계: 차이점 분석
```
실계좌 ←→ DB 비교
├─ 실계좌에만 있음 → 추가 필요
├─ DB에만 있음 → 삭제 필요
└─ 수량 차이 → 업데이트 필요
```

### 2단계: 보고서 검색
```
pdf_reports/ 디렉토리에서 최근 7일 이내 보고서 검색
├─ 패턴: {ticker}_{company_name}_YYYYMMDD_*.pdf
├─ 가장 최근 파일 선택
└─ 없으면
   ├─ 기본 모드: 경고 후 기본값 사용 (목표가/손절가 0)
   └─ --auto-analyze: AI 분석 자동 실행
```

### 3단계: 보고서 분석 또는 생성

**보고서가 있는 경우**:
```
StockTrackingAgent.analyze_report() 사용
├─ PDF → 마크다운 변환
├─ AI 에이전트로 시나리오 추출
└─ 목표가/손절가 파싱
```

**보고서가 없고 --auto-analyze 옵션 사용 시** ⭐ NEW:
```
1. cores.analysis.analyze_stock() 실행
   ├─ 13개 AI 에이전트 협업
   ├─ 종합 분석 보고서 생성 (Markdown)
   └─ PDF 변환

2. StockTrackingAgent.analyze_report() 실행
   ├─ 생성된 보고서 분석
   └─ 목표가/손절가 추출
```

### 4단계: DB 동기화
```
실제 매수가/수량으로 DB 업데이트
├─ INSERT: 신규 종목
├─ UPDATE: 수량 차이
└─ DELETE: 매도된 종목
```

---

## 📊 보고서 처리 로직

### 보고서 검색 우선순위

1. **최근 7일 이내** 보고서 우선
2. 없으면 가장 최근 보고서 사용 (Fallback)
3. 그것도 없으면:
   - **기본 모드**: 기본값 사용 (목표가/손절가 0)
   - **--auto-analyze 모드**: AI 분석 자동 실행

### 보고서 패턴

```
pdf_reports/017670_SK텔레콤_20260128_morning_gpt5.2.pdf
            ^^^^^^  ^^^^^^^  ^^^^^^^^  ^^^^^^^
            종목코드  종목명    날짜      모드
```

### 분석 데이터 추출

- **목표가**: `scenario['target_price']`
- **손절가**: `scenario['stop_loss']`
- **투자기간**: `scenario['investment_period']`
- **섹터**: `scenario['sector']`
- **핵심 로직**: `scenario['key_levels']`

---

## ⚙️ 설정

### 보고서 검색 기간 변경

코드 내부에서 `days` 파라미터 수정:

```python
# 기본값: 7일
report_path = self.find_recent_report(ticker, company_name, days=7)

# 30일로 변경
report_path = self.find_recent_report(ticker, company_name, days=30)
```

### DB 경로 변경

```python
syncer = AccountReportSync(db_path="custom_path.sqlite")
```

### AI 분석 자동 실행 여부 (프로그래밍)

```python
# 기본 모드
syncer = AccountReportSync(auto_analyze=False)

# AI 분석 자동 실행 모드
syncer = AccountReportSync(auto_analyze=True)
```

---

## 🔄 실행 흐름 비교

### 기본 모드 (보고서 재사용만)

```
실계좌 조회
    ↓
DB와 비교
    ↓
실계좌에만 있는 종목 발견
    ↓
보고서 검색 (최근 7일)
    ↓
├─ 보고서 있음 → StockTrackingAgent.analyze_report()
│                 ↓
│                목표가/손절가 추출
│
└─ 보고서 없음 → 목표가/손절가 = 0
    ↓
DB 동기화 완료
```

### AI 분석 자동 실행 모드 (`--auto-analyze`)

```
실계좌 조회
    ↓
DB와 비교
    ↓
실계좌에만 있는 종목 발견
    ↓
보고서 검색 (최근 7일)
    ↓
├─ 보고서 있음 → StockTrackingAgent.analyze_report()
│                 ↓
│                목표가/손절가 추출
│
└─ 보고서 없음 → cores.analysis.analyze_stock()  ⭐ NEW
                  ↓
                 보고서 생성 (PDF)
                  ↓
                 StockTrackingAgent.analyze_report()
                  ↓
                 목표가/손절가 추출
    ↓
DB 동기화 완료
```

---

## 🔍 문제 해결

### 문제: "보고서를 찾을 수 없습니다"

**원인**: pdf_reports/ 디렉토리에 해당 종목 보고서 없음

**해결**:
```bash
# 최근 보고서 확인
ls -lt pdf_reports/ | head -20

# 해당 종목 보고서 검색
ls pdf_reports/*017670*
```

**대응**:
- **옵션 1**: `--auto-analyze` 옵션으로 자동 분석 실행
  ```bash
  python sync_account_with_reports.py --auto-analyze
  ```
- **옵션 2**: 기본값(목표가/손절가 0)으로 일단 등록 후 수동 설정
- **옵션 3**: `account_balance_sync.py`로 별도 AI 분석 수행

### 문제: "토큰 만료"

**원인**: KIS API 토큰 만료

**해결**:
```bash
# 토큰 파일 삭제 (자동 재발급)
rm trading/config/KIS20*
```

### 문제: "분석 실패"

**원인**: 보고서 형식 변경 또는 파싱 오류

**해결**:
- 로그 확인: `tail -f stock_tracking_*.log`
- 보고서 수동 확인
- 기본값으로 일단 등록 후 수동 설정

---

## 🆚 스크립트 비교

| 항목 | account_balance_sync.py | sync_account_with_reports.py<br>(기본 모드) | sync_account_with_reports.py<br>(--auto-analyze) |
|------|-------------------------|------------------------------|------------------------------------------------|
| AI 분석 | 매번 새로 실행 | 보고서 재사용 | 보고서 재사용 + 없으면 자동 실행 |
| 소요 시간 | 5-10분 | 30초 | 30초 (보고서 있음)<br>5-10분 (보고서 없음) |
| 보고서 생성 | 항상 생성 | X (기존 재사용) | 보고서 없을 때만 생성 |
| 보고서 없을 때 | 새로 생성 | 기본값(0) 사용 | 자동으로 생성 |
| 적용 상황 | 신규 종목 | 보고서 있는 종목 | 모든 종목 (범용) |
| 권장 사용 | 신규 종목 동기화 | 빠른 동기화 | 완전 자동화 필요시 |

---

## 💡 활용 팁

### 1. 정기 실행 (Cron)

**빠른 동기화 (보고서 재사용)**:
```bash
# 매일 장 마감 후 자동 실행
0 16 * * 1-5 cd /path/to/prism-insight && python sync_account_with_reports.py >> sync.log 2>&1
```

**완전 자동화 (AI 분석 포함)**:
```bash
# 매일 장 마감 후 AI 분석 자동 실행
0 16 * * 1-5 cd /path/to/prism-insight && python sync_account_with_reports.py --auto-analyze >> sync_auto.log 2>&1
```

### 2. 배치 실패 시 즉시 실행

**보고서가 있는 경우 (빠른 복구)**:
```bash
# 오전 배치 후
python sync_account_with_reports.py

# 오후 배치 후
python sync_account_with_reports.py
```

**보고서가 없는 경우 (완전 자동화)**:
```bash
python sync_account_with_reports.py --auto-analyze
```

### 3. 수동 매매 후 즉시 실행

HTS에서 수동 매수/매도 후:
```bash
# 빠른 동기화 (보고서가 이미 있는 종목)
python sync_account_with_reports.py

# 완전 자동화 (신규 종목 포함)
python sync_account_with_reports.py --auto-analyze
```

### 4. 주말 점검

```bash
# 주말에 한 주간 거래 검증 (보고서 재사용)
python sync_account_with_reports.py

# 완전 점검 (신규 보고서 생성 포함)
python sync_account_with_reports.py --auto-analyze
```

### 5. 모드 선택 가이드

| 상황 | 권장 모드 | 이유 |
|------|-----------|------|
| 배치 매수 실패 후 수동 매수 | 기본 모드 | 보고서 이미 생성되어 있음 |
| HTS 긴급 매수 (신규 종목) | `--auto-analyze` | 보고서 없음 |
| 정기 점검 | 기본 모드 | 빠른 확인 |
| 완전 자동화 필요 | `--auto-analyze` | 모든 경우 대응 |
| 시간 여유 없음 | 기본 모드 | 30초 완료 |
| API 비용 절약 | 기본 모드 | AI 분석 최소화 |

---

## 📝 변경 이력

### v1.1.0 (2026-01-28)
- **AI 분석 자동 실행 기능 추가** (`--auto-analyze` 옵션)
- 보고서가 없을 때 자동으로 AI 분석 수행
- `analyze_new_stock()` 메서드 추가
- `cores.analysis.analyze_stock()` 통합
- 완전 자동화 워크플로우 구현

### v1.0.0 (2026-01-28)
- 초기 버전 생성
- 보고서 기반 동기화 구현
- 실계좌 불일치 자동 해소
- 목표가/손절가 자동 추출

---

## 🔗 관련 문서

- [account_balance_sync.py 설명](../account_balance_sync.py) - 전체 AI 분석 수행 버전
- [Stock Tracking Agent](../stock_tracking_agent.py) - 매매 시나리오 분석
- [Trading Documentation](TRADING_JOURNAL.md) - 트레이딩 저널 시스템

---

**최초 작성**: 2026-01-28
**최종 업데이트**: 2026-01-28 (v1.1.0 - AI 분석 자동 실행 기능 추가)
**작성자**: PRISM-INSIGHT Development Team
