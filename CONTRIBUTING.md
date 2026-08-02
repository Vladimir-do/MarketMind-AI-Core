# Вклад в MarketMind AI

## Настройка окружения разработки

```bash
# Клонируем репозиторий
git clone https://github.com/your-org/MarketMind-AI-Core.git
cd MarketMind-AI-Core

# Создаём виртуальное окружение
python3.11 -m venv .venv
source .venv/bin/activate

# Устанавливаем зависимости
pip install -r requirements.txt

# Устанавливаем dev-зависимости
pip install ruff mypy pytest pytest-asyncio

# Копируем .env
cp .env.example .env
# Заполните .env реальными значениями

# Устанавливаем Playwright
playwright install chromium
playwright install-deps chromium

# Запускаем бота
python -m app.main --telegram
```

## Код-стайл

- **Python 3.11+** — используйте modern-синтаксис (match/case, type hints, walrus operator где уместно).
- **Ruff** — линтер и форматтер. Запускайте перед коммитом:
  ```bash
  ruff check .          # проверка
  ruff format .         # форматирование
  ```
- **Типизация** — добавляйте type hints к публичным функциям. `mypy` настроен в `pyproject.toml`.
- **Именование** — `snake_case` для переменных и функций, `PascalCase` для классов, `UPPER_SNAKE_CASE` для констант.
- **Импорты** — группируются в порядке: stdlib → third-party → `app.*`. Ruff сортирует автоматически.

## Тестирование

```bash
# Все тесты
pytest tests/ -v

# Только быстрые
pytest tests/ -v -m "not slow"

# С покрытием
pytest tests/ --cov=app --cov-report=term-missing
```

- Пишите тесты для нового кода. Минимум — unit-тесты для бизнес-логики.
- Интеграционные тесты для парсеров помечайте `@pytest.mark.slow`.
- Тесты должны быть детерминированными — мокайте внешние вызовы (HTTP, Telegram API, Playwright).

## Формат коммитов

Используйте [Conventional Commits](https://www.conventionalcommits.org/):

```
<тип>: <описание>

[необязательное тело]

[необязательный футер]
```

Типы:
- `feat` — новая функциональность
- `fix` — исправление бага
- `docs` — документация
- `style` — форматирование (без изменения логики)
- `refactor` — рефакторинг (без изменения поведения)
- `test` — добавление/обновление тестов
- `chore` — сборка, зависимости, CI

Примеры:
```
feat: добавить экспорт в PDF для Telegram
fix: исправить парсинг цен Ozon при отсутствии скидки
docs: обновить ROADMAP.md — добавить фазу 3
```

## Процесс Pull Request

1. Создайте ветку из `develop`: `git checkout -b feat/my-feature develop`
2. Внесите изменения, напишите тесты
3. Запустите проверки: `ruff check . && pytest tests/ -v`
4. Закоммитьте с описательным сообщением
5. Откройте PR в `develop` с описанием:
   - **Что** сделано и **зачем**
   - Как тестировать
   - Скриншоты (если есть UI-изменения)
6. Дождитесь ревью и CI-проверок
7. После одобрения — squash-merge в `develop`

## Архитектурные решения

- Если планируете крупное изменение — обсудите в issue перед началом работы.
- Следуйте принципам из `ARCHITECTURE_NEXT.md`.
- Не привязывайтесь к конкретным библиотекам без веской причины.
- Предпочитайте async/await для всех I/O-операций.

## Контрибьюция без кода

- Сообщайте о багах через Issues с деталями: шаги воспроизведения, ожидаемое/фактическое поведение, логи.
- Улучшайте документацию.
- Делитесь.feedback по UX бота.
