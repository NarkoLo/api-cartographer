"""Сквозной тест формирования пакета знаний."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from api_cartographer.config import load_config
from api_cartographer.exporter import export_knowledge_pack
from api_cartographer.matcher import apply_rewrite_rules, infer_rewrite_rules, match_operations
from api_cartographer.models import Observation
from api_cartographer.openapi_loader import extract_operations, load_document


FIXTURES = Path(__file__).parent / "fixtures"


class ExporterTest(unittest.TestCase):
    def test_exports_complete_pack(self) -> None:
        config = load_config(FIXTURES / "target.yaml")
        document = load_document(config.openapi_path)
        sources = extract_operations(document)
        observations = [
            Observation.from_dict(json.loads(line))
            for line in (FIXTURES / "observations.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        mappings = match_operations(sources, observations, config.matching.minimum_confidence)
        rules = infer_rewrite_rules(mappings)
        apply_rewrite_rules(mappings, rules)

        with tempfile.TemporaryDirectory() as temporary:
            output = export_knowledge_pack(
                config, document, sources, mappings, rules, Path(temporary)
            )
            manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"]["operations"], 3)
            self.assertTrue((output / "discovered-openapi.yaml").is_file())
            self.assertTrue((output / "discovery-report.md").is_file())


if __name__ == "__main__":
    unittest.main()
