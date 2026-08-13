"""Background job helpers for AI suggestion generation."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from app.ai_recommendation.db_approval import DatabaseApprovalQueue
from app.ai_recommendation.engine import AIRecommendationEngine
from app.ai_recommendation.providers.factory import create_configured_provider
from app.ai_recommendation.suggestions import AIRecommendationResult, AISuggestion
from app.effective_card.service import EffectiveProductCardService
from app.products.analyzer import ProductAnalyzer
from app.products.schema import UnifiedProduct
from app.seo_intelligence import audit_unified_product_seo

if TYPE_CHECKING:
    from app.database import Database, PriceHistory, Product

logger = logging.getLogger(__name__)

class AIJobFailureError(RuntimeError):
    """AI job error carrying structured diagnostics for persistence and UI."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def _response_failure_details(provider, response, *, job_id: str, product_id: int, project_id: str | None = None) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "project_id": project_id,
        "product_id": product_id,
        "provider": provider.name(),
        "model": response.model or getattr(provider, "model", getattr(provider, "_model", "")),
        "stage": response.error_stage or "unknown",
        "status_code": response.status_code,
        "latency_ms": response.latency_ms,
        "error_type": response.error_type or "EmptyResponse",
        "error_message": response.error_message or "AI returned an empty response",
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
    }



def _detect_marketplace(url: str | None) -> str:
    low = (url or "").lower()
    if "ozon.ru" in low:
        return "ozon"
    if "wildberries.ru" in low or "wb.ru" in low:
        return "wildberries"
    if "market.yandex" in low or "yandex.ru/market" in low:
        return "yandex_market"
    return "unknown"


def _build_unified(product: Product, last_price: PriceHistory | None) -> UnifiedProduct:
    marketplace = _detect_marketplace(product.url)
    return UnifiedProduct(
        name=product.name or "",
        source_id=str(product.id),
        source_type=marketplace,
        price=last_price.price if last_price else None,
        image_urls=[product.image_url] if product.image_url else [],
        thumbnail_url=product.image_url,
        marketplace=marketplace,
        availability=last_price.availability_status if last_price else "unknown",
        source_url=product.url,
    )


def _build_project_unified(snapshot: dict[str, Any], product_id: int) -> UnifiedProduct:
    tags = snapshot.get("tags") or []
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.replace(";", ",").split(",") if item.strip()]
    attributes = snapshot.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {}
    image_urls = snapshot.get("image_urls") or []
    if isinstance(image_urls, str):
        image_urls = [item.strip() for item in image_urls.split(",") if item.strip()]
    return UnifiedProduct(
        name=str(snapshot.get("title") or ""),
        source_id=str(snapshot.get("external_product_id") or product_id),
        source_type=str(snapshot.get("marketplace") or "unknown"),
        description=snapshot.get("description"),
        brand=snapshot.get("brand"),
        category=snapshot.get("category"),
        sku=snapshot.get("sku") or snapshot.get("external_product_id"),
        price=snapshot.get("price"),
        old_price=snapshot.get("old_price"),
        weight_g=snapshot.get("weight_g"),
        width_mm=snapshot.get("width_mm"),
        height_mm=snapshot.get("height_mm"),
        depth_mm=snapshot.get("depth_mm"),
        image_urls=list(image_urls),
        thumbnail_url=(list(image_urls)[0] if image_urls else None),
        attributes={str(k): str(v) for k, v in attributes.items()},
        tags=[str(item) for item in tags],
        source_url=snapshot.get("source_url"),
        marketplace=snapshot.get("marketplace"),
        availability=str(snapshot.get("availability") or "unknown"),
    )


def _build_project_seo_prompt(
    *,
    product: UnifiedProduct,
    action: str,
    audit,
) -> str:
    lines = [
        "Ты эксперт по SEO-оптимизации карточек товаров на маркетплейсах.",
        "На входе дается SEO-аудит и выбранная пользователем рекомендация.",
        "Сформируй 1-3 конкретных предложения исправления карточки.",
        "Ответ верни ТОЛЬКО JSON-массивом объектов со следующими полями:",
        "- field",
        "- suggestion_type",
        "- before",
        "- after",
        "- reason",
        "- confidence",
        "- source_finding",
        "",
        f"Выбранная рекомендация: {action}",
        f"Товар: {product.name}",
    ]
    if product.description:
        lines.append(f"Описание: {product.description}")
    if product.brand:
        lines.append(f"Бренд: {product.brand}")
    if product.category:
        lines.append(f"Категория: {product.category}")
    if product.price is not None:
        lines.append(f"Цена: {product.price} руб")
    if product.tags:
        lines.append(f"Теги: {', '.join(product.tags)}")

    if audit.findings:
        lines.append("")
        lines.append("Найденные проблемы:")
        for finding in audit.findings:
            lines.append(f"- [{finding.severity}] {finding.field}: {finding.message} ({finding.rule})")

    if audit.recommendations:
        lines.append("")
        lines.append("Рекомендации:")
        for recommendation in audit.recommendations:
            lines.append(
                f"- {recommendation.action} | приоритет {recommendation.priority}: {recommendation.reason}"
            )

    lines.append("")
    lines.append(
        "Сделай предложения практичными, без воды, и не возвращай markdown, пояснения или code fences."
    )
    return "\n".join(lines)


async def process_project_seo_suggestion_job(
    app,
    job_id: str,
    project_id: str,
    product_id: int,
    *,
    action: str,
) -> dict[str, Any]:
    """Execute a queued project SEO suggestion job using the configured AI provider."""
    db: Database = app.state.db
    queue = getattr(app.state, "ai_queue", None)
    if not isinstance(queue, DatabaseApprovalQueue):
        queue = DatabaseApprovalQueue(db)
        app.state.ai_queue = queue

    logger.info(
        "SEO recommendation queued task_id=%s project_id=%s product_id=%s stage=queued action=%s",
        job_id,
        project_id,
        product_id,
        action,
    )
    await db.start_job(job_id)

    try:
        effective_service = EffectiveProductCardService(db)
        card = await effective_service.get_effective_card(project_id, product_id)
        product = _build_project_unified(card.effective_snapshot, product_id)
        audit = audit_unified_product_seo(product)
        provider = create_configured_provider()
        prompt = _build_project_seo_prompt(product=product, action=action, audit=audit)

        if not provider.is_available():
            raise RuntimeError(f"AI provider {provider.name()} is not configured")

        logger.info(
            "AI provider=%s task_id=%s project_id=%s product_id=%s stage=request_started",
            provider.name(),
            job_id,
            project_id,
            product_id,
        )

        response = await provider.complete(
            prompt,
            system="Ты специалист по SEO-карточкам товаров. Отвечай только JSON.",
        )
        response_text = response.text.strip()
        if not response.ok:
            details = _response_failure_details(
                provider, response, job_id=job_id, product_id=product_id, project_id=project_id
            )
            raise AIJobFailureError(
                f"AI request failed: {details['error_type']}: {details['error_message']}",
                details=details,
            )

        model_name = response.model or provider.name()
        recommendations = AIRecommendationEngine._parse_suggestions(response_text)
        if not recommendations:
            raise RuntimeError("AI returned no suggestions")

        suggestions = [
            AISuggestion(
                field=suggestion.field,
                suggestion_type=suggestion.suggestion_type,
                before=suggestion.before,
                after=suggestion.after,
                reason=suggestion.reason,
                confidence=suggestion.confidence,
                source_finding=suggestion.source_finding or action,
                metadata={
                    **suggestion.metadata,
                    "source": "seo_audit",
                    "project_id": project_id,
                    "project_product_id": card.project_product_id,
                    "product_name": card.effective_snapshot.get("title") or str(product_id),
                    "selected_action": action,
                    "job_id": job_id,
                },
            )
            for suggestion in recommendations
        ]

        result = AIRecommendationResult(
            product_id=str(product_id),
            suggestions=suggestions,
            summary=f"SEO suggestion for: {action}",
            overall_confidence=round(sum(s.confidence for s in suggestions) / len(suggestions), 2),
            model_used=model_name,
            tokens_used=response.input_tokens + response.output_tokens,
        )
        added = await queue.add(result)
        approval_ids = [item.approval_id for item in added]
        finished = await db.finish_job(
            job_id,
            {
                "job_id": job_id,
                "project_id": project_id,
                "product_id": product_id,
                "selected_action": action,
                "queued": len(approval_ids),
                "approval_ids": approval_ids,
                "status": "completed",
                "model_used": model_name,
                "provider": provider.name(),
                "latency_ms": response.latency_ms,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
        )
        logger.info(
            "Suggestion saved task_id=%s project_id=%s product_id=%s queued=%s stage=completed",
            job_id,
            project_id,
            product_id,
            len(approval_ids),
        )
        return {
            "job_id": job_id,
            "project_id": project_id,
            "product_id": product_id,
            "selected_action": action,
            "queued": len(approval_ids),
            "approval_ids": approval_ids,
            "status": finished.status if finished else "succeeded",
            "model_used": model_name,
        }
    except Exception as exc:
        logger.warning("AI suggestion job %s failed: %s", job_id, exc, exc_info=True)
        await db.fail_job(job_id, exc, details=getattr(exc, "details", None))
        raise


async def process_product_ai_suggestion_job(app, job_id: str, product_id: int) -> dict[str, Any]:
    """Execute a queued AI suggestion job and persist the results."""
    db: Database = app.state.db
    queue = getattr(app.state, "ai_queue", None)
    if not isinstance(queue, DatabaseApprovalQueue):
        queue = DatabaseApprovalQueue(db)
        app.state.ai_queue = queue

    logger.info("AI task created task_id=%s product_id=%s stage=queued", job_id, product_id)
    await db.start_job(job_id)

    try:
        product = await db.get_product_by_id(product_id)
        if product is None:
            raise ValueError("Product not found")

        last_price = await db.get_last_price(product_id)
        unified = _build_unified(product, last_price)
        analysis = ProductAnalyzer().analyze(unified)
        provider = create_configured_provider()
        logger.info(
            "AI provider=%s model=%s task_id=%s product_id=%s stage=request_started",
            provider.name(),
            getattr(provider, "model", ""),
            job_id,
            product_id,
        )

        if not provider.is_available():
            result = {
                "job_id": job_id,
                "product_id": product_id,
                "queued": 0,
                "approval_ids": [],
                "status": "provider_unavailable",
                "provider": provider.name(),
                "model_used": getattr(provider, "model", getattr(provider, "_model", "")),
                "latency_ms": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
            await db.finish_job(job_id, result)
            logger.warning(
                "AI task failed task_id=%s product_id=%s stage=provider_unavailable provider=%s",
                job_id,
                product_id,
                provider.name(),
            )
            return result

        recommendation = await AIRecommendationEngine(provider).recommend(analysis)
        logger.info(
            "AI request completed task_id=%s product_id=%s stage=response_received model=%s",
            job_id,
            product_id,
            recommendation.model_used,
        )
        suggestions = [
            replace(
                suggestion,
                metadata={
                    **suggestion.metadata,
                    "product_name": product.name or str(product.id),
                    "job_id": job_id,
                },
            )
            for suggestion in recommendation.suggestions
            if suggestion.field and suggestion.after
        ]

        approval_ids: list[str] = []
        if suggestions:
            added = await queue.add(
                AIRecommendationResult(
                    product_id=str(product.id),
                    suggestions=suggestions,
                    summary=recommendation.summary,
                    overall_confidence=recommendation.overall_confidence,
                    model_used=recommendation.model_used,
                    tokens_used=recommendation.tokens_used,
                )
            )
            approval_ids = [item.approval_id for item in added]

        result = {
            "job_id": job_id,
            "product_id": product_id,
            "queued": len(approval_ids),
            "approval_ids": approval_ids,
            "status": "completed",
            "model_used": recommendation.model_used,
            "tokens_used": recommendation.tokens_used,
        }
        await db.finish_job(job_id, result)
        logger.info(
            "Suggestion saved task_id=%s product_id=%s queued=%s stage=completed",
            job_id,
            product_id,
            len(approval_ids),
        )
        return result
    except Exception as exc:
        logger.warning("AI suggestion job %s failed: %s", job_id, exc, exc_info=True)
        await db.fail_job(job_id, exc, details=getattr(exc, "details", None))
        raise
