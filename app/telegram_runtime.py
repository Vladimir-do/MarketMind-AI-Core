import asyncio
import ssl
from collections.abc import Callable, Sequence

import certifi
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.types import BotCommand
from python_socks import ProxyConnectionError

from app.config import (
    TELEGRAM_DROP_PENDING_UPDATES,
    TELEGRAM_FORCE_DIRECT,
    TELEGRAM_PROXY,
    logger,
    require_bot_token,
)
from app.utils.proxy import mask_proxy_url, proxy_is_reachable

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


def _configure_session_proxy(session: AiohttpSession, proxy: str | None, ssl_ctx: ssl.SSLContext) -> None:
    if hasattr(session, "_setup_proxy_connector"):
        session._setup_proxy_connector(proxy)
    elif hasattr(session, "proxy"):
        session.proxy = proxy  # type: ignore[attr-defined]
    if hasattr(session, "_connector_init"):
        session._connector_init["ssl"] = ssl_ctx  # type: ignore[attr-defined]


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
    configured_proxy = None if TELEGRAM_FORCE_DIRECT else (TELEGRAM_PROXY if TELEGRAM_PROXY else None)
    current_proxy = configured_proxy
    if TELEGRAM_FORCE_DIRECT:
        logger.info("Telegram API proxy forcibly disabled; connecting directly")
    elif current_proxy:
        if not proxy_is_reachable(current_proxy):
            logger.warning(
                "Telegram API proxy is unreachable before polling starts: %s. Switched to direct mode",
                mask_proxy_url(current_proxy),
            )
            current_proxy = None
            logger.info("Telegram API proxy is not configured; connecting to api.telegram.org directly")
        else:
            logger.info("Telegram API proxy enabled: %s", mask_proxy_url(current_proxy))
    elif not TELEGRAM_FORCE_DIRECT:
        logger.info("Telegram API proxy is not configured; connecting to api.telegram.org directly")

    reconnect_attempt = 0
    http_session: AiohttpSession | None = None
    while True:
        polling_started = False
        reuse_session = False
        if http_session is None:
            http_session = AiohttpSession(proxy=None)
        _configure_session_proxy(http_session, current_proxy, ssl_ctx)
        active_bot = Bot(token=token, session=http_session)
        if set_active_bot is not None:
            set_active_bot(active_bot)
        try:
            await active_bot.delete_webhook(drop_pending_updates=TELEGRAM_DROP_PENDING_UPDATES)
            await active_bot.set_my_commands(commands)
            # Pre-polling probe: verify the connection works before entering
            # aiogram's internal _listen_updates retry loop (which swallows
            # all exceptions and retries forever, preventing our fallback).
            # Use get_me() instead of get_updates() to avoid consuming pending
            # updates when TELEGRAM_DROP_PENDING_UPDATES is False.
            await active_bot.get_me()
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
                await active_bot.session.close()
                _configure_session_proxy(http_session, None, ssl_ctx)
                current_proxy = None
                reconnect_attempt = 0
                reuse_session = True
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
                await active_bot.session.close()
                _configure_session_proxy(http_session, None, ssl_ctx)
                current_proxy = None
                reconnect_attempt = 0
                reuse_session = True
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
                await active_bot.session.close()
                _configure_session_proxy(http_session, None, ssl_ctx)
                current_proxy = None
                reconnect_attempt = 0
                reuse_session = True
                logger.info("Polling restarted")
                continue
            reconnect_attempt += 1
            delay = telegram_reconnect_delay(reconnect_attempt)
            _log_telegram_retry(e, delay, reconnect_attempt)
            await asyncio.sleep(delay)
        finally:
            if set_active_bot is not None:
                set_active_bot(None)
            if not reuse_session:
                await active_bot.session.close()
                http_session = None
        logger.info("Polling restarted")
