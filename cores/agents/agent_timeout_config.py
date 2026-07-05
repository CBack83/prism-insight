"""
에이전트별 타임아웃 설정

각 에이전트 유형에 따라 적절한 타임아웃과 재시도 횟수를 설정합니다.
MCP 서버 응답 지연이나 복잡한 분석 작업에 대응하기 위한 설정입니다.
"""

# 에이전트별 타임아웃 설정 (초 단위)
AGENT_TIMEOUT_CONFIG = {
    # === 분석 에이전트 (일반) ===
    "price_volume_agent": {"timeout": 120, "max_retries": 2},
    "investor_trading_agent": {"timeout": 120, "max_retries": 2},
    "company_status_agent": {"timeout": 120, "max_retries": 2},
    "company_overview_agent": {"timeout": 120, "max_retries": 2},
    "news_analysis_agent": {"timeout": 150, "max_retries": 2},
    "market_index_agent": {"timeout": 150, "max_retries": 2},  # P95 actual: 64s, buffer for kospi_kosdaq+perplexity

    # === 전략 에이전트 (중간 타임아웃) ===
    "investment_strategy_agent": {"timeout": 180, "max_retries": 2},
    "summary_agent": {"timeout": 150, "max_retries": 2},

    # === 매매 에이전트 (긴 타임아웃 - 복잡한 의사결정) ===
    "trading_journal_agent": {"timeout": 300, "max_retries": 3},
    "sell_decision_agent": {"timeout": 240, "max_retries": 2},
    "buy_decision_agent": {"timeout": 240, "max_retries": 2},

    # === 텔레그램 에이전트 ===
    "telegram_summary_optimizer_agent": {"timeout": 180, "max_retries": 2},
    "telegram_summary_evaluator_agent": {"timeout": 120, "max_retries": 2},
    "telegram_translator_agent": {"timeout": 120, "max_retries": 2},

    # === 기본값 ===
    "default": {"timeout": 120, "max_retries": 2}
}


def get_agent_timeout(agent_name: str) -> dict:
    """
    에이전트 이름에 따른 타임아웃 설정 반환

    Args:
        agent_name: 에이전트 이름 (예: "price_volume_agent", "trading_journal_agent")

    Returns:
        dict: {"timeout": int, "max_retries": int} 형태의 설정
    """
    return AGENT_TIMEOUT_CONFIG.get(agent_name, AGENT_TIMEOUT_CONFIG["default"])


def get_timeout_seconds(agent_name: str) -> int:
    """
    에이전트 이름에 따른 타임아웃(초) 반환

    Args:
        agent_name: 에이전트 이름

    Returns:
        int: 타임아웃 초
    """
    return get_agent_timeout(agent_name)["timeout"]


def get_max_retries(agent_name: str) -> int:
    """
    에이전트 이름에 따른 최대 재시도 횟수 반환

    Args:
        agent_name: 에이전트 이름

    Returns:
        int: 최대 재시도 횟수
    """
    return get_agent_timeout(agent_name)["max_retries"]
