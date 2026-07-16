# P3.4 — Product Detail: Техническое задание

Дата: 2026-07-14
Статус: ПЛАН (ожидает подтверждения)

## 1. Цель

Создать центральную страницу товара, объединяющую все данные: основную информацию, Quality Score, Findings, AI Suggestions, Approval History.

## 2. Архитектура страницы

```
Product Detail (/products/{id})
├── Основные данные товара
│   ├── Название, бренд, категория
│   ├── Цена, старая цена, скидка
│   ├── Описание
│   ├── Фото
│   └── Характеристики
├── Quality Score (0-100)
│   ├── Уровень (excellent/good/fair/poor/critical)
│   └── Цветовой индикатор
├── Findings (проблемы)
│   ├── Completeness (10 правил)
│   ├── Consistency (6 правил)
│   └── Quality (4 правила)
├── AI Suggestions
│   ├── Предложения по улучшению
│   ├── Confidence
│   └── Approve/Reject
├── Approval History
│   ├── История изменений
│   └── Rollback кнопки
└── Price History
    └── График цен (Chart.js)
```

## 3. API Endpoints

| Метод | Путь | Описание |
|---|---|---|
| GET | `/products/{id}` | Страница товара (HTML) |
| GET | `/api/products/{id}` | Данные товара (JSON) |
| GET | `/api/products/{id}/prices` | История цен (JSON) |
| GET | `/api/products/{id}/analysis` | Результат анализа (JSON) |
| GET | `/api/products/{id}/suggestions` | AI предложения (JSON) |
| GET | `/api/products/{id}/history` | История одобрений (JSON) |

## 4. UI Компоненты

### 4.1 Основные данные

| Поле | Источник | Отображение |
|---|---|---|
| Название | Product.name | Заголовок |
| Бренд | UnifiedProduct.brand | Текст |
| Категория | UnifiedProduct.category | Текст |
| Цена | PriceHistory.price | Число + ₽ |
| Старая цена | UnifiedProduct.old_price | Зачёркнутое число |
| Скидка | UnifiedProduct.discount_pct | Процент |
| Описание | UnifiedProduct.description | Текст |
| Фото | Product.image_url | Изображение |
| Наличие | PriceHistory.availability_status | Бейдж |
| Маркетплейс | URL → detect | Бейдж |

### 4.2 Quality Score

| Уровень | Диапазон | Цвет |
|---|---|---|
| Excellent | 90-100 | Зелёный |
| Good | 75-89 | Синий |
| Fair | 50-74 | Жёлтый |
| Poor | 25-49 | Оранжевый |
| Critical | 0-24 | Красный |

Отображение: круговая диаграмма или полоса прогресса с числовым значением.

### 4.3 Findings

Таблица с колонками:
- Поле (field)
- Правило (rule)
- Сообщение (message)
- Серьёзность (severity): critical/warning/info
- Категория (category): completeness/consistency/quality

Цветовая кодировк�: critical=красный, warning=жёлтый, info=серый.

### 4.4 AI Suggestions

Таблица с колонками:
- Тип изменения (suggestion_type)
- Поле (field)
- Было (before)
- Предложение (after)
- Причина (reason)
- Уверенность (confidence)
- Статус (status)
- Действия (approve/reject/rollback)

### 4.5 Price History

График через Chart.js:
- X-axis: дата
- Y-axis: цена
- Точка данных: PriceHistory.price + recorded_at

## 5. Связь с существующими модулями

| Модуль | Использование |
|---|---|
| Product (database.py) | Основные данные |
| PriceHistory (database.py) | История цен |
| UnifiedProduct (schema.py) | Дополнительные поля |
| ProductAnalyzer (analyzer.py) | Quality Score + Findings |
| DatabaseApprovalQueue (db_approval.py) | AI Suggestions + History |
| ApprovalRecord (database.py) | История изменений |

## 6. Файлы для создания/изменения

### Новые:

| Файл | Описание |
|---|---|
| `app/web/routes/product_detail.py` | Router для страницы товара |
| `app/web/templates/product_detail.html` | Шаблон страницы |

### Изменённые:

| Файл | Изменение |
|---|---|
| `app/web/app.py` | Подключить product_detail router |
| `app/web/templates/products.html` | Добавить ссылки на детали |
| `app/web/schemas.py` | Добавить ProductDetailResponse |

## 7. Тесты

| Тест | Покрытие |
|---|---|
| `test_product_detail_page` | Страница открывается для существующего товара |
| `test_product_detail_api` | JSON API возвращает все данные |
| `test_product_detail_prices` | История цен отображается |
| `test_product_detail_analysis` | Quality Score + Findings отображаются |
| `test_product_detail_suggestions` | AI Suggestions отображаются |
| `test_product_detail_history` | Approval History отображается |
| `test_product_detail_404` | Несуществующий товар → 404 |

## 8. Риски

| Риск | Серьёзность | Митигация |
|---|---|---|
| Нет данных анализа для товара | Medium | Показать "Анализ не проведён" |
| Нет AI suggestions | Low | Показать "Нет предложений" |
| Нет истории цен | Low | Показать "Нет данных" |
| Производительность (много JOINов) | Low | Индексы + лимит истории |
| Chart.js CDN недоступен | Low | Fallback на текстовый вывод |

## 9. Критерии готовности

- [ ] Страница `/products/{id}` открывается
- [ ] Основные данные товара отображаются
- [ ] Quality Score отображается с цветом
- [ ] Findings отображаются в таблице
- [ ] AI Suggestions отображаются с approve/reject
- [ ] Approval History отображается
- [ ] Price History график работает
- [ ] Ссылка "Подробнее" на странице товаров работает
- [ ] 404 для несуществующего товара
- [ ] Все тесты проходят
