"""Timeline event constants and labels."""

from __future__ import annotations

from enum import StrEnum


class TimelineEventType(StrEnum):
    PRODUCT_IMPORTED = "product_imported"
    PRODUCT_SYNCED = "product_synced"
    PRICE_CHANGED = "price_changed"
    STOCK_CHANGED = "stock_changed"
    QUALITY_SCORE_CHANGED = "quality_score_changed"
    AI_SUGGESTION_CREATED = "ai_suggestion_created"
    AI_SUGGESTION_APPROVED = "ai_suggestion_approved"
    AI_SUGGESTION_REJECTED = "ai_suggestion_rejected"
    AI_SUGGESTION_APPLIED = "ai_suggestion_applied"
    AI_SUGGESTION_ROLLED_BACK = "ai_suggestion_rolled_back"
    MANUAL_FIELD_CHANGED = "manual_field_changed"
    CARD_VERSION_CREATED = "card_version_created"
    EXPORT_CREATED = "export_created"
    VALIDATION_ISSUE_FOUND = "validation_issue_found"
    VALIDATION_ISSUE_RESOLVED = "validation_issue_resolved"


class TimelineEventGroup(StrEnum):
    IMPORT = "import"
    PRICE = "price"
    STOCK = "stock"
    AI = "ai"
    DECISION = "decision"
    MANUAL = "manual"
    QUALITY = "quality"
    SYSTEM = "system"


class TimelineSource(StrEnum):
    IMPORT = "import"
    SYNC = "sync"
    AI = "ai"
    USER = "user"
    SYSTEM = "system"
    VALIDATION = "validation"
    EXPORT = "export"
    ROLLBACK = "rollback"
    UNKNOWN = "unknown"


class TimelineStatus(StrEnum):
    RECORDED = "recorded"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    SKIPPED = "skipped"


EVENT_TYPE_LABELS = {
    TimelineEventType.PRODUCT_IMPORTED: "Импорт товара",
    TimelineEventType.PRODUCT_SYNCED: "Синхронизация товара",
    TimelineEventType.PRICE_CHANGED: "Изменение цены",
    TimelineEventType.STOCK_CHANGED: "Изменение остатков",
    TimelineEventType.QUALITY_SCORE_CHANGED: "Изменение Quality Score",
    TimelineEventType.AI_SUGGESTION_CREATED: "AI-рекомендация создана",
    TimelineEventType.AI_SUGGESTION_APPROVED: "AI-рекомендация одобрена",
    TimelineEventType.AI_SUGGESTION_REJECTED: "AI-рекомендация отклонена",
    TimelineEventType.AI_SUGGESTION_APPLIED: "AI-рекомендация применена",
    TimelineEventType.AI_SUGGESTION_ROLLED_BACK: "Решение отменено",
    TimelineEventType.MANUAL_FIELD_CHANGED: "Ручное изменение",
    TimelineEventType.CARD_VERSION_CREATED: "Создана версия карточки",
    TimelineEventType.EXPORT_CREATED: "Создан экспорт",
    TimelineEventType.VALIDATION_ISSUE_FOUND: "Найдена проблема качества",
    TimelineEventType.VALIDATION_ISSUE_RESOLVED: "Проблема качества решена",
}

EVENT_GROUP_LABELS = {
    TimelineEventGroup.IMPORT: "Импорт",
    TimelineEventGroup.PRICE: "Цена",
    TimelineEventGroup.STOCK: "Остатки",
    TimelineEventGroup.AI: "AI-рекомендации",
    TimelineEventGroup.DECISION: "Одобрения и отклонения",
    TimelineEventGroup.MANUAL: "Ручные изменения",
    TimelineEventGroup.QUALITY: "Качество",
    TimelineEventGroup.SYSTEM: "Система",
}

SOURCE_LABELS = {
    TimelineSource.IMPORT: "Импорт",
    TimelineSource.SYNC: "Синхронизация",
    TimelineSource.AI: "AI",
    TimelineSource.USER: "Пользователь",
    TimelineSource.SYSTEM: "Система",
    TimelineSource.VALIDATION: "Проверка качества",
    TimelineSource.EXPORT: "Экспорт",
    TimelineSource.ROLLBACK: "Откат",
    TimelineSource.UNKNOWN: "Неизвестно",
}

STATUS_LABELS = {
    TimelineStatus.RECORDED: "Зафиксировано",
    TimelineStatus.PENDING: "Ожидает решения",
    TimelineStatus.APPROVED: "Принято",
    TimelineStatus.REJECTED: "Отклонено",
    TimelineStatus.APPLIED: "Применено",
    TimelineStatus.ROLLED_BACK: "Отменено",
    TimelineStatus.FAILED: "Ошибка",
    TimelineStatus.SKIPPED: "Пропущено",
}

EVENT_PRIORITY = {
    TimelineEventType.AI_SUGGESTION_ROLLED_BACK: 10,
    TimelineEventType.AI_SUGGESTION_APPLIED: 20,
    TimelineEventType.AI_SUGGESTION_APPROVED: 30,
    TimelineEventType.AI_SUGGESTION_REJECTED: 30,
    TimelineEventType.AI_SUGGESTION_CREATED: 40,
    TimelineEventType.PRICE_CHANGED: 50,
    TimelineEventType.STOCK_CHANGED: 60,
    TimelineEventType.QUALITY_SCORE_CHANGED: 70,
    TimelineEventType.MANUAL_FIELD_CHANGED: 80,
    TimelineEventType.PRODUCT_IMPORTED: 90,
}
