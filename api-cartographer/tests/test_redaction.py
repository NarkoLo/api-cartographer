"""Тесты очистки секретов перед записью артефактов."""

from __future__ import annotations

import unittest

from api_cartographer.redaction import REDACTED, redact


class RedactionTest(unittest.TestCase):
    def test_redacts_headers_and_nested_token(self) -> None:
        token = "super-secret-token"
        value = {
            "Authorization": f"Bearer {token}",
            "nested": {"message": f"Ошибка для {token}"},
        }
        result = redact(value, {"authorization"}, [token])
        self.assertEqual(result["Authorization"], REDACTED)
        self.assertNotIn(token, result["nested"]["message"])


if __name__ == "__main__":
    unittest.main()

