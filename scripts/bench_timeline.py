"""Lightweight synthetic benchmark for the product timeline builder.

This script is intentionally not part of normal pytest. Run manually:

    .venv/bin/python scripts/bench_timeline.py
    .venv/bin/python scripts/bench_timeline.py --include-100k
"""

from __future__ import annotations

import argparse
import sys
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import PriceHistory, Product  # noqa: E402
from app.timeline.builder import ProductHistoryBuilder  # noqa: E402


def _product() -> Product:
    return Product(
        id=1,
        url_hash="bench",
        url="https://example.test/bench",
        name="Benchmark product",
        first_seen=datetime(2026, 7, 17, tzinfo=UTC),
    )


def _price_rows(count: int) -> list[PriceHistory]:
    base = datetime(2026, 7, 17, tzinfo=UTC)
    rows = []
    for index in range(count):
        rows.append(
            PriceHistory(
                id=index + 1,
                product_id=1,
                price=1000 + index,
                availability_status="in_stock" if index % 2 == 0 else "out_of_stock",
                recorded_at=base + timedelta(minutes=index),
            )
        )
    return rows


def run_case(count: int) -> dict[str, int | float]:
    builder = ProductHistoryBuilder()
    product = _product()
    rows = _price_rows(count)
    tracemalloc.start()
    started = time.perf_counter()
    events = builder.build(
        product=product,
        price_history=rows,
        approval_records=[],
        limit=50,
        offset=0,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "rows": count,
        "returned_events": len(events),
        "elapsed_ms": round(elapsed_ms, 2),
        "peak_kb": round(peak / 1024, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark timeline builder with synthetic rows.")
    parser.add_argument("--include-100k", action="store_true", help="Include the heavy 100k synthetic case.")
    args = parser.parse_args()

    sizes = [10, 1_000, 10_000]
    if args.include_100k:
        sizes.append(100_000)
    for size in sizes:
        print(run_case(size))


if __name__ == "__main__":
    main()
