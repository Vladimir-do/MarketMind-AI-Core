"""
telegram_humanize.py — Делает ответы бота живыми и человечными.
Вместо сухих «Метрик нет» → «Пока ничего не парсили, запустите /update».
"""
import random

# ── Приветствия и заглушки ────────────────────────────────────────────────────

def greeting() -> str:
    """Живое приветствие при /start."""
    variants = [
        "Привет! Я MarketMind — слежу за ценами на маркетплейсах и делаю карточки для Ozon. Чем могу помочь?",
        "Здравствуйте! MarketMind на связи. Мониторю цены, ищу сделки, генерирую карточки. Команда /help покажет что умею.",
        "Привет! Здесь можно следить за ценами на Ozon/Wildberries, находить лучшие сделки и готовить карточки товаров. Начните с /help.",
    ]
    return random.choice(variants)


def empty_database() -> str:
    """База пуста — предложи начать."""
    variants = [
        "База пустая — пока не за кем не слежим. Добавьте ссылки на товары через /add, и я начну мониторинг цен.",
        "Пока ничего не отслеживается. Скиньте ссылки на товары командой /add — и я запущу парсинг.",
        "Нет товаров в базе. Пришлите ссылки через /add, и я начну следить за ценами.",
    ]
    return random.choice(variants)


def parser_busy() -> str:
    """Парсер занят."""
    variants = [
        "Сейчас парсер занят — предыдущая задача ещё выполняется. Подождите немного и попробуйте снова.",
        "Парсер загружен другим запросом. Дайте ему пару секунд и повторите.",
        "Идёт парсинг, подождите завершения. Обычно это занимает 10-30 секунд.",
    ]
    return random.choice(variants)


def access_denied() -> str:
    """Доступ запрещён."""
    return "К сожалению, у вас нет доступа к этому боту. Обратитесь к администратору."


def no_metrics() -> str:
    """Метрик пока нет."""
    variants = [
        "Пока нечего показать — попыток парсинга ещё не было. Запустите /update, и я соберу метрики.",
        "Метрик пока нет. Запустите обновление цен через /update, и данные появятся.",
    ]
    return random.choice(variants)


def no_blocks() -> str:
    """Block memory пуста."""
    return "Память блокировок пустая — пока ничего не блокировалось. Хороший знак!"


def no_health() -> str:
    """Нет данных о здоровье маркетплейсов."""
    return "Данных о здоровье маркетплейсов пока нет. Запустите парсинг через /update."


def nothing_found(query: str | None = None) -> str:
    """Ничего не найдено."""
    q = f" по запросу «{query}»" if query else ""
    variants = [
        f"К сожалению, ничего не найдено{q}. Попробуйте переформулировать или другой запрос.",
        f"По запросу{q}пусто. Попробуйте другие ключевые слова.",
    ]
    return random.choice(variants)


def search_started(query: str) -> str:
    """Начало поиска."""
    return f"Ищу «{query}» на Ozon, подождите секунду..."


def update_started(count: int) -> str:
    """Начало обновления цен."""
    variants = [
        f"Запускаю обновление цен для {count} товаров. Это займёт немного времени...",
        f"Обновляю цены {count} товаров. Подождите, пожалуйста...",
        f"Начинаю парсинг {count} товаров. Обычно это 1-3 минуты в зависимости от количества.",
    ]
    return random.choice(variants)


def update_finished(success: int, failed: int) -> str:
    """Обновление завершено."""
    if failed == 0:
        return f"Готово! Обновлено {success} товаров, все успешно."
    return f"Обновление завершено: {success} успешно, {failed} с ошибками. Посмотрите /metrics для деталей."


def add_started(count: int) -> str:
    """Начало добавления товаров."""
    return f"Добавляю {count} товаров в мониторинг. Сейчас спаршу их и сохраню в базу..."


def add_finished(count: int) -> str:
    """Товары добавлены."""
    variants = [
        f"Готово! {count} товаров добавлено в мониторинг. Теперь могу обновлять их цены через /update.",
        f"{count} товаров на связи! Теперь отслеживаю их цены. Команда /update запустит обновление.",
    ]
    return random.choice(variants)


def card_generating() -> str:
    """Генерация карточки."""
    return "Готовлю карточку для Ozon, подождите секунду..."


def card_ready() -> str:
    """Карточка готова."""
    return "Вот ваша карточка для Ozon:"


def analyzing() -> str:
    """Анализ данных."""
    return "Анализирую данные, это займёт пару секунд..."


def report_generating() -> str:
    """Генерация отчёта."""
    return "Собираю HTML-отчёт с графиками и метриками..."


def network_check() -> str:
    """Проверка сети."""
    return "Проверяю сетевое соединение и прокси, подождите..."


def subscribe_ok() -> str:
    """Подписка оформлена."""
    return "Подписка оформлена! Теперь буду присылать уведомления, когда цены изменятся."


def unsubscribe_ok() -> str:
    """Отписка."""
    return "Отписка выполнена. Уведомления больше не будут приходить."


def error_message(detail: str = "") -> str:
    """Ошибка."""
    base = "Что-то пошло не так"
    if detail:
        return f"{base}: {detail}"
    return f"{base}. Попробуйте ещё раз или обратитесь к администратору."


def help_text() -> str:
    """Красивый help-текст."""
    return (
        "<b>MarketMind — ваш помощник по маркетплейсам</b>\n\n"
        "Я слежу за ценами, ищу сделки и готовлю карточки для Ozon.\n\n"
        "<b> Мониторинг:</b>\n"
        "/add — добавить товары по ссылкам\n"
        "/update — обновить цены\n"
        "/list — все отслеживаемые товары\n"
        "/status — статистика базы\n\n"
        "<b> Поиск:</b>\n"
        "/search — найти товар по названию\n"
        "/compare — сравнить цены\n\n"
        "<b> Карточки Ozon:</b>\n"
        "/ozon_card — сделать карточку\n"
        "/ozon_batch_cards — пачка карточек\n"
        "/profile — выбрать профиль\n\n"
        "<b> Аналитика:</b>\n"
        "/analyze — AI-анализ цен\n"
        "/deals — лучшие сделки\n"
        "/anomalies — подозрительные изменения\n"
        "/report — HTML-отчёт с графиками\n\n"
        "<b> Диагностика:</b>\n"
        "/metrics — попытки парсинга\n"
        "/blocks — блокировки и anti-bot\n"
        "/health — здоровье маркетплейсов\n"
        "/net_diag — проверка сети\n\n"
        "<b> Уведомления:</b>\n"
        "/subscribe — подписаться на изменения цен\n"
        "/unsubscribe — отписаться\n\n"
        "Можно писать просто текстом — я пойму и выполню!"
    )


def natural_response(intent: str, **kwargs) -> str:
    """Универсальный генератор ответов по типу намерения."""
    handlers = {
        "greeting": lambda: greeting(),
        "empty_db": lambda: empty_database(),
        "busy": lambda: parser_busy(),
        "denied": lambda: access_denied(),
        "no_metrics": lambda: no_metrics(),
        "no_blocks": lambda: no_blocks(),
        "no_health": lambda: no_health(),
        "nothing_found": lambda: nothing_found(kwargs.get("query")),
        "search_started": lambda: search_started(kwargs.get("query", "")),
        "update_started": lambda: update_started(kwargs.get("count", 0)),
        "update_finished": lambda: update_finished(
            kwargs.get("success", 0), kwargs.get("failed", 0)
        ),
        "add_started": lambda: add_started(kwargs.get("count", 0)),
        "add_finished": lambda: add_finished(kwargs.get("count", 0)),
        "card_generating": lambda: card_generating(),
        "card_ready": lambda: card_ready(),
        "analyzing": lambda: analyzing(),
        "report": lambda: report_generating(),
        "network": lambda: network_check(),
        "subscribe_ok": lambda: subscribe_ok(),
        "unsubscribe_ok": lambda: unsubscribe_ok(),
        "error": lambda: error_message(kwargs.get("detail", "")),
        "help": lambda: help_text(),
    }
    handler = handlers.get(intent)
    if handler:
        return handler()
    return f"Выполняю: {intent}"
