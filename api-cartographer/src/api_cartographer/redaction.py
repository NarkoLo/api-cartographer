"""Удаление токенов и чувствительных HTTP-заголовков из артефактов."""

from __future__ import annotations

from typing import Any


REDACTED = "<redacted>"


def redact(value: Any, sensitive_keys: set[str], secrets: list[str] | None = None) -> Any:
    """Рекурсивно очищает словари, массивы и строковые значения."""

    secrets = [secret for secret in (secrets or []) if secret]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in sensitive_keys:
                result[str(key)] = REDACTED
            else:
                result[str(key)] = redact(item, sensitive_keys, secrets)
        return result
    if isinstance(value, list):
        return [redact(item, sensitive_keys, secrets) for item in value]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, REDACTED)
        return result
    return value

