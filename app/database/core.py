"""Database class: engine/session lifecycle, generic CRUD, telemetry, and the
adaptive cooldown/circuit-breaker orchestration built on top of it.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_URL, logger
from app.database.base import Base
from app.database.models import (
    BlockedPattern,
    JobRecord,
    PriceHistory,
    Product,
    ScrapeAttempt,
    Subscriber,
)
from app.database.resilience import (
    _adaptive_cooldown,
    _classify_failure_trigger,
    _env_float,
    _env_int,
    _next_best_strategy_for,
    _score_source,
    _success_rate,
)
from app.database.utils import (
    _block_patterns_jsonl_path,
    _scrape_attempts_jsonl_path,
    _site_from_url,
    _text_payload,
    url_to_hash,
)
from app.utils.proxy import mask_proxy_url

# ── Database класс ────────────────────────────────────────────────────────────

class Database:
    def __init__(self):
        self._engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self):
        """Инициализирует базу данных.

        NOTE: В будущем create_all будет заменен Alembic миграциями.
        Запускайте `alembic upgrade head` для управления схемой.
        Пока create_all остается для обратной совместимости со старыми БД и тестами.
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if DATABASE_URL.startswith("sqlite"):
                await conn.execute(text("PRAGMA journal_mode=WAL"))
            # NOTE: _migrate_scrape_attempts() будет заменена Alembic в будущем
            await self._migrate_scrape_attempts(conn)
        logger.info("База данных инициализирована")

    def session(self) -> AsyncSession:
        return self._session_factory()

    async def _migrate_scrape_attempts(self, conn) -> None:
        if not DATABASE_URL.startswith("sqlite"):
            return

        rows = await conn.exec_driver_sql("PRAGMA table_info(scrape_attempts)")
        columns = {row[1] for row in rows.fetchall()}
        if not columns:
            return

        migrations = {
            "product_id": "ALTER TABLE scrape_attempts ADD COLUMN product_id INTEGER",
            "site": "ALTER TABLE scrape_attempts ADD COLUMN site TEXT",
            "task_type": "ALTER TABLE scrape_attempts ADD COLUMN task_type VARCHAR(80)",
            "parser_used": "ALTER TABLE scrape_attempts ADD COLUMN parser_used VARCHAR(120)",
            "source": "ALTER TABLE scrape_attempts ADD COLUMN source VARCHAR(32)",
            "status": "ALTER TABLE scrape_attempts ADD COLUMN status VARCHAR(32)",
            "success": "ALTER TABLE scrape_attempts ADD COLUMN success BOOLEAN",
            "recorded_at": "ALTER TABLE scrape_attempts ADD COLUMN recorded_at DATETIME",
            "proxy": "ALTER TABLE scrape_attempts ADD COLUMN proxy TEXT",
            "browser_profile": "ALTER TABLE scrape_attempts ADD COLUMN browser_profile TEXT",
            "strategy": "ALTER TABLE scrape_attempts ADD COLUMN strategy VARCHAR(80)",
            "warnings": "ALTER TABLE scrape_attempts ADD COLUMN warnings TEXT",
            "confidence": "ALTER TABLE scrape_attempts ADD COLUMN confidence FLOAT",
            "next_best_strategy": "ALTER TABLE scrape_attempts ADD COLUMN next_best_strategy VARCHAR(120)",
            "errors": "ALTER TABLE scrape_attempts ADD COLUMN errors TEXT",
        }
        for column, sql in migrations.items():
            if column not in columns:
                await conn.exec_driver_sql(sql)

        if "fetch_status" in columns:
            await conn.exec_driver_sql(
                "UPDATE scrape_attempts SET status = COALESCE(status, fetch_status)"
            )
        if "created_at" in columns:
            await conn.exec_driver_sql(
                "UPDATE scrape_attempts SET recorded_at = COALESCE(recorded_at, created_at)"
            )
        await conn.exec_driver_sql(
            "UPDATE scrape_attempts SET source = COALESCE(source, 'legacy')"
        )
        await conn.exec_driver_sql(
            "UPDATE scrape_attempts SET success = COALESCE(success, CASE WHEN status = 'ok' THEN 1 ELSE 0 END)"
        )

    async def get_all_products(self) -> list[Product]:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(Product))
            return result.scalars().all()

    async def get_latest_product(self) -> Product | None:
        from sqlalchemy import desc, select

        async with self.session() as s:
            result = await s.execute(
                select(Product)
                .order_by(desc(Product.last_check), desc(Product.id))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def create_job(self, job_type: str, payload: dict | None = None, *, job_id: str | None = None) -> JobRecord:
        now = datetime.now(UTC)
        record = JobRecord(
            job_id=job_id or uuid.uuid4().hex,
            job_type=job_type,
            status="queued",
            payload_json=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            progress=0,
            created_at=now,
            updated_at=now,
        )
        async with self.session() as s:
            s.add(record)
            await s.commit()
            await s.refresh(record)
            return record

    async def start_job(self, job_id: str) -> JobRecord | None:
        now = datetime.now(UTC)
        async with self.session() as s:
            record = await s.get(JobRecord, job_id)
            if record is None:
                return None
            record.status = "running"
            record.started_at = record.started_at or now
            record.updated_at = now
            await s.commit()
            await s.refresh(record)
            return record

    async def update_job_progress(self, job_id: str, progress: int) -> JobRecord | None:
        async with self.session() as s:
            record = await s.get(JobRecord, job_id)
            if record is None:
                return None
            record.progress = max(0, min(100, int(progress)))
            record.updated_at = datetime.now(UTC)
            await s.commit()
            await s.refresh(record)
            return record

    async def finish_job(self, job_id: str, result: dict | None = None) -> JobRecord | None:
        now = datetime.now(UTC)
        async with self.session() as s:
            record = await s.get(JobRecord, job_id)
            if record is None:
                return None
            record.status = "succeeded"
            record.progress = 100
            record.result_json = json.dumps(result or {}, ensure_ascii=False, sort_keys=True)
            record.finished_at = now
            record.updated_at = now
            await s.commit()
            await s.refresh(record)
            return record

    async def fail_job(
        self,
        job_id: str,
        error: Exception | str,
        *,
        details: dict | None = None,
    ) -> JobRecord | None:
        now = datetime.now(UTC)
        error_class = error.__class__.__name__ if isinstance(error, Exception) else "JobError"
        error_text = str(error)[:1000]
        async with self.session() as s:
            record = await s.get(JobRecord, job_id)
            if record is None:
                return None
            record.status = "failed"
            record.error_class = error_class
            record.error_text = error_text
            if details is not None:
                record.result_json = json.dumps(details, ensure_ascii=False, sort_keys=True)
            record.finished_at = now
            record.updated_at = now
            await s.commit()
            await s.refresh(record)
            return record

    async def get_recent_jobs(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[JobRecord]:
        from sqlalchemy import desc, select

        stmt = select(JobRecord).order_by(desc(JobRecord.updated_at)).limit(limit)
        if status:
            stmt = stmt.where(JobRecord.status == status)
        if job_type:
            stmt = stmt.where(JobRecord.job_type == job_type)
        async with self.session() as s:
            result = await s.execute(stmt)
            return result.scalars().all()

    async def get_product_by_hash(self, url_hash: str) -> Product | None:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(Product).where(Product.url_hash == url_hash))
            return result.scalar_one_or_none()

    async def get_last_price(self, product_id: int) -> PriceHistory | None:
        from sqlalchemy import desc, select
        async with self.session() as s:
            result = await s.execute(
                select(PriceHistory)
                .where(PriceHistory.product_id == product_id)
                .order_by(desc(PriceHistory.recorded_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def record_scrape_attempt(
        self,
        *,
        url: str,
        marketplace: str,
        source: str,
        status: str,
        latency_ms: int,
        product_id: int | None = None,
        site: str | None = None,
        task_type: str | None = None,
        parser_used: str | None = None,
        success: bool | None = None,
        http_status: int | None = None,
        error_class: str | None = None,
        error_text: str | None = None,
        errors: str | list[str] | tuple[str, ...] | None = None,
        warnings: str | list[str] | tuple[str, ...] | None = None,
        confidence: float | None = None,
        next_best_strategy: str | None = None,
        trigger: str | None = None,
        proxy: str | None = None,
        browser_profile: str | None = None,
        strategy: str | None = None,
        cooldown_sec: int = 0,
    ) -> None:
        now = datetime.now(UTC)
        latency_ms = max(0, int(latency_ms))
        proxy = mask_proxy_url(proxy) if proxy else None
        error_text = error_text[:1000] if error_text else None
        errors_text = _text_payload(errors) or error_text
        warnings_text = _text_payload(warnings)
        site = site or _site_from_url(url) or marketplace
        task_type = task_type or "marketplace_product"
        parser_used = parser_used or marketplace
        success = (status == "ok") if success is None else bool(success)
        confidence = (0.9 if success else 0.0) if confidence is None else max(0.0, min(1.0, float(confidence)))
        next_best_strategy = next_best_strategy or _next_best_strategy_for(source, status)
        trigger = trigger or _classify_failure_trigger(
            status=status,
            http_status=http_status,
            error_class=error_class,
            error_text=errors_text or error_text,
        )
        async with self.session() as s:
            s.add(ScrapeAttempt(
                job_id=0,
                product_id=product_id,
                url=url,
                site=site,
                marketplace=marketplace,
                task_type=task_type,
                parser_used=parser_used,
                fetch_status=status,
                source=source,
                status=status,
                success=success,
                http_status=http_status,
                latency_ms=latency_ms,
                proxy=proxy,
                browser_profile=browser_profile,
                strategy=strategy,
                warnings=warnings_text,
                confidence=confidence,
                next_best_strategy=next_best_strategy,
                error_class=error_class,
                error_text=error_text,
                errors=errors_text,
                created_at=now,
                recorded_at=now,
            ))
            if trigger:
                s.add(BlockedPattern(
                    recorded_at=now,
                    url=url,
                    url_hash=url_to_hash(url) if url else None,
                    marketplace=marketplace,
                    source=source,
                    status=status,
                    trigger=trigger,
                    proxy=proxy,
                    browser_profile=browser_profile,
                    strategy=strategy,
                    cooldown_sec=max(0, int(cooldown_sec or 0)),
                    http_status=http_status,
                    latency_ms=max(0, int(latency_ms or 0)),
                    error_class=error_class,
                    error_text=(error_text[:1000] if error_text else None),
                ))
            await s.commit()
        if trigger:
            self._append_blocked_pattern_jsonl(
                {
                    "recorded_at": now.isoformat(),
                    "url": url,
                    "url_hash": url_to_hash(url) if url else None,
                    "marketplace": marketplace,
                    "source": source,
                    "status": status,
                    "trigger": trigger,
                    "proxy": proxy,
                    "browser_profile": browser_profile,
                    "strategy": strategy,
                    "cooldown_sec": max(0, int(cooldown_sec or 0)),
                    "http_status": http_status,
                    "latency_ms": max(0, int(latency_ms or 0)),
                    "error_class": error_class,
                    "error_text": (error_text[:1000] if error_text else None),
                }
            )
        self._append_scrape_attempt_jsonl(
            {
                "recorded_at": now.isoformat(),
                "product_id": product_id,
                "url": url,
                "site": site,
                "marketplace": marketplace,
                "task_type": task_type,
                "parser_used": parser_used,
                "source": source,
                "status": status,
                "success": success,
                "http_status": http_status,
                "latency_ms": latency_ms,
                "proxy": proxy,
                "browser_profile": browser_profile,
                "strategy": strategy,
                "warnings": warnings_text,
                "confidence": confidence,
                "next_best_strategy": next_best_strategy,
                "error_class": error_class,
                "error_text": error_text,
                "errors": errors_text,
            }
        )

    async def record_blocked_pattern(
        self,
        *,
        url: str | None,
        marketplace: str,
        source: str,
        status: str,
        trigger: str,
        proxy: str | None = None,
        browser_profile: str | None = None,
        strategy: str | None = None,
        cooldown_sec: int = 0,
        http_status: int | None = None,
        latency_ms: int = 0,
        error_class: str | None = None,
        error_text: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        proxy = mask_proxy_url(proxy) if proxy else None
        payload = {
            "recorded_at": now,
            "url": url,
            "url_hash": url_to_hash(url) if url else None,
            "marketplace": marketplace,
            "source": source,
            "status": status,
            "trigger": trigger,
            "proxy": proxy,
            "browser_profile": browser_profile,
            "strategy": strategy,
            "cooldown_sec": max(0, int(cooldown_sec or 0)),
            "http_status": http_status,
            "latency_ms": max(0, int(latency_ms or 0)),
            "error_class": error_class,
            "error_text": (error_text[:1000] if error_text else None),
        }
        try:
            async with self.session() as s:
                s.add(BlockedPattern(**payload))
                await s.commit()
        except Exception:
            logger.warning(
                "blocked pattern write failed (marketplace=%s trigger=%s): "
                "adaptive cooldown/circuit-breaker data may be incomplete",
                marketplace, trigger, exc_info=True,
            )
            return
        json_payload = {**payload, "recorded_at": now.isoformat()}
        self._append_blocked_pattern_jsonl(json_payload)

    def _append_blocked_pattern_jsonl(self, payload: dict) -> None:
        path = _block_patterns_jsonl_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            logger.warning("blocked pattern jsonl write failed (path=%s)", path, exc_info=True)

    def _append_scrape_attempt_jsonl(self, payload: dict) -> None:
        path = _scrape_attempts_jsonl_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            logger.warning("scrape_attempts jsonl write failed (path=%s)", path, exc_info=True)

    async def get_recent_scrape_attempts(
        self,
        limit: int = 100,
        *,
        marketplace: str | None = None,
        minutes: int | None = None,
    ) -> list[ScrapeAttempt]:
        from sqlalchemy import desc, select

        stmt = select(ScrapeAttempt).order_by(desc(ScrapeAttempt.recorded_at)).limit(limit)
        if marketplace:
            stmt = stmt.where(ScrapeAttempt.marketplace == marketplace)
        if minutes:
            since = datetime.now(UTC) - timedelta(minutes=minutes)
            stmt = stmt.where(ScrapeAttempt.recorded_at >= since)
        async with self.session() as s:
            result = await s.execute(stmt)
            return result.scalars().all()

    async def get_recent_blocked_patterns(
        self,
        *,
        marketplace: str | None = None,
        limit: int = 100,
        minutes: int | None = None,
    ) -> list[BlockedPattern]:
        from sqlalchemy import desc, select

        stmt = select(BlockedPattern).order_by(desc(BlockedPattern.recorded_at)).limit(limit)
        if marketplace:
            stmt = stmt.where(BlockedPattern.marketplace == marketplace)
        if minutes:
            since = datetime.now(UTC) - timedelta(minutes=minutes)
            stmt = stmt.where(BlockedPattern.recorded_at >= since)
        async with self.session() as s:
            result = await s.execute(stmt)
            return result.scalars().all()

    async def get_marketplace_health(
        self,
        marketplace: str,
        *,
        window_minutes: int | None = None,
    ) -> dict:
        window = window_minutes or _env_int("ADAPTIVE_BLOCK_WINDOW_MINUTES", 60)
        attempts = await self.get_recent_scrape_attempts(
            marketplace=marketplace,
            limit=_env_int("ADAPTIVE_HEALTH_ATTEMPT_LIMIT", 200),
            minutes=window,
        )
        blocks = await self.get_recent_blocked_patterns(
            marketplace=marketplace,
            limit=_env_int("ADAPTIVE_HEALTH_BLOCK_LIMIT", 200),
            minutes=window,
        )

        attempt_count = len(attempts)
        block_count = len(blocks)
        ok_count = sum(1 for item in attempts if item.status == "ok")
        network_count = sum(1 for item in blocks if item.trigger == "network")
        browser_blocks = [item for item in blocks if item.source == "browser"]
        browser_failures = [
            item for item in attempts
            if item.source == "browser" and item.status not in {"ok", "skipped"}
        ]
        api_blocks = [item for item in blocks if item.source in {"api", "html"}]

        block_rate = block_count / max(1, attempt_count + block_count)
        browser_block_rate = len(browser_blocks) / max(1, block_count)
        network_rate = network_count / max(1, block_count)
        heat_score = min(
            1.0,
            (block_rate * 0.55)
            + (browser_block_rate * 0.2)
            + (network_rate * 0.15)
            + (min(block_count, 10) / 10 * 0.1),
        )
        heat_score = round(heat_score, 4)

        def build_source_stats(source: str) -> dict:
            source_attempts = [item for item in attempts if item.source == source]
            source_blocks = [item for item in blocks if item.source == source]
            total = len(source_attempts)
            ok = sum(1 for item in source_attempts if item.status == "ok")
            block_total = len(source_blocks)
            source_block_rate = block_total / max(1, total + block_total)
            success = _success_rate(total, ok)
            return {
                "attempts": total,
                "ok": ok,
                "blocks": block_total,
                "success_rate": success,
                "block_rate": round(source_block_rate, 4),
                "score": _score_source(
                    success_rate=success,
                    block_rate=source_block_rate,
                    heat_score=heat_score,
                    bias=0.05 if source == "search" else 0.0,
                ),
            }

        source_stats = {
            "api": build_source_stats("api"),
            "browser": build_source_stats("browser"),
            "search_fallback": build_source_stats("search"),
        }

        def build_reputation(field: str) -> dict:
            keys = sorted({
                str(getattr(item, field))
                for item in attempts
                if getattr(item, field)
            } | {
                str(getattr(item, field))
                for item in blocks
                if getattr(item, field)
            })
            reputation = {}
            for key in keys:
                key_attempts = [item for item in attempts if str(getattr(item, field) or "") == key]
                key_blocks = [item for item in blocks if str(getattr(item, field) or "") == key]
                total = len(key_attempts)
                ok = sum(1 for item in key_attempts if item.status == "ok")
                block_total = len(key_blocks)
                block_rate = block_total / max(1, total + block_total)
                success = _success_rate(total, ok)
                reputation[key] = {
                    "attempts": total,
                    "ok": ok,
                    "blocks": block_total,
                    "success_rate": success,
                    "block_rate": round(block_rate, 4),
                    "heavily_blocked": block_total >= _env_int("ADAPTIVE_REPUTATION_BLOCK_THRESHOLD", 3)
                    or block_rate >= _env_float("ADAPTIVE_REPUTATION_BLOCK_RATE", 0.6),
                }
            return reputation

        browser_reputation = build_reputation("browser_profile")
        proxy_reputation = build_reputation("proxy")

        best_profile = None
        best_profile_score = -1.0
        for profile, stats in browser_reputation.items():
            if stats["heavily_blocked"]:
                continue
            score = stats["success_rate"] - stats["block_rate"]
            if score > best_profile_score:
                best_profile = profile
                best_profile_score = score

        best_proxy = None
        best_proxy_score = -1.0
        for proxy, stats in proxy_reputation.items():
            if stats["heavily_blocked"]:
                continue
            score = stats["success_rate"] - stats["block_rate"]
            if score > best_proxy_score:
                best_proxy = proxy
                best_proxy_score = score

        dynamic_cooldown_sec = _adaptive_cooldown(block_count)
        predictive_threshold = _env_float("ADAPTIVE_PREDICTIVE_HEAT_THRESHOLD", 0.9)
        api_disable_threshold = _env_int("ADAPTIVE_API_BLOCK_THRESHOLD", 3)
        return {
            "marketplace": marketplace,
            "window_minutes": window,
            "attempts": attempt_count,
            "ok": ok_count,
            "blocks": block_count,
            "network_failures": network_count,
            "browser_blocks": len(browser_blocks),
            "browser_failures": len(browser_failures),
            "api_blocks": len(api_blocks),
            "heat_score": heat_score,
            "dynamic_cooldown_sec": dynamic_cooldown_sec,
            "predictive_blocking": heat_score >= predictive_threshold,
            "disable_api": len(api_blocks) >= api_disable_threshold,
            "avoid_browser": heat_score >= predictive_threshold
            or len(browser_failures) >= _env_int("ADAPTIVE_BROWSER_FAILURE_THRESHOLD", 3)
            or len(browser_blocks) >= _env_int("ADAPTIVE_BROWSER_BLOCK_THRESHOLD", 3),
            "source_scores": source_stats,
            "browser_reputation": browser_reputation,
            "proxy_reputation": proxy_reputation,
            "preferred_browser_profile": best_profile,
            "preferred_proxy": best_proxy,
        }

    async def recommend_scrape_strategy(
        self,
        marketplace: str,
        *,
        url: str | None = None,
        window_minutes: int | None = None,
    ) -> dict:
        window = window_minutes or _env_int("ADAPTIVE_BLOCK_WINDOW_MINUTES", 60)
        browser_threshold = _env_int("ADAPTIVE_BROWSER_BLOCK_THRESHOLD", 3)
        browser_failure_threshold = _env_int("ADAPTIVE_BROWSER_FAILURE_THRESHOLD", 3)
        network_threshold = _env_int("ADAPTIVE_NETWORK_ERROR_THRESHOLD", 3)
        health = await self.get_marketplace_health(marketplace, window_minutes=window)
        attempts = await self.get_recent_scrape_attempts(
            marketplace=marketplace,
            limit=_env_int("ADAPTIVE_HEALTH_ATTEMPT_LIMIT", 200),
            minutes=window,
        )
        recent = await self.get_recent_blocked_patterns(
            marketplace=marketplace,
            limit=50,
            minutes=window,
        )

        url_hash = url_to_hash(url) if url else None
        same_url = [event for event in recent if url_hash and event.url_hash == url_hash]
        browser_blocks = [
            event for event in recent
            if event.source == "browser" and event.status == "blocked"
        ]
        browser_failures = [
            event for event in attempts
            if event.source == "browser" and event.status not in {"ok", "skipped"}
        ]
        network_failures = [event for event in recent if event.trigger == "network"]

        if same_url and same_url[0].status == "blocked" and same_url[0].source in {"browser", "strategy"}:
            return {
                "strategy": "defer_same_url",
                "skip": True,
                "skip_browser": True,
                "reason": f"same URL recently blocked by {same_url[0].source}",
                "next_best_strategy": "wait_for_cooldown_or_change_route",
                "cooldown_sec": max(
                    _env_int("ADAPTIVE_SAME_URL_COOLDOWN_SEC", 600),
                    health["dynamic_cooldown_sec"],
                ),
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
            }
        if len(browser_failures) >= browser_failure_threshold:
            return {
                "strategy": "api_only_browser_cooldown",
                "skip": False,
                "skip_browser": True,
                "skip_api": False,
                "reason": f"{len(browser_failures)} recent browser failures in {window} min",
                "cooldown_sec": max(
                    _env_int("ADAPTIVE_BROWSER_COOLDOWN_SEC", 1200),
                    health["dynamic_cooldown_sec"],
                ),
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
                "next_best_strategy": "api_or_structured_source_only",
            }
        if len(browser_blocks) >= browser_threshold:
            return {
                "strategy": "api_only_browser_cooldown",
                "skip": False,
                "skip_browser": True,
                "skip_api": False,
                "reason": f"{len(browser_blocks)} recent browser blocks in {window} min",
                "cooldown_sec": max(
                    _env_int("ADAPTIVE_BROWSER_COOLDOWN_SEC", 1200),
                    health["dynamic_cooldown_sec"],
                ),
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
                "next_best_strategy": "api_or_structured_source_only",
            }
        if len(network_failures) >= network_threshold:
            return {
                "strategy": "network_cooldown",
                "skip": True,
                "skip_browser": True,
                "next_best_strategy": "network_cooldown_wait",
                "reason": f"{len(network_failures)} recent network failures in {window} min",
                "cooldown_sec": max(
                    _env_int("ADAPTIVE_NETWORK_COOLDOWN_SEC", 300),
                    health["dynamic_cooldown_sec"],
                ),
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
            }
        if health["disable_api"]:
            return {
                "strategy": "self_heal_disable_api",
                "skip": False,
                "skip_browser": health["avoid_browser"],
                "skip_api": True,
                "reason": f"{health['api_blocks']} recent API blocks in {window} min",
                "next_best_strategy": "browser_if_allowed_or_search_fallback",
                "cooldown_sec": health["dynamic_cooldown_sec"],
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
                "preferred_browser_profile": health["preferred_browser_profile"],
                "preferred_proxy": health["preferred_proxy"],
            }
        if health["predictive_blocking"]:
            return {
                "strategy": "predictive_heat_cooldown",
                "skip": False,
                "skip_browser": True,
                "reason": f"heat_score={health['heat_score']}",
                "next_best_strategy": "wait_or_use_low_cost_source",
                "cooldown_sec": health["dynamic_cooldown_sec"],
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
                "preferred_browser_profile": health["preferred_browser_profile"],
                "preferred_proxy": health["preferred_proxy"],
            }
        return {
            "strategy": "normal",
            "skip": False,
            "skip_browser": False,
            "skip_api": False,
            "reason": "",
            "next_best_strategy": "reuse_current_strategy",
            "cooldown_sec": 0,
            "heat_score": health["heat_score"],
            "source_scores": health["source_scores"],
            "preferred_browser_profile": health["preferred_browser_profile"],
            "preferred_proxy": health["preferred_proxy"],
        }

    async def add_subscriber(self, user_id: int) -> None:
        from sqlalchemy import select

        async with self.session() as s:
            existing = await s.scalar(select(Subscriber).where(Subscriber.user_id == user_id))
            if not existing:
                s.add(Subscriber(user_id=user_id))
                await s.commit()

    async def remove_subscriber(self, user_id: int) -> None:
        from sqlalchemy import select

        async with self.session() as s:
            existing = await s.scalar(select(Subscriber).where(Subscriber.user_id == user_id))
            if existing:
                await s.delete(existing)
                await s.commit()

    async def get_subscribers(self) -> list[int]:
        from sqlalchemy import select

        async with self.session() as s:
            result = await s.execute(select(Subscriber.user_id).order_by(Subscriber.created_at))
            return list(result.scalars().all())

    async def get_subscriber_count(self) -> int:
        from sqlalchemy import func, select

        async with self.session() as s:
            return await s.scalar(select(func.count(Subscriber.id))) or 0

    async def save_product(self, url: str, data: dict) -> tuple[Product, bool]:
        """
        Сохраняет товар и добавляет запись в историю если цена/наличие изменились.
        Возвращает (product, price_changed).
        """
        from sqlalchemy import desc, select
        from sqlalchemy.exc import IntegrityError

        url_hash = url_to_hash(url)
        now = datetime.now(UTC)

        def _touch_existing(p: Product) -> None:
            p.last_check = now
            p.name = data.get("name", p.name)
            p.image_url = data.get("image_url") or p.image_url

        async with self.session() as s:
            result = await s.execute(select(Product).where(Product.url_hash == url_hash))
            product = result.scalar_one_or_none()

            if not product:
                new_product = Product(
                    url_hash=url_hash,
                    url=url,
                    name=data.get("name"),
                    image_url=data.get("image_url"),
                    first_seen=now,
                    last_check=now,
                )
                s.add(new_product)
                try:
                    await s.flush()
                    product = new_product
                    is_new = True
                except IntegrityError:
                    # A concurrent scrape of the same URL won the insert race
                    # (url_hash UNIQUE). Recover by reusing the row it created
                    # instead of propagating an unhandled exception.
                    await s.rollback()
                    result = await s.execute(select(Product).where(Product.url_hash == url_hash))
                    product = result.scalar_one()
                    _touch_existing(product)
                    is_new = False
            else:
                _touch_existing(product)
                is_new = False

            # Последняя запись истории
            last_result = await s.execute(
                select(PriceHistory)
                .where(PriceHistory.product_id == product.id)
                .order_by(desc(PriceHistory.recorded_at))
                .limit(1)
            )
            last = last_result.scalar_one_or_none()

            new_price = data.get("price")
            # Support both payload key conventions:
            # - "availability" (what parsers/worker currently provide)
            # - "availability_status" (what DB/reporting uses)
            new_status = data.get("availability") or data.get("availability_status") or "out_of_stock"
            price_changed = not last or last.price != new_price or last.availability_status != new_status

            if price_changed:
                s.add(PriceHistory(
                    product_id=product.id,
                    price=new_price,
                    availability_status=new_status,
                    recorded_at=now,
                ))
                if last and not is_new:
                    logger.info(
                        f"Изменение [{product.name}]: "
                        f"{last.price}₽→{new_price}₽ | {last.availability_status}→{new_status}"
                    )
                elif is_new:
                    logger.info(f"Новый товар: {product.name} | {new_price}₽ | {new_status}")

            await s.commit()
            return product, price_changed
