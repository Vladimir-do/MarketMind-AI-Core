from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict

from app.universal_parsing_core.schemas.parse_result import ParseResult


def export_json(result: ParseResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False, default=str)


def export_csv(result: ParseResult) -> bytes:
    output = io.StringIO()
    fieldnames = ["entity_type", "title", "price", "description", "url", "source"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for entity in result.entities:
        writer.writerow({name: getattr(entity, name) for name in fieldnames})
    return output.getvalue().encode("utf-8-sig")
