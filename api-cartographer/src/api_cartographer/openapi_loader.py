"""Чтение OpenAPI 3.x и Swagger 2.0 без привязки к конкретному продукту."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from api_cartographer.models import Parameter, SourceOperation


HTTP_METHODS = {"get", "head", "options", "post", "put", "patch", "delete", "trace"}


def load_document(path: str | Path) -> dict[str, Any]:
    """Загружает JSON или YAML и проверяет минимальную структуру документа."""

    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"OpenAPI-файл не найден: {file_path}")
    text = file_path.read_text(encoding="utf-8")
    try:
        document = json.loads(text) if file_path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Не удалось разобрать OpenAPI-файл: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("Корень OpenAPI должен быть объектом")
    if "openapi" not in document and "swagger" not in document:
        raise ValueError("Не найдено поле openapi или swagger")
    if not isinstance(document.get("paths"), dict):
        raise ValueError("Поле paths отсутствует или не является объектом")
    return document


def _operation_id(method: str, path: str, operation: dict[str, Any]) -> str:
    explicit = operation.get("operationId")
    if explicit:
        return str(explicit)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_")
    return f"{method.lower()}_{cleaned or 'root'}"


def _schema_from_content(container: dict[str, Any]) -> dict[str, Any] | None:
    content = container.get("content")
    if not isinstance(content, dict):
        return None
    preferred = content.get("application/json")
    if not isinstance(preferred, dict):
        preferred = next((value for value in content.values() if isinstance(value, dict)), None)
    schema = preferred.get("schema") if preferred else None
    return schema if isinstance(schema, dict) else None


def _parameters(values: list[Any]) -> list[Parameter]:
    result: list[Parameter] = []
    for value in values:
        if not isinstance(value, dict) or "$ref" in value:
            continue
        schema = value.get("schema") if isinstance(value.get("schema"), dict) else {}
        if not schema and "type" in value:
            schema = {"type": value["type"]}
        result.append(
            Parameter(
                name=str(value.get("name", "")),
                location=str(value.get("in", "")),
                required=bool(value.get("required", False)),
                schema=schema,
            )
        )
    return result


def extract_operations(document: dict[str, Any]) -> list[SourceOperation]:
    """Извлекает операции, параметры и схемы ответов из документа."""

    result: list[SourceOperation] = []
    is_openapi3 = "openapi" in document
    for path, path_item in document["paths"].items():
        if not isinstance(path_item, dict):
            continue
        shared_parameters = path_item.get("parameters", [])
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            parameters = _parameters(list(shared_parameters) + list(operation.get("parameters", [])))
            request_schema = None
            if is_openapi3 and isinstance(operation.get("requestBody"), dict):
                request_schema = _schema_from_content(operation["requestBody"])
            elif not is_openapi3:
                body = next((item for item in parameters if item.location == "body"), None)
                request_schema = body.schema if body else None

            responses: dict[str, dict[str, Any]] = {}
            for status, response in (operation.get("responses") or {}).items():
                if not isinstance(response, dict):
                    continue
                schema = _schema_from_content(response) if is_openapi3 else response.get("schema")
                if isinstance(schema, dict):
                    responses[str(status)] = schema

            result.append(
                SourceOperation(
                    operation_id=_operation_id(method, str(path), operation),
                    method=method.upper(),
                    path=str(path),
                    summary=str(operation.get("summary") or operation.get("description") or ""),
                    tags=[str(value) for value in operation.get("tags", [])],
                    parameters=parameters,
                    request_schema=request_schema,
                    response_schemas=responses,
                )
            )
    return sorted(result, key=lambda item: (item.path, item.method, item.operation_id))


def schema_property_names(schema: dict[str, Any] | None) -> set[str]:
    """Собирает имена верхнеуровневых полей без полного разыменования `$ref`."""

    if not isinstance(schema, dict):
        return set()
    properties = schema.get("properties")
    if isinstance(properties, dict):
        return {str(value) for value in properties}
    for keyword in ("allOf", "oneOf", "anyOf"):
        variants = schema.get(keyword)
        if isinstance(variants, list):
            result: set[str] = set()
            for variant in variants:
                if isinstance(variant, dict):
                    result.update(schema_property_names(variant))
            return result
    return set()

