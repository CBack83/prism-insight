"""
PRISM-INSIGHT Telegram 긴급 알람 유틸리티
데이터 소스 실패 등 중요 이벤트 즉시 알람
"""

import os
import asyncio
from typing import Optional
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()


async def send_telegram_alert(
    message: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None
) -> bool:
    """
    Telegram으로 긴급 알람 전송

    Args:
        message: 전송할 메시지
        bot_token: Telegram 봇 토큰 (없으면 환경변수에서 로드)
        chat_id: 채널 ID (없으면 환경변수에서 로드)

    Returns:
        bool: 전송 성공 시 True
    """
    try:
        # 환경변수에서 토큰 로드
        if bot_token is None:
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if chat_id is None:
            chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not bot_token or not chat_id:
            print("⚠️ Telegram 설정 없음 - 알람 전송 생략")
            return False

        # telegram 라이브러리 동적 임포트
        try:
            from telegram import Bot
        except ImportError:
            print("⚠️ python-telegram-bot 라이브러리 미설치 - 알람 전송 생략")
            return False

        # 메시지 전송
        bot = Bot(token=bot_token)
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown"
        )
        return True

    except Exception as e:
        print(f"⚠️ Telegram 알람 전송 실패: {e}")
        return False


def send_telegram_alert_sync(message: str) -> bool:
    """
    Telegram 알람 동기 버전 (asyncio 이벤트 루프 없는 환경용)

    Args:
        message: 전송할 메시지

    Returns:
        bool: 전송 성공 시 True
    """
    try:
        return asyncio.run(send_telegram_alert(message))
    except RuntimeError:
        # 이미 실행 중인 이벤트 루프가 있을 경우
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 백그라운드 태스크로 실행
            asyncio.create_task(send_telegram_alert(message))
            return True
        else:
            return asyncio.run(send_telegram_alert(message))
    except Exception as e:
        print(f"⚠️ Telegram 알람 전송 실패: {e}")
        return False
