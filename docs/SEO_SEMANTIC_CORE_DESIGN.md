# Semantic Core — Семантическое ядро для SEO-анализа карточек товаров

**Версия**: 1.0
**Дата**: 2026-07-20
**Статус**: Дизайн

---

## 1. Описание проблемы

### Текущее состояние SEO-аудита

Модуль `app/seo_intelligence.py` выполняет детерминированный аудит карточек товаров. Проверки охватывают:

- Длину названия (25–140 символов)
- Длину описания (минимум 350 символов)
- Количество ключевых слов (минимум 6)
- Количество атрибутов (минимум 4)
- Количество изображений (минимум 3)
- Наличие запрещённых маркетинговых слов
- Покрытие ключевых слов конкурентов

Все проверки работают на уровне **структуры**: длина, количество, наличие/отсутствие.

### Чего не хватает

1. **Нет понятия "семантическое ядро товара"**. Ключевые слова хранятся как плоский список (`tags: list[str]`), без классификации по роли в поисковом запросе.

2. **Ключевые слова берутся как есть**. Нет различия между основным ключом ("магний в таблетках"), дополнительным ("минеральная добавка"), хвостовым ("магний цитрат 200 мг 60 капсул") и мусорным ("купить дешево акция").

3. **SEO-скор не отражает семантическую глубину**. Товар с 20 мусорными ключами получает тот же бонус за количество, что и товар с 6 релевантными.

4. **Нет данных для умных рекомендаций**. Рекомендации системы generic: "добавьте ключевые слова", "уберите запрещённые слова". Нет возможности сказать: "ваш основной ключ 'магний' покрыт, но хвостовой 'цитрат 200 мг' отсутствует — добавьте его".

### Цель модуля

Ввести понятие **SemanticCore** — структурированное семантическое ядро товара, которое:

- Классифицирует каждый ключ по роли
- Вычисляет семантические метрики
- Питает более точные рекомендации
- Сохраняется в snapshot карточки без отдельной таблицы БД

---

## 2. Архитектура решения

### 2.1 Датакласс SemanticCore

```python
@dataclass(frozen=True)
class SemanticCore:
    """Семантическое ядро товара — классифицированные ключевые слова."""

    product_id: int | str

    primary_keys: list[str]          # 1–3 ключа: точное попадание в товар
    secondary_keys: list[str]        # 4–10 ключей: смежные запросы
    long_tail_keys: list[str]        # 11+ ключей: длинные специфичные запросы
    brand_keys: list[str]            # ключи с упоминанием бренда
    junk_keys: list[str]             # мусорные/спамные ключи
    category_keys: list[str]         # ключи, связанные с категорией товара

    competitor_overlap: list[str]    # ключи, совпадающие с конкурентами
    missing_competitor_keys: list[str]  # ключи конкурентов, которых нет у товара

    keyword_coverage: float = 0.0    # покрытие целевых ключей (0.0–1.0)
    semantic_depth: float = 0.0      # доля хвостовых ключей (0.0–1.0)
    junk_ratio: float = 0.0          # доля мусорных ключей (0.0–1.0)
    semantic_score: float = 0.0      # итоговая оценка (0.0–1.0)

    @property
    def all_product_keys(self) -> list[str]:
        """Все ключи товара (без мусорных)."""
        return self.primary_keys + self.secondary_keys + self.long_tail_keys + self.brand_keys + self.category_keys

    @property
    def total_keys(self) -> int:
        return len(self.all_product_keys) + len(self.junk_keys)

    @property
    def effective_keys(self) -> list[str]:
        """Ключи, пригодные для использования (без мусора)."""
        return self.all_product_keys
```

### 2.2 Источники данных для построения ядра

| Источник | Поле UnifiedProduct | Что извлекается |
|---|---|---|
| Название товара | `name` | Основные ключи, тип товара, бренд |
| Описание | `description` | Дополнительные ключи, сценарии использования |
| Атрибуты | `attributes` | Характеристики, технические термины |
| Категория | `category` | Категорийные ключи |
| Теги | `tags` | Уже размеченные ключи |
| Конкуренты | `competitor_terms` (внешний параметр) | Частые термины конкурентов |

### 2.3 Классификатор ключей

Классификация основана на длине, позиции и семантических характеристиках ключевого слова:

| Класс | Определение | Примеры |
|---|---|---|
| **Primary** (1–3) | Точное попадание в суть товара; совпадают с типом + главной характеристикой | "магний в таблетках", "кабель USB-C", "книга Пушкин" |
| **Secondary** (4–10) | Смежные запросы, раскрывающие товар шире | "минеральная добавка", "зарядное устройство USB", "собрание сочинений" |
| **Long-tail** (11+) | Длинные специфичные запросы, низкочастотные | "магний цитрат 200 мг 60 капсул", "USB-C кабель 2 м быстрая зарядка" |
| **Brand** | Содержат имя бренда | "Nature Made магний", "Xiaomi кабель" |
| **Category** | Связаны с родительской категорией, но не описывают товар напрямую | "витамины", "кабели и провода", "книги" |
| **Junk** | Спамные, запрещённые, не несущие информации | "купить дешево", "скидка акция", "лучший топ" |

### 2.4 Алгоритм классификации

```python
def classify_keys(
    tokens: list[str],
    title_tokens: list[str],
    brand: str,
    category: str | None,
    competitor_terms: list[str],
) -> SemanticCore:
    """
    Алгоритм ( детерминированный, без ML ):

    1. Нормализовать все токены (lowercase, удалить стоп-слова)
    2. Пометить как junk: токены из FORBIDDEN_MARKETING_WORDS
       и GENERIC_PRODUCT_TYPES, а также токены < 3 символов
    3. Пометить как brand: токены, содержащие brand (если бренд не "Нет бренда")
    4. Пометить как category: токены, совпадающие с корнем категории
    5. Среди оставшихся:
       - primary: токены, совпадающие с title_tokens (первые 3 по частоте)
       - secondary: токены с частотой 2+ или из атрибутов (позиции 4–10)
       - long_tail: составные фразы из 3+ слов
       - остальные secondary
    6. Вычислить competitor_overlap и missing_competitor_keys
    """
```

### 2.5 Функция построения

```python
def build_semantic_core(
    product: UnifiedProduct,
    competitor_terms: list[str] | None = None,
) -> SemanticCore:
    """Строит семантическое ядро для товара."""
```

**Вход**: `UnifiedProduct` + опциональный список терминов конкурентов.
**Выход**: `SemanticCore` с заполненными полями и вычисленными метриками.

Логика:
1. Собрать все текстовые данные: `name`, `description`, `attributes.values()`, `category`, `tags`
2. Токенизировать через `_tokens()` из `seo_intelligence.py`
3. Подсчитать частоту каждого токена
4. Классифицировать по правилам из п. 2.4
5. Вычислить метрики (п. 4)
6. Сопоставить с `competitor_terms`

---

## 3. Интеграция с существующей системой

### 3.1 Точка входа: audit_unified_product_seo

Текущая функция `audit_unified_product_seo()` в `seo_intelligence.py` выглядит так:

```python
def audit_unified_product_seo(
    product: UnifiedProduct,
    *,
    competitor_terms: list[str] | None = None,
) -> SEOAuditResult:
    ...
    findings.extend(_check_snapshot_keywords(product.tags, product.name or "", competitor_terms))
    ...
```

**Изменения**:

1. Внутри `audit_unified_product_seo` вызывать `build_semantic_core(product, competitor_terms)`
2. Передавать `SemanticCore` в расширенные проверки ключевых слов
3. Добавлять findings на основе семантических метрик:

```python
def _check_semantic_core(core: SemanticCore) -> list[SEOFinding]:
    findings = []
    if core.junk_ratio > 0.15:
        findings.append(SEOFinding(
            rule="seo_junk_keys_high",
            field="keywords",
            severity="warning",
            message=f"Более 15% ключей — мусорные ({len(core.junk_keys)} из {core.total_keys}).",
        ))
    if core.semantic_depth < 0.2 and core.total_keys > 6:
        findings.append(SEOFinding(
            rule="seo_long_tail_few",
            field="keywords",
            severity="info",
            message="Мало хвостовых ключей. Добавьте специфичные составные запросы.",
        ))
    if core.keyword_coverage < 0.5:
        findings.append(SEOFinding(
            rule="seo_keyword_coverage_low",
            field="keywords",
            severity="warning",
            message=f"Покрытие целевых ключей: {core.keyword_coverage:.0%}.",
        ))
    if core.missing_competitor_keys:
        findings.append(SEOFinding(
            rule="seo_competitor_keys_missing",
            field="keywords",
            severity="info",
            message="Ключи конкурентов отсутствуют: " + ", ".join(core.missing_competitor_keys[:5]),
        ))
    return findings
```

### 3.2 Влияние на рекомендации

SemanticCore позволяет формировать **конкретные** рекомендации:

| finding.rule | Рекомендация на основе SemanticCore |
|---|---|
| `seo_junk_keys_high` | "Удалите мусорные ключи: {junk_keys}" |
| `seo_long_tail_few` | "Добавьте хвостовые ключи на основе: {primary_keys} + {category}" |
| `seo_keyword_coverage_low` | "Отсутствуют ключи: {missing_competitor_keys}" |
| `seo_competitor_keys_missing` | "Конкуренты используют: {missing_competitor_keys}" |

### 3.3 Хранение

SemanticCore **не сохраняется** отдельно в БД. Он:

- Вычисляется on-the-fly при вызове `audit_unified_product_seo()`
- Сериализуется в `effective_snapshot` как поле `_semantic_core` (с префиксом `_`, чтобы фильтроваться через `_without_internal_fields()`)
- Доступен через `seo()` и `seo_suggestions()` в `EffectiveProductCardService`

```python
# В audit_unified_product_seo:
core = build_semantic_core(product, competitor_terms)
findings.extend(_check_semantic_core(core))

# Возврат расширенного результата:
result.semantic_core = core  # для snapshot
```

### 3.4 Расширение SEOAuditResult

```python
@dataclass
class SEOAuditResult:
    score: int
    tier: str
    findings: list[SEOFinding] = field(default_factory=list)
    recommendations: list[SEORecommendation] = field(default_factory=list)
    semantic_core: SemanticCore | None = None  # НОВОЕ

    @property
    def ready(self) -> bool:
        return self.score >= 75 and not any(item.severity == "critical" for item in self.findings)
```

---

## 4. Формулы

### 4.1 keyword_coverage

```python
target_keyword_count = max(len(competitor_terms), MIN_KEYWORDS)  # MIN_KEYWORDS = 6
keyword_coverage = len(primary_keys + secondary_keys) / target_keyword_count
keyword_coverage = min(1.0, keyword_coverage)
```

Покрытие основных и дополнительных ключей относительно целевого количества (определяется конкурентами или порогом MIN_KEYWORDS).

### 4.2 semantic_depth

```python
total_keys = len(primary_keys + secondary_keys + long_tail_keys + brand_keys + category_keys) + len(junk_keys)
semantic_depth = len(long_tail_keys) / max(total_keys, 1)
```

Доля хвостовых (длинных, специфичных) ключей в общем объёме. Высокая глубина = карточка покрывает низкочастотные запросы.

### 4.3 junk_ratio

```python
junk_ratio = len(junk_keys) / max(total_keys, 1)
```

Доля мусорных ключей. Высокая доля = карточка содержит спам, что снижает доверие маркетплейса.

### 4.4 semantic_score

```python
def _compute_semantic_score(
    keyword_coverage: float,
    semantic_depth: float,
    junk_ratio: float,
) -> float:
    """
    Итоговая оценка семантического ядра (0.0–1.0).

    - keyword_coverage: вес 0.5 (основной фактор)
    - semantic_depth: вес 0.3 (бонус за хвостовые ключи)
    - junk_ratio: вес 0.2 (штраф за мусор)

    Формула:
    score = 0.5 * coverage + 0.3 * depth - 0.2 * junk_ratio
    score = clamp(score, 0.0, 1.0)
    """
    raw = 0.5 * keyword_coverage + 0.3 * semantic_depth - 0.2 * junk_ratio
    return max(0.0, min(1.0, raw))
```

### 4.5 Влияние на общий SEO-скор

SemanticCore score **не заменяет** текущий `_score()`, а **дополняет** его:

```python
# В audit_unified_product_seo:
base_score = _score(findings)
semantic_adjustment = 0

if core is not None:
    # Бонус за высокое семантическое ядро
    if core.semantic_score >= 0.7:
        semantic_adjustment += 5
    # Штраф за мусор
    if core.junk_ratio > 0.2:
        semantic_adjustment -= 10

final_score = max(0, min(100, base_score + semantic_adjustment))
```

---

## 5. Тестовые кейсы

### 5.1 Товар с чистым семантическим ядром (высокий score)

**Вход**:
```python
UnifiedProduct(
    name="Магний цитрат в таблетках 200 мг 60 капсул",
    source_id="1",
    source_type="wb",
    description="Магний цитрат — легкоусвояемая форма минерала. 200 мг elemental magnesium в каждой капсуле. Подходит для ежедневного приёма.",
    category="Красота и здоровье/Витамины и БАДы/Минералы",
    brand="Nature Made",
    tags=["магний", "цитрат", "таблетки", "минерал", "добавка", "капсулы", "200 мг", "60 шт"],
)
```

**Ожидаемый SemanticCore**:
- `primary_keys`: ["магний", "цитрат", "таблетки"]
- `secondary_keys`: ["минерал", "добавка", "капсулы"]
- `long_tail_keys`: ["магний цитрат 200 мг", "60 капсул"]
- `brand_keys`: ["nature made"]
- `junk_keys`: []
- `keyword_coverage`: 1.0
- `semantic_depth`: >= 0.2
- `junk_ratio`: 0.0
- `semantic_score`: >= 0.6

**Ожидаемый SEO-скор**: >= 80 (strong)

### 5.2 Товар с мусорными ключами (низкий score)

**Вход**:
```python
UnifiedProduct(
    name="Кабель USB-C",
    source_id="2",
    source_type="ozon",
    description="Кабель",
    tags=["купить", "дешево", "скидка", "акция", "топ", "лучший", "недорого", "кабель"],
)
```

**Ожидаемый SemanticCore**:
- `primary_keys`: ["кабель"]
- `secondary_keys`: []
- `long_tail_keys`: []
- `brand_keys`: []
- `junk_keys`: ["купить", "дешево", "скидка", "акция", "топ", "лучший", "недорого"]
- `keyword_coverage`: < 0.5
- `junk_ratio`: > 0.5
- `semantic_score`: < 0.2

**Ожидаемый SEO-скор**: < 50 (weak), findings включают `seo_junk_keys_high`

### 5.3 Товар без ключевых слов (нулевой score)

**Вход**:
```python
UnifiedProduct(
    name="Товар",
    source_id="3",
    source_type="csv",
    tags=[],
)
```

**Ожидаемый SemanticCore**:
- `primary_keys`: []
- `secondary_keys`: []
- `total_keys`: 0
- `keyword_coverage`: 0.0
- `semantic_depth`: 0.0
- `junk_ratio`: 0.0
- `semantic_score`: 0.0

**Ожидаемый SEO-скор**: < 50, findings включают `seo_keywords_few` и `seo_keyword_coverage_low`

### 5.4 Товар с конкурентными терминами (бонус к score)

**Вход**:
```python
product = UnifiedProduct(
    name="Магний в таблетках",
    source_id="4",
    source_type="ozon",
    tags=["магний", "таблетки", "минерал"],
    category="Витамины",
)
competitor_terms = ["магний", "цитрат", "минерал", "добавка", "капсулы", "200 мг", "B6"]
```

**Ожидаемый SemanticCore**:
- `primary_keys`: ["магний", "таблетки"]
- `secondary_keys`: ["минерал"]
- `competitor_overlap`: ["магний", "минерал"]
- `missing_competitor_keys`: ["цитрат", "добавка", "капсулы", "200 мг", "b6"]
- `keyword_coverage`: 2/7 ≈ 0.29

**Ожидаемый результат**: finding `seo_competitor_keys_missing` с конкретным списком недостающих ключей. Рекомендация: "Добавьте ключи конкурентов: цитрат, добавка, капсулы, 200 мг, B6".

---

## 6. Файлы для реализации

### 6.1 app/semantic_core.py (новый модуль)

Содержимое:
- `SemanticCore` (датакласс)
- `build_semantic_core(product, competitor_terms)` — основная функция
- `_classify_keys(...)` — внутренняя классификация
- `_compute_semantic_score(...)` — вычисление score
- `_tokens_from_product(product)` — извлечение токенов из UnifiedProduct

Зависимости:
- `app.products.schema UnifiedProduct`
- `app.seo_intelligence._tokens`, `_normalize_terms`, `FORBIDDEN_MARKETING_WORDS`, `GENERIC_PRODUCT_TYPES`

### 6.2 app/seo_intelligence.py (интеграция)

Изменения:
- Импорт `build_semantic_core` из `app.semantic_core`
- Расширение `SEOAuditResult` полем `semantic_core: SemanticCore | None`
- Добавление `_check_semantic_core(core)` — новые findings
- Вызов `build_semantic_core()` внутри `audit_unified_product_seo()`
- Обновление `_recommend()` для генерации конкретных рекомендаций на основе SemanticCore

### 6.3 tests/test_semantic_core.py (тесты)

Тестовые сценарии:
- `test_clean_semantic_core` — товар с чистыми ключами
- `test_junk_keys_penalized` — мусорные ключи снижают score
- `test_empty_keys_zero_score` — пустые ключи = нулевой score
- `test_competitor_bonus` — конкурентные термины дают рекомендации
- `test_brand_keys_classified` — брендовые ключи в отдельной категории
- `test_category_keys_classified` — категорийные ключи отдельно
- `test_long_tail_detection` — составные фразы распознаются как хвостовые
- `test_semantic_core_in_audit` — интеграция с `audit_unified_product_seo`

---

## 7. Порядок реализации

1. Создать `app/semantic_core.py` с датаклассом и `build_semantic_core()`
2. Написать `tests/test_semantic_core.py` — unit-тесты на изолированную логику
3. Интегрировать в `app/seo_intelligence.py` — расширить `SEOAuditResult`, добавить `_check_semantic_core()`
4. Обновить `app/effective_card/service.py` — пробросить `semantic_core` в snapshot
5. Запустить полный набор тестов: `.venv/bin/python -m pytest -q`
