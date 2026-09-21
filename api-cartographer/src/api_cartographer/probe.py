"""Безопасная активная проверка только разрешённых read-only операций."""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from api_cartographer.config import ProjectConfig, SAFE_METHODS
from api_cartographer.models import Observation
from api_cartographer.redaction import redact


PATH_PARAMETER_RE = re.compile(r"\{([^{}]+)\}")


def _resolve_path(path: str, values: dict[str, str]) -> str | None:
    """Подставляет только явно заданные значения параметров пути."""

    missing = [name for name in PATH_PARAMETER_RE.findall(path) if name not in values]
    if missing:
        return None
    return PATH_PARAMETER_RE.sub(lambda match: quote(values[match.group(1)], safe=""), path)


def _ensure_allowed(config: ProjectConfig, url: str, method: str) -> None:
    """Применяет ограничения до выполнения любого сетевого запроса."""

    if method not in SAFE_METHODS or method not in config.discovery.safe_methods:
        raise ValueError(f"Метод {method} запрещён политикой безопасного исследования")
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin.rstrip("/") not in config.target.allowed_origins:
        raise ValueError(f"Origin не входит в allowlist: {origin}")
    if not any(parsed.path.startswith(prefix) for prefix in config.target.allowed_path_prefixes):
        raise ValueError(f"Путь не входит в allowlist: {parsed.path}")


def probe_mapping(
    config: ProjectConfig,
    mapping: dict[str, Any],
    token: str | None,
) -> Observation | None:
    """Проверяет одно сопоставление и возвращает очищенное наблюдение."""

    method = str(mapping.get("method", "")).upper()
    template = mapping.get("target_path")
    if not template or method not in config.discovery.safe_methods:
        return None
    resolved = _resolve_path(str(template), config.discovery.parameter_values)
    if resolved is None:
        return None
    url = urljoin(config.target.base_url + "/", resolved.lstrip("/"))
    _ensure_allowed(config, url, method)

    headers = {"Accept": "application/json"}
    if config.auth.type == "bearer" and token:
        headers[config.auth.header] = f"{config.auth.scheme} {token}".strip()
    request = urllib.request.Request(url, headers=headers, method=method)
    status_code: int | None = None
    body = b""
    response_headers: dict[str, str] = {}
    try:
        with urllib.request.urlopen(
            request,
            timeout=config.discovery.request_timeout_seconds,
            context=ssl.create_default_context(),
        ) as response:
            status_code = response.status
            response_headers = dict(response.headers.items())
            body = response.read(config.discovery.max_response_bytes + 1)
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        body = exc.read(config.discovery.max_response_bytes + 1)
    except urllib.error.URLError as exc:
        return Observation(
            method=method,
            path=urlparse(url).path,
            path_template=str(template),
            source="probe",
            validated=False,
            evidence=[f"network-error:{type(exc.reason).__name__}"],
        )

    truncated = len(body) > config.discovery.max_response_bytes
    body = body[: config.discovery.max_response_bytes]
    example: Any = body.decode("utf-8", errors="replace")
    content_type = response_headers.get("Content-Type", "")
    if "json" in content_type.lower() and body:
        try:
            example = json.loads(body)
        except json.JSONDecodeError:
            pass
    example = redact(
        example,
        set(config.output.redact_headers),
        [token] if token else [],
    )
    evidence = [f"probe-status:{status_code}"]
    if truncated:
        evidence.append("response-truncated")
    return Observation(
        method=method,
        path=urlparse(url).path,
        path_template=str(template),
        status_code=status_code,
        response_example=example,
        operation_hint=mapping.get("operation_id"),
        source="probe",
        validated=status_code is not None and 200 <= status_code < 400,
        evidence=evidence,
    )


def probe_file(config: ProjectConfig, map_path: Path, output_path: Path) -> int:
    """Проверяет карту с ограничением частоты и записывает JSONL-наблюдения."""

    token = config.bearer_token(required=config.auth.type == "bearer")
    delay = 1.0 / config.discovery.requests_per_second
    observations: list[Observation] = []
    for line in map_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        mapping = json.loads(line)
        observation = probe_mapping(config, mapping, token)
        if observation is not None:
            observations.append(observation)
            time.sleep(delay)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        for observation in observations:
            stream.write(json.dumps(observation.to_dict(), ensure_ascii=False) + "\n")
    return len(observations)
