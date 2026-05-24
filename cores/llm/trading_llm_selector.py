"""Select the trading-agent LLM transport for the current auth mode.

Official OpenAI API-key mode can use the Responses API directly. ChatGPT OAuth
mode must go through the local Codex OAuth proxy, which currently exposes the
OpenAI-compatible Chat Completions route only (`/v1/chat/completions`).
"""

import os


def is_chatgpt_oauth_mode() -> bool:
    """Return True when PRISM should route OpenAI calls through ChatGPT OAuth."""
    return os.getenv("PRISM_OPENAI_AUTH_MODE", "api_key").strip().lower() == "chatgpt_oauth"


if is_chatgpt_oauth_mode():
    # The OAuth proxy translates Chat Completions requests to the ChatGPT Codex
    # Responses backend. Calling client.responses.create() directly would hit
    # /v1/responses on the local proxy, which is not implemented and returns 404.
    from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM

    SELECTED_TRADING_LLM_BACKEND = "chat_completions_via_chatgpt_oauth_proxy"
else:
    from cores.llm.openai_responses_llm import OpenAIResponsesLLM as OpenAIAugmentedLLM

    SELECTED_TRADING_LLM_BACKEND = "openai_responses_api"
