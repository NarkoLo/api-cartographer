"""Безопасная загрузка локальных переменных окружения без сторонних зависимостей."""

from __future__ import annotations

import os
import re
from pathlib import Path


ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: Path, *, override: bool = False) -> int:
    """Загружает dotenv-файл, не печатая имена и значения секретов."""

    if not path.is_file():
        return 0

    loaded = 0
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path}:{number}: ожидалась запись ИМЯ=ЗНАЧЕНИЕ")

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not ENV_NAME_RE.fullmatch(name):
            raise ValueError(f"{path}:{number}: некорректное имя переменной окружения")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        if override or name not in os.environ:
            os.environ[name] = value
            loaded += 1
    return loaded

