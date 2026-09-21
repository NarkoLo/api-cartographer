#!/usr/bin/env python3
"""Переносимая точка входа без обязательной установки пакета."""

from __future__ import annotations

import sys
from pathlib import Path


# Добавляем каталог исходников, чтобы команды одинаково работали в Windows и Linux.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api_cartographer.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

