# P1.3 Report — Universal Data Import Layer

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Цель P1.3

Создать независимый слой импорта данных, который НЕ зависит от Ozon или Wildberries. Любой источник данных (CSV, Excel, PDF, изображения, ссылки, ручной ввод) приводится к единой модели товара.

## Почему отказались от парсероцентричной архитектуры

Ранее система была завязана на парсеры маркетплейсов:
- CSV/XLSX → batch_enricher → текст → OzonCardDraft (только Ozon)
- URL → парсер → ProductData (только marketplace)

Это ограничивало систему:
- Нельзя импортировать произвольные данные
- Нет единой модели товара
- Новые источники требовали изменения ядра

## Новая архитектура импорта

```
Любой источник → Importer → UnifiedProduct → Bridge → Существующие системы
```

### Источники данных
- CSV/Excel (через импортёры)
- PDF (будущее)
- Изображения (будущее)
- Ссылки (парсеры маркетплейсов — опционально)
- Ручной ввод (Telegram)
- API маркетплейсов (будущее)

### Архитектурные слои

| Слой | Модуль | Роль |
|---|---|---|
| Schema | `app/products/schema.py` | UnifiedProduct — единая модель товара |
| Base | `app/importers/base.py` | BaseImporter ABC — контракт для всех импортёров |
| Importers | `app/importers/csv_importer.py`, `excel_importer.py` | Конкретные реализации |
| Registry | `app/importers/registry.py` | Маршрутизация по типу файла |
| Bridge | `app/adapters/product_bridge.py` | Конвертация между схемами |
| Parsers | `app/parsers/` | Marketplace-specific (вторичный источник) |

## Единая модель данных

`UnifiedProduct` — source-agnostic dataclass:

| Поле | Тип | Описание |
|---|---|---|
| name | str | Название товара (обязательно) |
| source_id | str | Уникальный ID в источнике (обязательно) |
| source_type | str | Тип источника (обязательно) |
| description | str | Описание |
| brand | str | Бренд |
| category | str | Категория |
| sku | str | Артикул |
| price | int\|None | Цена |
| old_price | int\|None | Старая цена |
| weight_g, width_mm, height_mm, depth_mm | int\|None | Физические атрибуты |
| image_urls | list[str] | Фото |
| attributes | dict[str,str] | Произвольные атрибуты |
| raw | dict[str,Any] | Оригинальные данные (escape hatch) |

## Созданные компоненты

| Файл | Роль |
|---|---|
| `app/products/__init__.py` | Package |
| `app/products/schema.py` | UnifiedProduct dataclass |
| `app/importers/__init__.py` | Re-exports |
| `app/importers/base.py` | BaseImporter ABC, ImportResult, ImportRowError, DEFAULT_FIELD_MAPPING |
| `app/importers/csv_importer.py` | CsvImporter — чтение CSV |
| `app/importers/excel_importer.py` | ExcelImporter — чтение XLSX |
| `app/importers/registry.py` | import_file(), import_string() |
| `app/adapters/__init__.py` | Package |
| `app/adapters/product_bridge.py` | unified_to_product_data(), unified_to_card_task() |
| `tests/test_importers.py` | 11 тестов |

## Изменённые файлы

Нет — только новые файлы. Существующий код не затронут.

## Тестирование

```
289 passed, 24 warnings, 0 failed
```

- 278 существующих тестов — все проходят
- 11 новых тестов — все проходят
- 0 regressions

### Новые тесты
- test_csvImporter_can_handle
- test_csvImporter_validate_missing_file
- test_csvImporter_extract_basic_csv
- test_csvImporter_extract_russian_headers
- test_csvImporter_normalize_to_unified
- test_csvImporter_import_data_full_pipeline
- test_excelImporter_can_handle
- test_registry_routes_to_csv
- test_registry_routes_to_excel
- test_registry_no_match_raises
- test_bridge_unified_to_card_task

## Риски

| Риск | Серьёзность | Митигация |
|---|---|---|
| import_string() использует /tmp | LOW | Проект уже использует /tmp для кеша |
| Нет тестов для Excel edge cases | LOW | Базовые тесты покрывают основной сценарий |
| field_mapping может устареть | LOW | DEFAULT_FIELD_MAPPING в base.py — единая точка обновления |

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-52` | Дизайн архитектуры |
| Developer Agent | `general-53` | Реализация (9 файлов) |
| Test Agent | `general-54` | Верификация |
| Reviewer Agent | `general-55` | Ревью — REQUEST CHANGES |
| Developer Agent (fix) | `general-56` | Исправление 3 замечаний |
| Reviewer Agent (re-review) | `general-57` | Повторное ревью — APPROVE |

## Готовность к следующим этапам

P1.3 завершён. Universal Import Layer создан. Рекомендуемые следующие шаги:
- P1.4: Интеграция импортёров с batch_enricher (Phase 2)
- P1.5: Telegram /import команда (Phase 3)
- P1.6: PDF/OCR импорт
- P2.1: Inline-клавиатуры для Telegram
