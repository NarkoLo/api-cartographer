"""Модели данных пакета знаний об исследованном API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Parameter:
    """Параметр операции из исходной спецификации."""

    name: str
    location: str
    required: bool = False
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SourceOperation:
    """Операция, извлечённая из OpenAPI или Swagger."""

    operation_id: str
    method: str
    path: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    request_schema: dict[str, Any] | None = None
    response_schemas: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Преобразует операцию в сериализуемый словарь."""

        return asdict(self)


@dataclass(slots=True)
class Observation:
    """Факт вызова операции, полученный из браузера или безопасной проверки."""

    method: str
    path: str
    path_template: str | None = None
    query_parameters: list[str] = field(default_factory=list)
    status_code: int | None = None
    response_example: Any = None
    operation_hint: str | None = None
    source: str = "manual"
    validated: bool = False
    evidence: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Observation":
        """Создаёт наблюдение и нормализует регистр HTTP-метода."""

        allowed = {
            "method",
            "path",
            "path_template",
            "query_parameters",
            "status_code",
            "response_example",
            "operation_hint",
            "source",
            "validated",
            "evidence",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Неизвестные поля наблюдения: {sorted(unknown)}")
        method = str(value["method"]).upper()
        path = str(value["path"])
        source = str(value.get("source", "manual"))
        status_code = value.get("status_code")
        if not method.isalpha():
            raise ValueError("method должен содержать только латинские буквы")
        if not path.startswith("/"):
            raise ValueError("path должен начинаться с /")
        if value.get("path_template") and not str(value["path_template"]).startswith("/"):
            raise ValueError("path_template должен начинаться с /")
        if source not in {"browser", "probe", "manual", "frontend_bundle"}:
            raise ValueError(f"Недопустимый source: {source}")
        if status_code is not None and not 100 <= int(status_code) <= 599:
            raise ValueError("status_code должен находиться в диапазоне 100..599")
        return cls(
            method=method,
            path=path,
            path_template=value.get("path_template"),
            query_parameters=sorted(set(value.get("query_parameters", []))),
            status_code=int(status_code) if status_code is not None else None,
            response_example=value.get("response_example"),
            operation_hint=value.get("operation_hint"),
            source=source,
            validated=bool(value.get("validated", False)),
            evidence=list(value.get("evidence", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразует наблюдение в сериализуемый словарь."""

        return asdict(self)


@dataclass(slots=True)
class OperationMapping:
    """Результат сопоставления исходной и фактической операции."""

    operation_id: str
    method: str
    source_path: str
    target_path: str | None
    status: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    query_parameters: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    read_only: bool = False
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Преобразует сопоставление в стабильный JSON-совместимый формат."""

        result = asdict(self)
        result["confidence"] = round(self.confidence, 4)
        return result


@dataclass(slots=True)
class RewriteRule:
    """Правило замены префикса пути, подтверждённое наблюдениями."""

    source_prefix: str
    target_prefix: str
    confidence: float
    support_operation_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Преобразует правило в сериализуемый словарь."""

        result = asdict(self)
        result["confidence"] = round(self.confidence, 4)
        return result
