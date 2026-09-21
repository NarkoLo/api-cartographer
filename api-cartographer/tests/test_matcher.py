"""Тесты сопоставления и вывода правил переписывания."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from api_cartographer.matcher import apply_rewrite_rules, infer_rewrite_rules, match_operations
from api_cartographer.models import Observation
from api_cartographer.openapi_loader import extract_operations, load_document


FIXTURES = Path(__file__).parent / "fixtures"


class MatcherTest(unittest.TestCase):
    def test_observations_create_prefix_rule(self) -> None:
        sources = extract_operations(load_document(FIXTURES / "openapi.yaml"))
        observations = [
            Observation.from_dict(json.loads(line))
            for line in (FIXTURES / "observations.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        mappings = match_operations(sources, observations, 0.65)
        rules = infer_rewrite_rules(mappings)
        apply_rewrite_rules(mappings, rules)

        self.assertTrue(
            any(rule.source_prefix == "/api/v1" and rule.target_prefix == "/gateway" for rule in rules)
        )
        create = next(item for item in mappings if item.operation_id == "createUser")
        self.assertEqual(create.status, "inferred")
        self.assertEqual(create.target_path, "/gateway/users")


if __name__ == "__main__":
    unittest.main()
