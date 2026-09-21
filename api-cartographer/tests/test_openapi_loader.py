"""Тесты извлечения операций из OpenAPI."""

from __future__ import annotations

import unittest
from pathlib import Path

from api_cartographer.openapi_loader import extract_operations, load_document


FIXTURES = Path(__file__).parent / "fixtures"


class OpenAPILoaderTest(unittest.TestCase):
    def test_extracts_all_operations(self) -> None:
        operations = extract_operations(load_document(FIXTURES / "openapi.yaml"))
        self.assertEqual([item.operation_id for item in operations], ["listUsers", "createUser", "getUser"])
        detail = next(item for item in operations if item.operation_id == "getUser")
        self.assertEqual(detail.parameters[0].name, "id")
        self.assertEqual(detail.parameters[0].location, "path")


if __name__ == "__main__":
    unittest.main()

