"""Client delivery report generation."""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from html import escape
from typing import Any

from sqlalchemy import select

from app.database import ClientProject, Database, ProjectReport
from app.effective_card.service import EffectiveProductCardService, _unified_from_snapshot
from app.semantic_core import build_semantic_core
from app.seo_intelligence import audit_unified_product_seo
from app.workspace.files import project_artifact_path


class ClientDeliveryReportService:
    """Builds project-scoped reports for handoff to a client."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._effective = EffectiveProductCardService(db)

    async def preview(self, project_id: str) -> dict[str, Any]:
        async with self._db.session() as session:
            project = await session.get(ClientProject, project_id)
            if project is None:
                raise ValueError("Проект не найден")
        cards = await self._effective.list_effective_cards(project_id, limit=500)
        qualities = [await self._effective.quality(project_id, card.product_id) for card in cards]
        seo_results = [
            audit_unified_product_seo(_unified_from_snapshot(card.effective_snapshot, card.product_id))
            for card in cards
        ]
        semantic_results = [
            build_semantic_core(
                name=unified.name,
                description=unified.description,
                attributes=dict(unified.attributes) if unified.attributes else None,
                category=unified.category,
                tags=unified.tags,
                brand=unified.brand,
            )
            for unified in [
                _unified_from_snapshot(card.effective_snapshot, card.product_id)
                for card in cards
            ]
        ]
        source_scores = [item["source"]["score"] for item in qualities]
        effective_scores = [item["effective"]["score"] for item in qualities]
        seo_scores = [s.score for s in seo_results]
        changed = [card for card in cards if card.is_manually_modified]
        attention = [
            {
                "product_id": card.product_id,
                "title": card.effective_snapshot.get("title") or "Без названия",
                "warnings": card.warnings,
            }
            for card in cards
            if card.warnings or (qualities[cards.index(card)]["effective"]["score"] < 60)
        ]
        tier_counts = Counter(s.tier for s in seo_results)
        worst_seo = sorted(
            [
                {
                    "product_id": cards[i].product_id,
                    "title": cards[i].effective_snapshot.get("title") or "Без названия",
                    "score": seo_results[i].score,
                    "tier": seo_results[i].tier,
                }
                for i in range(len(cards))
            ],
            key=lambda x: x["score"],
        )[:10]
        problem_counter: Counter = Counter()
        for s in seo_results:
            for finding in s.findings:
                problem_counter[finding.rule] += 1
        semantic_term_counter: Counter = Counter()
        for semantic in semantic_results:
            semantic_term_counter.update(semantic.primary_terms)
            semantic_term_counter.update(semantic.secondary_terms)
            semantic_term_counter.update(semantic.attribute_terms)
        seo_summary = {
            "average_score": _avg(seo_scores),
            "distribution": {
                "strong": tier_counts.get("strong", 0),
                "usable": tier_counts.get("usable", 0),
                "needs_work": tier_counts.get("needs_work", 0),
                "weak": tier_counts.get("weak", 0),
            },
            "worst_cards": worst_seo,
            "top_problems": [
                {"rule": rule, "count": count}
                for rule, count in problem_counter.most_common(10)
            ],
            "semantic": {
                "average_coverage_score": _avg_float([s.coverage_score for s in semantic_results]),
                "average_junk_ratio": _avg_float([s.junk_ratio for s in semantic_results]),
                "cards_without_primary_terms": sum(1 for s in semantic_results if not s.primary_terms),
                "top_terms": [
                    {"term": term, "count": count}
                    for term, count in semantic_term_counter.most_common(10)
                ],
            },
        }
        return {
            "project_id": project_id,
            "project_name": project.name,
            "client_name": project.client_name,
            "generated_at": datetime.now(UTC).isoformat(),
            "source_file": project.source_filename,
            "total_products": len(cards),
            "processed_products": len(cards),
            "products_with_errors": 0,
            "average_source_quality_score": _avg(source_scores),
            "average_effective_quality_score": _avg(effective_scores),
            "changed_cards": len(changed),
            "top_problems": _top_problems(qualities),
            "applied_fixes": [_fix_summary(card) for card in changed[:50]],
            "requires_review": attention[:50],
            "created_exports": [],
            "warnings": [],
            "seo_summary": seo_summary,
        }

    async def create_report(self, project_id: str, *, file_format: str = "html") -> ProjectReport:
        summary = await self.preview(project_id)
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        fmt = file_format.lower()
        filename = f"project_{project_id}_report_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{report_id[-6:]}.{fmt}"
        target, relative_path = project_artifact_path(project_id, "reports", filename)
        if fmt == "html":
            target.write_text(_html(summary), encoding="utf-8")
        elif fmt == "json":
            target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "csv":
            target.write_bytes(_csv(summary))
        else:
            raise ValueError("Формат отчёта не поддерживается")
        async with self._db.session() as session:
            record = ProjectReport(
                report_id=report_id,
                project_id=project_id,
                report_type="client_delivery",
                file_format=fmt,
                relative_path=relative_path,
                summary_json=json.dumps(summary, ensure_ascii=False, sort_keys=True),
                status="created",
                created_at=datetime.now(UTC),
            )
            session.add(record)
            await session.commit()
            return record

    async def list_reports(self, project_id: str) -> list[ProjectReport]:
        async with self._db.session() as session:
            result = await session.execute(
                select(ProjectReport)
                .where(ProjectReport.project_id == project_id)
                .order_by(ProjectReport.created_at.desc())
            )
            return list(result.scalars().all())


def _avg(values: list[int]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _avg_float(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _top_problems(qualities: list[dict[str, Any]]) -> list[str]:
    problems: dict[str, int] = {}
    for item in qualities:
        for finding in item["effective"].get("findings", []):
            message = finding.get("message") or finding.get("rule") or "Проблема качества"
            problems[message] = problems.get(message, 0) + 1
    return [key for key, _count in sorted(problems.items(), key=lambda pair: pair[1], reverse=True)[:10]]


def _fix_summary(card) -> str:
    title = card.effective_snapshot.get("title") or f"Товар {card.product_id}"
    fields = ", ".join(card.overridden_fields) if card.overridden_fields else "карточка"
    return f"{title}: изменены поля {fields}"


def _html(summary: dict[str, Any]) -> str:
    problems = "".join(f"<li>{escape(item)}</li>" for item in summary["top_problems"]) or "<li>Критичных проблем не найдено</li>"
    fixes = "".join(f"<li>{escape(item)}</li>" for item in summary["applied_fixes"]) or "<li>Ручные изменения не применялись</li>"
    review = "".join(
        f"<li>{escape(item['title'])}</li>" for item in summary["requires_review"]
    ) or "<li>Нет карточек, требующих ручной проверки</li>"
    return f"""<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>Отчёт проекта</title></head>
<body>
<h1>Отчёт по проекту: {escape(summary['project_name'])}</h1>
<p>Заказчик: {escape(summary.get('client_name') or 'не указан')}</p>
<p>Дата обработки: {escape(summary['generated_at'])}</p>
<p>Исходный файл: {escape(summary.get('source_file') or 'не указан')}</p>
<ul>
  <li>Товаров: {summary['total_products']}</li>
  <li>Успешно обработано: {summary['processed_products']}</li>
  <li>С ошибками: {summary['products_with_errors']}</li>
  <li>Средний Quality Score до: {summary['average_source_quality_score']}</li>
  <li>Средний Quality Score после: {summary['average_effective_quality_score']}</li>
  <li>Изменённых карточек: {summary['changed_cards']}</li>
</ul>
<h2>Основные проблемы</h2><ul>{problems}</ul>
<h2>Выполненные исправления</h2><ul>{fixes}</ul>
<h2>Требуют проверки</h2><ul>{review}</ul>
</body>
</html>"""


def _csv(summary: dict[str, Any]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Показатель", "Значение"])
    for key in (
        "project_name",
        "client_name",
        "total_products",
        "processed_products",
        "products_with_errors",
        "average_source_quality_score",
        "average_effective_quality_score",
        "changed_cards",
    ):
        writer.writerow([key, summary.get(key)])
    return buffer.getvalue().encode("utf-8-sig")
