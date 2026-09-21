#!/usr/bin/env python3
"""Запускает полную проверку готовности проекта к использованию."""

from __future__ import annotations

import sys
from pathlib import Path


# Healthcheck должен запускаться даже до установки проекта как Python-пакета.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api_cartographer.healthcheck import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

