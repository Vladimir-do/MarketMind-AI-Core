# Стандарты кодирования — MarketMind AI

Руководство по стилю кода для проекта MarketMind AI. Все правила на русском языке.

---

## 1. PEP 8 и форматирование

### Отступы и пробелы

- Отступ: 4 пробела (никогда табуляция).
- Максимальная длина строки: 120 символов (не 79 — проект использует широкие экраны).
- Пустая строка между функциями и методами класса (2 пустые строки между топ-уровнями).
- Нет trailing whitespace.

### Пробелы вокруг операторов

```python
# Правильно
x = 1 + 2
if x > 0:
    result = func(a, b)

# Неправильно
x = 1 + 2
if x > 0:
    result = func(a, b)
```

### Импорты

- Группируются в порядке:标准库, сторонние библиотеки, локальные модули.
- Каждая группа отделена пустой строкой.
- Не используйте `from module import *`.
- Импортируйте конкретные имена:

```python
# Правильно
from app.database import Database, Product, PriceHistory

# Неправильно
from app.database import *
```

---

## 2. Type Hints

### Обязательные аннотации

- Все функции должны иметь аннотации параметров и возвращаемого значения.
- Используйте `|` для Optional (Python 3.10+):

```python
# Правильно
async def fetch_product(url: str, proxy: str | None = None) -> ProductData | None:

# Неправильно
async def fetch_product(url, proxy=None):
```

### Коллекции

```python
from typing import Sequence


def process_items(items: Sequence[Product]) -> dict[str, int]: ...


async def get_urls(db: Database) -> list[str]: ...
```

### Dataclass аннотации

```python
from dataclasses import dataclass


@dataclass
class ScrapingResult:
    url: str
    success: bool
    status: str
    latency_ms: float
    error: str | None = None
```

---

## 3. Docstrings

### Формат

Используйте Google-style docstrings:

```python
async def worker_add_urls(
    db: Database,
    urls: list[str],
    notify: Callable | None = None,
) -> list[dict]:
    """Добавляет товары по URL в фоновом режиме.

    Args:
        db: Экземпляр Database для записи.
        urls: Список URL-ссылок на товары.
        notify: Callback для отправки прогресса.

    Returns:
        Список результатов добавления.

    Raises:
        ValueError: Если urls пустой.
    """
```

### Когда писать docstring

- Публичные функции и методы классов.
- Модули (в начале файла).
- Классы.
- НЕ пишите docstring для приватных методов `_method` если их назначение очевидно из имени.

---

## 4. Именование

### Модули

- `snake_case`: `task_intents.py`, `telegram_messages.py`.
- Короткие, описательные имена.

### Классы

- `PascalCase`: `PriceAgent`, `TaskPlanner`, `MarketplaceResilience`.
- Существительные или名词-глагол: `DatabaseManager`, `CardFiller`.

### Функции и методы

- `snake_case`: `fetch_product`, `worker_add_urls`.
- Глагол в начале: `build_draft`, `detect_marketplace`, `send_report`.

### Переменные

- `snake_case`: `price_changed`, `marketplace_name`.
- Константы: `UPPER_SNAKE_CASE`: `ADMIN_IDS`, `MAX_BATCH_SIZE`.

### Приватные атрибуты

- Префикс `_`: `_browser`, `_cache`, `_lock`.
- Не используйте `__` (dunder) без необходимости.

---

## 5. Async Patterns

### Асинхронность в проекте

Проект полностью асинхронный. Все I/O-операции должны быть async.

```python
# Правильно
async def fetch_page(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()


# Неправильно
import requests


def fetch_page(url: str) -> str:
    return requests.get(url).text
```

### Async context managers

```python
# Правильно
async with db.session() as session:
    result = await session.execute(select(Product))

# Правильно
async with playwright.async_api.async_playwright() as p:
    browser = await p.chromium.launch()
```

### Locks

```python
# Правильно — acquire в try, release в finally
lock = asyncio.Lock()
async with lock:
    await do_work()

# Или эквивалентно
await lock.acquire()
try:
    await do_work()
finally:
    lock.release()
```

### Запрещено

- `time.sleep()` в async-контексте (используйте `asyncio.sleep()`).
- `requests` (используйте `aiohttp` или `httpx`).
- Блокирующие вызовы в async-функциях.

---

## 6. Обработка ошибок

### Доменные ошибки

Определяйте специфичные ошибки в `app/core/errors.py`:

```python
class ParsingError(Exception):
    """Ошибка парсинга страницы маркетплейса."""


class BlockDetectedError(ParsingError):
    """Обнаружена блокировка антибота."""
```

### Retry с resilience

```python
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_with_retry(url: str) -> str: ...
```

### Не ловите слишком широко

```python
# Правильно
except (aiohttp.ClientError, asyncio.TimeoutError) as e:
    logger.warning("Network error: %s", e)

# Неправильно
except Exception as e:
    pass  # silently吞掉 ошибки
```

### Логирование ошибок

```python
logger.error("Failed to parse %s: %s", url, error, exc_info=True)
```

---

## 7. Логирование

### Используйте `logger` из `app/config.py`

```python
from app.config import logger

logger.info("Added %d products", count)
logger.warning("Block detected for %s", url)
logger.error("Fatal error in worker", exc_info=True)
```

### Не используйте

- `print()` в production-коде.
- `logging.basicConfig()` (уже настроено в config.py).
- Дублирование handlers.

### Уровни

- `DEBUG` — детали для разработчиков.
- `INFO` — нормальные операции.
- `WARNING` — неожиданные, но обрабатываемые ситуации.
- `ERROR` — ошибки требующие внимания.
- `CRITICAL` — фатальные ошибки.

---

## 8. Тестирование

### Структура тестов

```
tests/
├── test_database.py      # Модели БД
├── test_parsers.py        # Парсеры (mocked)
├── test_worker.py         # Worker
├── test_cli.py            # CLI entrypoint
├── test_card_filler.py    # Карточки
├── test_task_intents.py   # Intent normalization
├── test_task_planner.py   # Task planner
├── test_agent_loop.py     # Agent loop
└── test_brd_enricher.py   # BRD enrichment
```

### Правила тестов

1. Тесты не должны зависеть от сети (mock HTTP-запросы).
2. Тесты не должны зависеть от Telegram (mock bot).
3. Тесты не должны писать в production БД (используйте in-memory SQLite).
4. Имена тестов: `test_<что_тестируется>_<сценарий>`.

```python
def test_parse_ozon_html_blocked_page():
    """Блокировка Ozon распознаётся как blocked, не deleted."""
    html = load_fixture("ozon_blocked.html")
    result = parse_ozon_html(html)
    assert result["status"] == "blocked"


def test_worker_add_urls_empty_list():
    """Пустой список URL возвращает пустой результат."""
    result = await worker_add_urls(db, [], notify=None)
    assert result == []
```

### Запуск

```bash
python3 -m pytest tests/ -v
```

---

## 9. Безопасность

### Секреты

- Никогда не коммитите `.env`, токены, пароли.
- Используйте `os.getenv()` или Pydantic Settings.
- Не логируйте полные токены:

```python
# Правильно
logger.info("Using proxy: %s", mask_proxy_url(proxy))

# Неправильно
logger.info("Using proxy: %s", proxy)  # может содержать пароль
```

### Инъекции

- Экранируйте HTML в пользовательских сообщениях:

```python
safe_text = html.escape(user_input)
```

- Не используйте `eval()`, `exec()`, `__import__()`.
- Не подставляйте пользовательский ввод в SQL напрямую (используйте параметризованные запросы).

### Файловая система

- Не записывайте пользовательский ввод в произвольные пути.
- Валидируйте пути: запрещайте `..` и абсолютные пути от пользователя.
- Используйте `pathlib.Path` вместо строковых конкатенаций путей.

---

## 10. Архитектурные правила

### Контракты парсеров

- Все парсеры возвращают `ProductData` из `app/parsers/base.py`.
- Не создавайте ad-hoc словари вместо `ProductData`.
- Роутинг маркетплейсов — централизованно через `app/parsers/router.py`.

### Worker и прогресс

- Долгие операции запускайте через `worker_add_urls` / `worker_update_all`.
- Используйте `notify` callback для прогресса.
- Не блокируйте event loop.

### Telegram команды

- Каждая команда — отдельный handler с `@dp.message(Command(...))`.
- FSM state очищается после завершения.
- Не дублируйте логику между командами.

### Экспорт

- CSV: кодировка `utf-8-sig` для совместимости с Excel.
- XLSX: используйте `openpyxl`, форматируйте ячейки.
- Все экспорты возвращают `BytesIO` с установленным `.name`.

### Skillpack

- Новые reusable patterns — в `project_skills/skills_database.md` и `skills_index.json`.
- Запускайте `validate_skills.py` после изменений skillpack.
- Следуйте `SESSION_UPDATE_PROTOCOL.md` в конце сессии.

---

## 11. Git и коммиты

### Формат коммита

```
<type>(<scope>): <description>

[optional body]
```

Типы: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.

### Правила

- Один коммит = одна логическая единица изменения.
- Не коммитите сгенерированные файлы, `.env`, `__pycache__`, `.venv`.
- Обновляйте тесты вместе с кодом.

---

## 12. Контрольный список перед коммитом

- [ ] Код форматирован по PEP 8.
- [ ] Type hints добавлены для новых функций.
- [ ] Docstrings добавлены для публичных API.
- [ ] Тесты написаны и проходят (`python3 -m pytest tests/ -v`).
- [ ] Нет `print()` в production-коде.
- [ ] Нет секретов в diff.
- [ ] Skillpack обновлён (если появились reusable patterns).
- [ ] `validate_skills.py` проходит (если менялся skillpack).
