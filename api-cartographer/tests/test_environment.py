"""Тесты безопасной загрузки локального файла окружения."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api_cartographer.environment import load_env_file


class EnvironmentTest(unittest.TestCase):
    def test_loads_env_without_overriding_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env.local"
            path.write_text(
                "API_BEARER_TOKEN=local-token\n"
                "API_BEARER_ORIGINS='https://api.example.test'\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"API_BEARER_TOKEN": "process-token"}, clear=True):
                loaded = load_env_file(path)
                self.assertEqual(loaded, 1)
                self.assertEqual(os.environ["API_BEARER_TOKEN"], "process-token")
                self.assertEqual(
                    os.environ["API_BEARER_ORIGINS"],
                    "https://api.example.test",
                )

    def test_rejects_malformed_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env.local"
            path.write_text("BROKEN_LINE\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_env_file(path)


if __name__ == "__main__":
    unittest.main()

