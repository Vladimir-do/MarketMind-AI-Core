# Модуль Competitor Intelligence для SEO

## 1. Проблема

### Текущее состояние

Функция `extract_competitor_terms` в `app/seo_intelligence.py:130-140` выполняет минимальный анализ конкурентов:

- Подсчитывает частоту слов в названиях конкурентов
- Фильтрует общие слова и маркетинговые термины
- Возвращает до 20 наиболее частых слов

### Что не хватает

**Нет анализа структуры title конкурентов.** Текущая функция не учитывает, как конкуренты структурируют названия: какой порядок элементов (тип → бренд → свойства), какие шаблоны используются, какова средняя длина.

**Нет сравнения атрибутов.** Мы не знаем, какие характеристики конкуренты указывают обязательными, а какие мы пропускаем. Разрывы в атрибутах влияют на видимость в фильтрах маркетплейса.

**Нет оценки УТП (уникальное торговое предложение).** Мы не можем определить, какие термины уникальны для нашего товара и какие термины являются общими для рынка. Это мешает формировать правильные рекомендации по SEO.

**Нет анализа ценовой позиции.** Мы не позиционируем товар относительно рынка — дешевле, дороже или на уровне медианы.

**Нет анализ структуры карточек.** Мы не учитываем количество фото, наличие бренда, наличие категории у конкурентов — всё это влияет на качество SEO-рекомендаций.

---

## 2. Архитектура модуля

### 2.1 Датаклассы

```python
@dataclass(frozen=True)
class CompetitorProfile:
    """Профиль одного конкурента."""
    name: str
    title_words: list[str]          # токены из названия
    attribute_keys: list[str]       # ключи атрибутов/характеристик
    price_range: str                # "budget" | "mid" | "premium" | "unknown"
    image_count: int
    has_brand: bool
    has_category: bool

@dataclass(frozen=True)
class CompetitorAnalysis:
    """Агрегированный анализ всех конкурентов."""
    profiles: list[CompetitorProfile]
    top_words: list[tuple[str, int]]          # (слово, частота)
    common_attributes: list[str]              # атрибуты, которые есть у 2+ конкурентов
    price_distribution: dict[str, int]        # {"budget": 3, "mid": 5, "premium": 2}
    unique_terms: list[str]                   # термины, уникальные для одного конкурента
    shared_terms: list[str]                   # термины, которые есть у 2+ конкурентов
    average_title_length: float
    median_price: int | None
```

### 2.2 Функции

```python
def analyze_competitors(competitors: list[dict]) -> CompetitorAnalysis:
    """
    Анализирует список конкурентов и возвращает агрегированный профиль рынка.

    Вход: список словарей с ключами name, price, url, attributes (опционально)
    Выход: CompetitorAnalysis с агрегированными метриками
    """

def compare_with_competitors(
    product: UnifiedProduct,
    analysis: CompetitorAnalysis,
) -> CompetitorComparison:
    """
    Сравнивает единичный товар с агрегированным анализом конкурентов.

    Вход: UnifiedProduct + CompetitorAnalysis
    Выход: CompetitorComparison с конкретными gaps и позицией
    """
```

---

## 3. CompetitorComparison

```python
@dataclass(frozen=True)
class CompetitorComparison:
    """Результат сравнения товара с конкурентами."""

    missing_terms: list[str]
    # Термины, которые есть у конкурентов, но нет в нашем title/keywords/описании.
    # Приоритет: термины с частотой >= 2 конкурентов.

    unique_terms: list[str]
    # Наши уникальные термины — то, чего нет у конкурентов.
    # Потенциальное УТП для выделения.

    price_position: str
    # "cheaper" — наша цена ниже медианы рынка на 15%+
    # "average" — в пределах ±15% от медианы
    # "premium" — наша цена выше медианы на 15%+
    # "unknown" — нет данных о цене товара или конкурентов

    attribute_gaps: list[str]
    # Атрибуты, которые есть у конкурентов (у 2+), но нет у нас.
    # Пример: ["Материал", "Тип разъёма", "Страна производства"]

    title_structure_score: float
    # 0.0–1.0: насколько наш title соответствует структуре конкурентных.
    # Считается по совпадению позиций токенов (тип товара в начале, бренд, свойства).
```

---

## 4. Интеграция с существующей системой

### 4.1 Новые finding-ы в SEO-аудите

Модуль `seo_intelligence.py` получает три новых типа finding:

| finding rule | severity | поле | описание |
|---|---|---|---|
| `seo_competitor_price_gap` | info | price | Товар значительно дешевле/дороже рынка. Рекомендация: проверить обоснованность цены. |
| `seo_competitor_attribute_gap` | warning | attributes | Отсутствуют атрибуты, которые есть у конкурентов. Рекомендация: заполнить недостающие характеристики. |
| `seo_competitor_title_gap` | info | name | Title не соответствует структуре конкурентных названий. Рекомендация: адаптировать формат. |

### 4.2 Изменения в `seo_suggestions()`

Текущая функция `audit_unified_product_seo` принимает `competitor_terms: list[str]`. Новая версия будет принимать `CompetitorComparison` вместо сырого списка терминов.

```python
def audit_unified_product_seo(
    product: UnifiedProduct,
    *,
    competitor_comparison: CompetitorComparison | None = None,
    rules: SEOMarketplaceRule | None = None,
) -> SEOAuditResult:
```

Внутри функции comparison используется для:
- Генерации finding `seo_competitor_price_gap` на основе `price_position`
- Генерации finding `seo_competitor_attribute_gap` на основе `attribute_gaps`
- Генерации finding `seo_competitor_title_gap` на основе `title_structure_score`
- Добавления `missing_terms` в existing `seo_keywords_competitor_gap` finding

### 4.3 Точка вызова

`compare_with_competitors` вызывается в `card_research.py` или на уровне UI перед аудитом. Результат `CompetitorComparison` передаётся в `audit_unified_product_seo`.

---

## 5. Логика сравнения

### 5.1 Определение позиции по цене

```
median_price = медиана цен конкурентов
наша_цена = product.price

если наша_цена None → "unknown"
если наша_цена < median_price * 0.85 → "cheaper"
если наша_цена > median_price * 1.15 → "premium"
иначе → "average"
```

### 5.2 Определение attribute_gaps

```
common_attrs = атрибуты, которые есть у >= 2 конкурентов
наши_attrs = product.attributes.keys()

gaps = common_attrs - наши_attrs
```

### 5.3 Определение title_structure_score

```
Если наш title пустой → 0.0

Для каждого конкурента:
  1. Извлекаем тип товара (первое слово/ phrase)
  2. Извлекаем бренд (второе слово, если есть)
  3. Считаем количество свойств

Среднее совпадение позиций → score от 0.0 до 1.0
```

### 5.4 Определение missing_terms и unique_terms

```
наши_токены = токены из product.name + product.tags + product.attributes.values()
токены_конкурентов = объединение токенов всех конкурентов (с весом по частоте)

missing = токены конкурентов с частотой >= 2, которых нет в наших_токенах
unique = наши_токены, которых нет в топ-токенах конкурентов
```

---

## 6. Тестовые кейсы

### 6.1 Три конкурента с похожими title

Вход:
```python
competitors = [
    {"name": "Кабель USB-C Type-C 2м зарядка данных", "price": 299},
    {"name": "Кабель USB Type-C для зарядки 1.5м", "price": 249},
    {"name": "Провод USB-C 2 метра быстрая зарядка", "price": 349},
]
product = UnifiedProduct(
    name="Кабель USB-C 2м",
    price=279,
    tags=["usb-c", "кабель"],
    attributes={"Длина": "2 м", "Тип": "USB-C"},
)
```

Ожидаемый результат:
- `top_words`: [("кабель", 3), ("usb", 3), ("зарядк", 3), ("type-c", 2), ("метра", 2)]
- `shared_terms`: ["кабель", "usb", "зарядк"]
- `missing_terms`: ["данных", "провод"] (если частота >= 2)
- `price_position`: "average" (279 в диапазоне 249–349, медиана ~299)
- `attribute_gaps`: ["Тип разъёма"] (если конкуренты указывают, а мы нет)
- `title_structure_score`: > 0.7 (структура "Тип + Свойства + Бренд" совпадает)

### 6.2 Конкуренты с разными атрибутами

Вход:
```python
competitors = [
    {"name": "Наушники TWS Bluetooth 5.3", "price": 1990,
     "attributes": {"Материал": "Пластик", "Вес": "45 г", "Время работы": "6 ч"}},
    {"name": "Наушники беспроводные TWS", "price": 1490,
     "attributes": {"Цвет": "чёрный", "Вес": "50 г", "Зарядный кейс": "есть"}},
    {"name": "TWS Наушники Bluetooth", "price": 2490,
     "attributes": {"Материал": "Пластик", "Водозащита": "IPX4", "Вес": "42 г"}},
]
product = UnifiedProduct(
    name="Наушники TWS Bluetooth",
    price=1690,
    attributes={"Цвет": "чёрный", "Вес": "48 г"},
)
```

Ожидаемый результат:
- `common_attributes`: ["Материал", "Вес"] (есть у 2+ конкурентов)
- `attribute_gaps`: ["Материал", "Время работы", "Зарядный кейс"] (наши: ["Цвет", "Вес"])
- `unique_terms`: ["bluetooth"] (если конкуренты используют "tws" без bluetooth)

### 6.3 Конкуренты с разным price range

Вход:
```python
competitors = [
    {"name": "Витамин D3 2000 МЕ 60 капсул", "price": 390},
    {"name": "Витамин D3 5000 МЕ 120 капсул", "price": 890},
    {"name": "Витамин D3 1000 МЕ 30 таблеток", "price": 190},
    {"name": "D3 витамин капли 10 мл", "price": 550},
]
product = UnifiedProduct(
    name="Витамин D3 2000 МЕ",
    price=450,
    attributes={"Форма": "капсулы", "Дозировка": "2000 МЕ"},
)
```

Ожидаемый результат:
- `price_distribution`: {"budget": 1, "mid": 2, "premium": 1} (границы: <300 / 300–600 / >600)
- `median_price`: 470
- `price_position`: "average" (450 в пределах ±15% от 470)

### 6.4 Один конкурент с пустыми данными

Вход:
```python
competitors = [
    {"name": "", "price": None},
    {"name": "Набор инструментов 100 предметов", "price": 2990},
]
product = UnifiedProduct(
    name="Набор инструментов",
    price=1500,
)
```

Ожидаемый результат:
- Пустой конкурент игнорируется при расчёте метрик
- `profiles` содержит 1 профиль (только валидный)
- `median_price`: 2990
- `price_position`: "cheaper" (1500 < 2990 * 0.85)

---

## 7. Файлы для реализации

### 7.1 `app/competitor_intelligence.py` (новый файл)

Содержит:
- `CompetitorProfile` — датакласс профиля конкурента
- `CompetitorAnalysis` — датакласс агрегированного анализа
- `CompetitorComparison` — датакласс результата сравнения
- `analyze_competitors(competitors: list[dict]) -> CompetitorAnalysis`
- `compare_with_competitors(product: UnifiedProduct, analysis: CompetitorAnalysis) -> CompetitorComparison`
- Вспомогательные функции: `_build_profile`, `_classify_price`, `_extract_title_structure`, `_compute_structure_score`

### 7.2 `app/seo_intelligence.py` (модификация)

Изменения:
- Импорт `CompetitorComparison` и `CompetitorAnalysis` из `app.competitor_intelligence`
- Новые функции `_check_competitor_price_gap`, `_check_competitor_attribute_gap`, `_check_competitor_title_gap`
- Обновлённая сигнатура `audit_unified_product_seo` — принимает `competitor_comparison: CompetitorComparison | None`
- Обновлённый `_recommend` — новые действия для трёх новых finding

### 7.3 `tests/test_competitor_intelligence.py` (новый файл)

Тесты:
- `test_analyze_competitors_basic` — базовый анализ 3 конкурентов
- `test_analyze_competitors_empty` — пустой список конкурентов
- `test_analyze_competitors_partial_data` — конкуренты с неполными данными
- `test_compare_price_cheaper` — товар дешевле рынка
- `test_compare_price_average` — товар на уровне рынка
- `test_compare_price_premium` — товар дороже рынка
- `test_compare_price_unknown` — нет цены у товара
- `test_compare_attribute_gaps` — недостающие атрибуты
- `test_compare_title_structure` — оценка структуры title
- `test_compare_missing_terms` — недостающие термины
- `test_compare_unique_terms` — уникальные термины
- `test_integration_seo_audit` — интеграция с `audit_unified_product_seo`

---

## 8. Зависимости

- `app/products/schema.py` — `UnifiedProduct` (входные данные)
- `app/seo_intelligence.py` — расширение существующего аудита
- Стандартная библиотека: `statistics.median`, `re`, `dataclasses`

Новых внешних зависимостей нет.
