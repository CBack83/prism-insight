"""
PRISM-INSIGHT 데이터 검증 유틸리티
MCP 서버 상태 확인, 데이터 검증, 가격 일치성 검증
"""

import re
from typing import Dict, Any, Optional
from mcp_agent import MCPApp
from .exceptions import DataSourceError, DataValidationError, PriceDataMismatchError


async def verify_mcp_server_health(server_name: str, app: MCPApp) -> bool:
    """
    MCP 서버 연결 상태 확인

    Args:
        server_name: MCP 서버 이름
        app: MCPApp 인스턴스

    Returns:
        bool: 서버가 정상이면 True, 아니면 False
    """
    try:
        # MCP 서버 상태 확인 로직
        async with app.tool_manager(tools=[server_name]) as tools:
            if not tools or len(tools) == 0:
                return False
            return True
    except Exception as e:
        return False


def validate_report_data(report_text: str, section: str) -> bool:
    """
    보고서 내용에 필수 데이터가 포함되어 있는지 검증

    Args:
        report_text: 생성된 보고서 텍스트
        section: 분석 섹션 이름

    Returns:
        bool: 검증 통과 시 True

    Raises:
        DataValidationError: 필수 데이터 누락 시
    """
    if not report_text or len(report_text.strip()) < 100:
        raise DataValidationError(f"{section}: 보고서가 너무 짧거나 비어있음")

    # 할루시네이션 방지: "데이터가 불충분", "확인이 어렵습니다" 등의 문구 확인
    hallucination_indicators = [
        "tool call",
        "I'll use",
        "Calling tool",
        "Let me",
        "I'll create",
        "I'll analyze"
    ]

    for indicator in hallucination_indicators:
        if indicator in report_text:
            raise DataValidationError(
                f"{section}: 보고서에 도구 호출 언급이 포함됨 (할루시네이션 가능성)"
            )

    # 섹션별 필수 키워드 검증
    if section == "price_volume_analysis":
        required_keywords = ["주가", "거래량"]
        for keyword in required_keywords:
            if keyword not in report_text:
                raise DataValidationError(
                    f"{section}: 필수 키워드 '{keyword}' 누락"
                )

    return True


def extract_price_from_report(report_text: str) -> Optional[float]:
    """
    보고서에서 현재가/최근 종가 추출

    Args:
        report_text: 보고서 텍스트

    Returns:
        Optional[float]: 추출된 가격, 없으면 None
    """
    # "최근 종가", "현재가" 등의 패턴에서 가격 추출
    patterns = [
        r'최근\s*종가[:\s]*\*?\*?([0-9,]+)원',
        r'현재가[:\s]*\*?\*?([0-9,]+)원',
        r'기준\s*가격[:\s]*\*?\*?([0-9,]+)원',
    ]

    for pattern in patterns:
        match = re.search(pattern, report_text)
        if match:
            price_str = match.group(1).replace(',', '')
            try:
                return float(price_str)
            except ValueError:
                continue

    return None


def validate_analysis_price(
    analyzed_price: float,
    trigger_price: float,
    tolerance: float = 0.1,
    company_name: str = ""
) -> None:
    """
    분석된 가격이 트리거 가격과 합리적 범위 내인지 검증

    Args:
        analyzed_price: 분석에서 사용된 가격
        trigger_price: 트리거 감지 시점의 가격
        tolerance: 허용 오차율 (기본 10%)
        company_name: 종목명 (로깅용)

    Raises:
        PriceDataMismatchError: 가격 불일치 시
    """
    if analyzed_price <= 0 or trigger_price <= 0:
        raise PriceDataMismatchError(
            f"{company_name}: 유효하지 않은 가격 데이터 "
            f"(분석={analyzed_price}, 트리거={trigger_price})"
        )

    diff_ratio = abs(analyzed_price - trigger_price) / trigger_price

    if diff_ratio > tolerance:
        raise PriceDataMismatchError(
            f"{company_name}: 가격 데이터 불일치 (오차율 {diff_ratio*100:.1f}%)\n"
            f"  - 트리거 가격: {trigger_price:,.0f}원\n"
            f"  - 분석 가격: {analyzed_price:,.0f}원\n"
            f"  - 허용 오차: {tolerance*100:.0f}%"
        )


def create_data_quality_metadata(
    data_sources_status: Dict[str, bool],
    timestamp: str,
    validation_passed: bool
) -> Dict[str, Any]:
    """
    데이터 품질 메타데이터 생성

    Args:
        data_sources_status: 각 데이터 소스의 상태 {server_name: success/fail}
        timestamp: 분석 시각
        validation_passed: 검증 통과 여부

    Returns:
        Dict: 메타데이터
    """
    success_count = sum(1 for status in data_sources_status.values() if status)
    total_count = len(data_sources_status)
    reliability_score = success_count / total_count if total_count > 0 else 0.0

    return {
        "timestamp": timestamp,
        "data_sources": data_sources_status,
        "validation_passed": validation_passed,
        "reliability_score": reliability_score,
        "status": "신뢰가능" if reliability_score >= 0.8 else "검증필요"
    }


def format_metadata_for_report(metadata: Dict[str, Any]) -> str:
    """
    메타데이터를 마크다운 형식으로 변환

    Args:
        metadata: 데이터 품질 메타데이터

    Returns:
        str: 마크다운 형식의 메타데이터
    """
    status_icon = "✅" if metadata["reliability_score"] >= 0.8 else "⚠️"

    sources_md = "\n".join([
        f"  - {name}: {'✅ 정상' if status else '❌ 실패'}"
        for name, status in metadata["data_sources"].items()
    ])

    return f"""
---

## 📊 데이터 품질 정보

{status_icon} **신뢰도 점수**: {metadata['reliability_score']:.0%} ({metadata['status']})

**데이터 소스 상태**:
{sources_md}

**분석 시각**: {metadata['timestamp']}

---
"""
