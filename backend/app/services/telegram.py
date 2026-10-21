"""Send alerts to a Telegram chat through a bot."""
import logging

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


def telegram_enabled() -> bool:
    return bool(settings.telegram_bot_token)


def send_message(chat_id: str, text: str) -> bool:
    if not telegram_enabled() or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        r = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        return r.status_code == 200
    except httpx.HTTPError as exc:
        log.warning("Telegram send failed: %s", exc)
        return False
