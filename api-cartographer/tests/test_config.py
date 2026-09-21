"""Тесты безопасной конфигурации проекта."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from api_cartographer.config import load_config


FIXTURES = Path(__file__).parent / "fixtures"


class ConfigTest(unittest.TestCase):
    def test_example_is_loaded(self) -> None:
        config = load_config(FIXTURES / "target.yaml")
        self.assertEqual(config.auth.type, "none")
        self.assertEqual(config.openapi_path, (FIXTURES / "openapi.yaml").resolve())

    def test_mutating_method_is_rejected(self) -> None:
        text = (FIXTURES / "target.yaml").read_text(encoding="utf-8")
        text = text.replace("[GET, HEAD, OPTIONS]", "[GET, POST]")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "target.yaml"
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "изменяющие методы"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()

