import asyncio
import ssl
from collections.abc import Callable, Sequence

import certifi
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.types import BotCommand
from python_socks import ProxyConnectionError

from app.config import TELEGRAM_DROP_PENDING_UPDATES, TELEGRAM_PROXY, logger, require_bot_token
from app.telegram_diagnostics import mask_proxy_url


TELEGRAM_RECONNECT_DELAYS_SEC = (1, 2, 5, 10, 30, 60)


def telegram_reconnect_delay(attempt: int) -> int:
    if attempt < 1:
        return TELEGRAM_RECONNECT_DELAYS_SEC[0]
    return TELEGRAM_RECONNECT_DELAYS_SEC[
        min(attempt - 1, len(TELEGRAM_RECONNECT_DELAYS_SEC) - 1)
    ]


def _log_telegram_retry(error: BaseException, delay: int, attempt: int) -> None:
    logger.warning("Telegram network error: %s", error)
    logger.warning("Retry in %s seconds", delay)
    logger.debug("Telegram polling retry attempt=%s", attempt)


async def run_telegram_polling(
    *,
    db,
    dp,
    commands: Sequence[BotCommand],
    set_active_bot: Callable[[Bot | None], None] | None = None,
) -> bool:
    logger.info("🥷 Запуск агента мониторинга цен Озон...")
    await db.init()
    token = require_bot_token()
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    configured_proxy = TELEGRAM_PROXY if TELEGRAM_PROXY else None
    current_proxy = configured_proxy
    if current_proxy:
        logger.info("Telegram API proxy enabled: %s", mask_proxy_url(current_proxy))
    else:
        logger.info("Telegram API proxy is not configured; connecting to api.telegram.org directly")

    reconnect_attempt = 0
    while True:
        polling_started = False
        http_session = AiohttpSession(proxy=current_proxy)
        http_session._connector_init["ssl"] = ssl_ctx
        active_bot = Bot(token=token, session=http_session)
        if set_active_bot is not None:
            set_active_bot(active_bot)
        try:
            await active_bot.delete_webhook(drop_pending_updates=TELEGRAM_DROP_PENDING_UPDATES)
            await active_bot.set_my_commands(commands)
            logger.info("Telegram connected")
            logger.info("Telegram polling started")
            polling_started = True
            await dp.start_polling(active_bot)
            return True
        except TelegramUnauthorizedError:
            logger.error(
                "Telegram API rejected BOT_TOKEN: Unauthorized. "
                "Проверьте, что в .env указан актуальный токен от @BotFather без кавычек и лишних пробелов."
            )
            return False
        except ProxyConnectionError as e:
            if current_proxy:
                logger.warning(
                    "Telegram network error through proxy %s: %s.",
                    mask_proxy_url(current_proxy),
                    e,
                )
                logger.warning("Switched to direct mode")
                current_proxy = None
                reconnect_attempt = 0
                logger.info("Polling restarted")
                continue
            reconnect_attempt += 1
            delay = telegram_reconnect_delay(reconnect_attempt)
            _log_telegram_retry(e, delay, reconnect_attempt)
            await asyncio.sleep(delay)
        except TelegramNetworkError as e:
            if current_proxy and not polling_started:
                logger.warning(
                    "Telegram network error through proxy %s: %s.",
                    mask_proxy_url(current_proxy),
                    e,
                )
                logger.warning("Switched to direct mode")
                current_proxy = None
                reconnect_attempt = 0
                logger.info("Polling restarted")
                continue
            reconnect_attempt += 1
            delay = telegram_reconnect_delay(reconnect_attempt)
            _log_telegram_retry(e, delay, reconnect_attempt)
            await asyncio.sleep(delay)
        except (ConnectionError, OSError, TimeoutError) as e:
            if current_proxy and not polling_started:
                logger.warning(
                    "Telegram network error through proxy %s: %s.",
                    mask_proxy_url(current_proxy),
                    e,
                )
                logger.warning("Switched to direct mode")
                current_proxy = None
                reconnect_attempt = 0
                logger.info("Polling restarted")
                continue
            reconnect_attempt += 1
            delay = telegram_reconnect_delay(reconnect_attempt)
            _log_telegram_retry(e, delay, reconnect_attempt)
            await asyncio.sleep(delay)
        finally:
            if set_active_bot is not None:
                set_active_bot(None)
            await active_bot.session.close()
        logger.info("Polling restarted")
