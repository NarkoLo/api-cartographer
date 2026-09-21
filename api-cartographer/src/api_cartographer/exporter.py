"""Экспорт воспроизводимого пакета знаний для следующего агента."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from api_cartographer import __version__
from api_cartographer.config import ProjectConfig
from api_cartographer.models import OperationMapping, RewriteRule, SourceOperation


def _write_yaml(path: Path, value: Any) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _discovered_document(
    source_document: dict[str, Any],
    mappings: list[OperationMapping],
    base_url: str,
) -> dict[str, Any]:
    """Переносит операции на фактические пути и добавляет доказательства."""

    result = copy.deepcopy(source_document)
    result["paths"] = {}
    if "openapi" in result:
        result["servers"] = [{"url": base_url}]
    else:
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(base_url)
        result["schemes"] = [parsed.scheme]
        result["host"] = parsed.netloc
        result["basePath"] = "/"

    source_paths = source_document.get("paths", {})
    for mapping in mappings:
        if not mapping.target_path:
            continue
        original = source_paths.get(mapping.source_path, {}).get(mapping.method.lower())
        if not isinstance(original, dict):
            continue
        operation = copy.deepcopy(original)
        operation["x-api-cartographer"] = {
            "sourcePath": mapping.source_path,
            "status": mapping.status,
            "confidence": round(mapping.confidence, 4),
            "evidence": mapping.evidence,
        }
        target_item = result["paths"].setdefault(mapping.target_path, {})
        if mapping.method.lower() not in target_item:
            target_item[mapping.method.lower()] = operation
    return result


def export_knowledge_pack(
    config: ProjectConfig,
    source_document: dict[str, Any],
    sources: list[SourceOperation],
    mappings: list[OperationMapping],
    rules: list[RewriteRule],
    output_dir: Path | None = None,
) -> Path:
    """Создаёт все артефакты, необходимые последующему MCP-агенту."""

    destination = output_dir or config.output_path
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "examples" / "requests").mkdir(parents=True, exist_ok=True)
    (destination / "examples" / "responses").mkdir(parents=True, exist_ok=True)

    counts = Counter(mapping.status for mapping in mappings)
    manifest = {
        "format_version": 1,
        "generator": {"name": "api-cartographer", "version": __version__},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "openapi": config.source.openapi,
            "sha256": _sha256(config.openapi_path),
            "operations": len(sources),
        },
        "target": {
            "base_url": config.target.base_url,
            "authentication": config.auth.type,
        },
        "counts": dict(sorted(counts.items())),
        "files": {
            "operation_map": "operation-map.jsonl",
            "rewrite_rules": "rewrite-rules.yaml",
            "discovered_openapi": "discovered-openapi.yaml",
            "unresolved": "unresolved-operations.yaml",
            "report": "discovery-report.md",
        },
    }
    _write_yaml(destination / "manifest.yaml", manifest)

    with (destination / "operation-map.jsonl").open("w", encoding="utf-8") as stream:
        for mapping in mappings:
            stream.write(json.dumps(mapping.to_dict(), ensure_ascii=False) + "\n")

    _write_yaml(
        destination / "rewrite-rules.yaml",
        {"rules": [rule.to_dict() for rule in rules]},
    )
    _write_yaml(
        destination / "unresolved-operations.yaml",
        {
            "operations": [
                mapping.to_dict()
                for mapping in mappings
                if mapping.status in {"unresolved", "ambiguous", "blocked"}
            ]
        },
    )
    _write_yaml(
        destination / "discovered-openapi.yaml",
        _discovered_document(source_document, mappings, config.target.base_url),
    )

    lines = [
        "# Отчёт об исследовании API",
        "",
        f"Сгенерировано: {manifest['generated_at']}",
        "",
        f"Исходных операций: **{len(sources)}**.",
        "",
        "## Покрытие",
        "",
        "| Статус | Количество |",
        "|---|---:|",
    ]
    for status in ("validated", "observed", "inferred", "ambiguous", "unresolved", "blocked"):
        lines.append(f"| `{status}` | {counts.get(status, 0)} |")
    lines.extend(["", "## Нерешённые и неоднозначные операции", ""])
    unresolved = [
        mapping for mapping in mappings if mapping.status in {"unresolved", "ambiguous", "blocked"}
    ]
    if unresolved:
        for mapping in unresolved:
            lines.append(
                f"- `{mapping.method} {mapping.source_path}` — `{mapping.status}`, "
                f"operationId: `{mapping.operation_id}`."
            )
    else:
        lines.append("Нерешённых операций нет.")
    lines.extend(
        [
            "",
            "## Ограничения",
            "",
            "Операции со статусом `inferred` нельзя считать проверенными. "
            "Изменяющие операции не вызываются активным пробером.",
            "",
        ]
    )
    (destination / "discovery-report.md").write_text("\n".join(lines), encoding="utf-8")
    return destination

