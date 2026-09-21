"""Загрузка и строгая проверка пользовательской конфигурации."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from api_cartographer.environment import load_env_file


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
AUTH_TYPES = {"bearer", "none"}


@dataclass(slots=True)
class SourceConfig:
    openapi: str


@dataclass(slots=True)
class TargetConfig:
    base_url: str
    ui_url: str | None = None
    allowed_origins: list[str] = field(default_factory=list)
    allowed_path_prefixes: list[str] = field(default_factory=lambda: ["/"])


@dataclass(slots=True)
class AuthConfig:
    type: str = "none"
    token_env: str = "API_BEARER_TOKEN"
    header: str = "Authorization"
    scheme: str = "Bearer"


@dataclass(slots=True)
class DiscoveryConfig:
    safe_methods: list[str] = field(default_factory=lambda: ["GET", "HEAD", "OPTIONS"])
    requests_per_second: float = 2.0
    request_timeout_seconds: float = 15.0
    max_response_bytes: int = 1_048_576
    parameter_values: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class MatchingConfig:
    minimum_confidence: float = 0.70
    infer_rewrite_rules: bool = True


@dataclass(slots=True)
class OutputConfig:
    directory: str = "output"
    redact_headers: list[str] = field(
        default_factory=lambda: ["authorization", "cookie", "set-cookie", "x-api-key"]
    )


@dataclass(slots=True)
class ProjectConfig:
    source: SourceConfig
    target: TargetConfig
    auth: AuthConfig
    discovery: DiscoveryConfig
    matching: MatchingConfig
    output: OutputConfig
    project_root: Path

    @property
    def openapi_path(self) -> Path:
        """Возвращает путь к спецификации относительно корня проекта."""

        return (self.project_root / self.source.openapi).resolve()

    @property
    def output_path(self) -> Path:
        """Возвращает каталог результатов относительно корня проекта."""

        return (self.project_root / self.output.directory).resolve()

    def bearer_token(self, required: bool = True) -> str | None:
        """Читает Bearer token из окружения, не сохраняя его в объекте конфигурации."""

        if self.auth.type == "none":
            return None
        token = os.environ.get(self.auth.token_env)
        if required and not token:
            raise ValueError(
                f"Не задана переменная окружения {self.auth.token_env} с Bearer token"
            )
        return token


def _require_mapping(data: Any, name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"Раздел {name} должен быть объектом")
    return data


def _validate_url(value: str, field_name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} должен быть абсолютным HTTP(S) URL")


def load_config(path: str | Path, require_secret: bool = False) -> ProjectConfig:
    """Загружает YAML и отклоняет небезопасные или неполные настройки."""

    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise ValueError(f"Файл конфигурации не найден: {config_path}")
    # Переменные процесса имеют приоритет, а локальный файл заполняет только отсутствующие.
    project_root = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent
    load_env_file(project_root / ".env.local")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = _require_mapping(raw, "корень")

    source_raw = _require_mapping(root.get("source"), "source")
    target_raw = _require_mapping(root.get("target"), "target")
    auth_raw = _require_mapping(root.get("auth", {}), "auth")
    discovery_raw = _require_mapping(root.get("discovery", {}), "discovery")
    matching_raw = _require_mapping(root.get("matching", {}), "matching")
    output_raw = _require_mapping(root.get("output", {}), "output")

    if not source_raw.get("openapi"):
        raise ValueError("source.openapi обязателен")
    if not target_raw.get("base_url"):
        raise ValueError("target.base_url обязателен")

    _validate_url(str(target_raw["base_url"]), "target.base_url")
    if target_raw.get("ui_url"):
        _validate_url(str(target_raw["ui_url"]), "target.ui_url")

    allowed_origins = list(target_raw.get("allowed_origins") or [])
    if not allowed_origins:
        parsed = urlparse(str(target_raw["base_url"]))
        allowed_origins = [f"{parsed.scheme}://{parsed.netloc}"]
    for origin in allowed_origins:
        _validate_url(origin, "target.allowed_origins[]")
    base = urlparse(str(target_raw["base_url"]))
    base_origin = f"{base.scheme}://{base.netloc}".rstrip("/")
    if base_origin not in {str(value).rstrip("/") for value in allowed_origins}:
        raise ValueError("Origin target.base_url должен входить в target.allowed_origins")

    prefixes = list(target_raw.get("allowed_path_prefixes") or ["/"])
    if any(not str(prefix).startswith("/") for prefix in prefixes):
        raise ValueError("Каждый allowed_path_prefixes должен начинаться с /")

    auth_type = str(auth_raw.get("type", "none")).lower()
    if auth_type not in AUTH_TYPES:
        raise ValueError(f"Пока поддерживаются auth.type: {sorted(AUTH_TYPES)}")

    methods = [str(value).upper() for value in discovery_raw.get("safe_methods", SAFE_METHODS)]
    unsafe = set(methods) - SAFE_METHODS
    if unsafe:
        raise ValueError(f"В safe_methods обнаружены изменяющие методы: {sorted(unsafe)}")

    rate = float(discovery_raw.get("requests_per_second", 2))
    timeout = float(discovery_raw.get("request_timeout_seconds", 15))
    max_bytes = int(discovery_raw.get("max_response_bytes", 1_048_576))
    if rate <= 0 or rate > 20:
        raise ValueError("requests_per_second должен быть больше 0 и не больше 20")
    if timeout <= 0 or timeout > 300:
        raise ValueError("request_timeout_seconds должен быть в диапазоне (0, 300]")
    if max_bytes <= 0 or max_bytes > 20 * 1024 * 1024:
        raise ValueError("max_response_bytes должен быть от 1 байта до 20 МиБ")

    confidence = float(matching_raw.get("minimum_confidence", 0.70))
    if not 0 <= confidence <= 1:
        raise ValueError("minimum_confidence должен находиться в диапазоне [0, 1]")

    result = ProjectConfig(
        source=SourceConfig(openapi=str(source_raw["openapi"])),
        target=TargetConfig(
            base_url=str(target_raw["base_url"]).rstrip("/"),
            ui_url=target_raw.get("ui_url"),
            allowed_origins=[str(value).rstrip("/") for value in allowed_origins],
            allowed_path_prefixes=[str(value) for value in prefixes],
        ),
        auth=AuthConfig(
            type=auth_type,
            token_env=str(auth_raw.get("token_env", "API_BEARER_TOKEN")),
            header=str(auth_raw.get("header", "Authorization")),
            scheme=str(auth_raw.get("scheme", "Bearer")),
        ),
        discovery=DiscoveryConfig(
            safe_methods=methods,
            requests_per_second=rate,
            request_timeout_seconds=timeout,
            max_response_bytes=max_bytes,
            parameter_values={
                str(key): str(value)
                for key, value in (discovery_raw.get("parameter_values") or {}).items()
            },
        ),
        matching=MatchingConfig(
            minimum_confidence=confidence,
            infer_rewrite_rules=bool(matching_raw.get("infer_rewrite_rules", True)),
        ),
        output=OutputConfig(
            directory=str(output_raw.get("directory", "output")),
            redact_headers=[
                str(value).lower()
                for value in output_raw.get(
                    "redact_headers",
                    ["authorization", "cookie", "set-cookie", "x-api-key"],
                )
            ],
        ),
        project_root=project_root,
    )
    if require_secret:
        result.bearer_token(required=True)
    return result
