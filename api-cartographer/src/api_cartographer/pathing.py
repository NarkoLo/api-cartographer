"""Нормализация путей и вывод простых правил переписывания."""

from __future__ import annotations

import re
from urllib.parse import urlparse


PARAMETER_RE = re.compile(r"^\{[^{}]+\}$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{12,}$")


def only_path(value: str) -> str:
    """Извлекает путь из URL и гарантирует ведущий слеш."""

    parsed = urlparse(value)
    path = parsed.path if parsed.scheme else value.split("?", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    return re.sub(r"/{2,}", "/", path) or "/"


def segments(path: str) -> list[str]:
    """Разбивает нормализованный путь на непустые сегменты."""

    return [segment for segment in only_path(path).strip("/").split("/") if segment]


def looks_dynamic(segment: str) -> bool:
    """Определяет распространённые идентификаторы без знания предметной области."""

    return bool(
        PARAMETER_RE.match(segment)
        or segment.isdigit()
        or UUID_RE.match(segment)
        or HEX_RE.match(segment)
        or (len(segment) >= 20 and any(char.isdigit() for char in segment))
    )


def normalize_path(path: str) -> str:
    """Заменяет имена и похожие на идентификаторы значения единым маркером."""

    normalized = ["{}" if looks_dynamic(segment) else segment.lower() for segment in segments(path)]
    return "/" + "/".join(normalized)


def static_tokens(path: str) -> set[str]:
    """Возвращает только статические токены пути."""

    return {segment.lower() for segment in segments(path) if not looks_dynamic(segment)}


def longest_common_suffix(left: str, right: str) -> int:
    """Считает количество совпадающих сегментов с конца путей."""

    left_parts = normalize_path(left).strip("/").split("/")
    right_parts = normalize_path(right).strip("/").split("/")
    count = 0
    for left_value, right_value in zip(reversed(left_parts), reversed(right_parts)):
        if left_value != right_value:
            break
        count += 1
    return count


def join_segments(parts: list[str]) -> str:
    """Собирает префикс пути из списка сегментов."""

    return "/" + "/".join(parts) if parts else "/"

