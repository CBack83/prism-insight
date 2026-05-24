# GitHub 릴리즈 노트 활용 가이드

## 📌 개요

GitHub 릴리즈 노트를 사용하여 이번 개선사항을 공식적으로 문서화하고 공유할 수 있습니다.

---

## 🚀 릴리즈 생성 방법

### 방법 1: GitHub 웹 인터페이스 (권장)

1. **저장소 접속**
   - https://github.com/CBack83/prism-insight 접속

2. **릴리즈 페이지 이동**
   - 우측 사이드바에서 "Releases" 클릭
   - 또는 직접 URL: https://github.com/CBack83/prism-insight/releases

3. **새 릴리즈 작성**
   - "Draft a new release" 버튼 클릭

4. **릴리즈 정보 입력**
   ```
   Tag version: v1.1.0
   Release title: v1.1.0 - DB-계좌 동기화 개선

   Description: (아래 템플릿 사용)
   ```

5. **변경사항 커밋 선택**
   - Target: main 브랜치
   - 최신 커밋 (8db7d38) 자동 포함

6. **게시**
   - "Publish release" 클릭

---

### 방법 2: GitHub CLI 설치 후 사용 (선택사항)

```bash
# GitHub CLI 설치 (macOS)
brew install gh

# 인증
gh auth login

# 릴리즈 생성
gh release create v1.1.0 \
  --title "v1.1.0 - DB-계좌 동기화 개선" \
  --notes-file git-sync-improvement-report-20251103.md \
  --target main
```

---

## 📝 릴리즈 노트 템플릿

아래 내용을 GitHub 릴리즈 Description에 복사하여 사용하세요:

```markdown
## 🎯 주요 개선사항

이번 릴리즈는 DB와 실제 증권사 계좌 간 동기화 안정성을 크게 향상시킵니다.

### 1️⃣ 트레이딩 모드 동적 설정
- `StockTrackingAgent`에 `trading_mode` 파라미터 추가
- yaml 설정의 `default_mode`를 자동으로 읽어 적용
- 하드코딩된 "real" 모드 제거로 유연성 향상

**효과**:
- ✅ 모의투자 ↔ 실전투자 전환 용이
- ✅ 테스트 환경과 실전 환경 명확히 분리

### 2️⃣ 트레이딩 API 클라이언트 재사용
- 싱글톤 패턴으로 `self.trading_api_client` 재사용
- 매번 새 인스턴스 생성하던 기존 방식 개선

**효과**:
- ✅ 중복 인증 세션 제거
- ✅ 토큰 갱신 안정성 개선
- ✅ API rate limit 효율적 활용

### 3️⃣ 수동 매수 종목 자동 DB 추가
- HTS/앱에서 수동 매수한 종목을 자동으로 DB에 추가
- 기본 매매 시나리오 자동 생성 (목표가 +10%, 손절가 -5%)

**효과**:
- ✅ AI가 수동 매수 종목도 추적 가능
- ✅ 포트폴리오 통합 관리
- ✅ 사용자 편의성 향상

---

## 📊 변경 내역

**변경 파일**:
- `stock_tracking_agent.py`: 약 150줄 수정

**커밋**:
- `8db7d38` - refactor: Improve DB-account sync with dynamic mode and API client reuse

---

## 📖 상세 문서

전체 개선사항 상세 내용은 [개선사항 리포트](./git-sync-improvement-report-20251103.md)를 참고하세요.

---

## ⚠️ 주의사항

### Breaking Changes
없음 (하위 호환성 유지)

### 업그레이드 방법
```bash
git pull origin main
# 기존 프로세스 재시작
```

### 테스트 권장사항
1. 모드 전환 테스트 (demo ↔ real)
2. 수동 매수 종목 동기화 확인
3. API 인증 안정성 모니터링

---

## 🙏 기여자

- @CBack83 - DB-계좌 동기화 로직 설계 및 리뷰
- Claude Code (AI Assistant) - 코드 구현 및 문서화

---

**Full Changelog**: https://github.com/CBack83/prism-insight/compare/v1.0.0...v1.1.0
```

---

## 🔖 버전 태그 생성 (로컬)

릴리즈 전에 로컬에서 태그를 미리 생성할 수도 있습니다:

```bash
# 태그 생성
git tag -a v1.1.0 -m "Release v1.1.0: DB-계좌 동기화 개선"

# 태그 확인
git tag -l

# 태그 푸시 (릴리즈 후)
git push origin v1.1.0
```

---

## 📚 참고 자료

- [GitHub 릴리즈 문서](https://docs.github.com/en/repositories/releasing-projects-on-github)
- [Semantic Versioning](https://semver.org/lang/ko/)
- [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/)

---

## ✅ 체크리스트

릴리즈 전 확인사항:

- [x] 코드 변경사항 커밋 완료
- [x] 개선사항 리포트 작성
- [x] 릴리즈 노트 템플릿 준비
- [ ] 버전 태그 생성 (v1.1.0)
- [ ] GitHub 릴리즈 페이지 작성
- [ ] 릴리즈 게시
- [ ] 팀원에게 공지

---

**생성일**: 2025-11-03
**작성자**: AI Assistant (Claude Code)
