"""Командный интерфейс, которым пользуется OpenCode-агент."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from api_cartographer.config import load_config
from api_cartographer.exporter import export_knowledge_pack
from api_cartographer.matcher import apply_rewrite_rules, infer_rewrite_rules, match_operations
from api_cartographer.models import Observation
from api_cartographer.openapi_loader import extract_operations, load_document
from api_cartographer.probe import probe_file
from api_cartographer.redaction import redact


def load_observations(paths: Sequence[Path], sensitive_keys: set[str], secrets: list[str]) -> list[Observation]:
    """Загружает JSONL, проверяет поля и удаляет секреты до дальнейшей обработки."""

    result: list[Observation] = []
    for path in paths:
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("строка должна содержать JSON-объект")
                value = redact(value, sensitive_keys, secrets)
                result.append(Observation.from_dict(value))
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                raise ValueError(f"{path}:{number}: некорректное наблюдение: {exc}") from exc
    return result


def command_validate_config(args: argparse.Namespace) -> int:
    config = load_config(args.config, require_secret=args.require_secret)
    if not config.openapi_path.is_file():
        raise ValueError(f"OpenAPI-файл не найден: {config.openapi_path}")
    document = load_document(config.openapi_path)
    operations = extract_operations(document)
    print(f"Конфигурация корректна. Операций в спецификации: {len(operations)}")
    return 0


def command_build(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    document = load_document(config.openapi_path)
    operations = extract_operations(document)
    token = config.bearer_token(required=False)
    observation_paths = [Path(value).resolve() for value in args.observations]
    observations = load_observations(
        observation_paths,
        set(config.output.redact_headers),
        [token] if token else [],
    )
    mappings = match_operations(operations, observations, config.matching.minimum_confidence)
    rules = infer_rewrite_rules(mappings) if config.matching.infer_rewrite_rules else []
    mappings = apply_rewrite_rules(mappings, rules)
    output = Path(args.output).resolve() if args.output else config.output_path
    export_knowledge_pack(config, document, operations, mappings, rules, output)
    print(
        f"Пакет знаний создан: {output}. "
        f"Операций: {len(operations)}, наблюдений: {len(observations)}, правил: {len(rules)}"
    )
    return 0


def command_probe(args: argparse.Namespace) -> int:
    config = load_config(args.config, require_secret=True)
    map_path = Path(args.map).resolve()
    output_path = Path(args.output).resolve()
    if not map_path.is_file():
        raise ValueError(f"Карта операций не найдена: {map_path}")
    count = probe_file(config, map_path, output_path)
    print(f"Безопасная проверка завершена. Наблюдений записано: {count}")
    return 0


def command_merge(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    token = config.bearer_token(required=False)
    observations = load_observations(
        [Path(value).resolve() for value in args.inputs],
        set(config.output.redact_headers),
        [token] if token else [],
    )
    # Удаляем точные дубликаты, сохраняя первое доказательство и порядок файлов.
    unique: dict[tuple[str, str, str | None, int | None], Observation] = {}
    for observation in observations:
        key = (
            observation.method,
            observation.path,
            observation.path_template,
            observation.status_code,
        )
        if key not in unique:
            unique[key] = observation
        else:
            current = unique[key]
            current.evidence = sorted(set(current.evidence + observation.evidence))
            current.validated = current.validated or observation.validated
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for observation in unique.values():
            stream.write(json.dumps(observation.to_dict(), ensure_ascii=False) + "\n")
    print(f"Объединено наблюдений: {len(unique)}. Файл: {output}")
    return 0


def create_parser() -> argparse.ArgumentParser:
    """Создаёт дерево CLI-команд с русскими пояснениями."""

    parser = argparse.ArgumentParser(
        prog="api-cartographer",
        description="Сопоставление фактического HTTP API с OpenAPI-спецификацией",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="Проверить конфигурацию и OpenAPI")
    validate.add_argument("--config", default="config/target.yaml")
    validate.add_argument("--require-secret", action="store_true")
    validate.set_defaults(handler=command_validate_config)

    build = subparsers.add_parser("build", help="Построить пакет знаний")
    build.add_argument("--config", default="config/target.yaml")
    build.add_argument(
        "--observations",
        nargs="+",
        default=["input/observations.jsonl"],
        help="Один или несколько JSONL-файлов наблюдений",
    )
    build.add_argument("--output", help="Переопределить каталог результатов")
    build.set_defaults(handler=command_build)

    probe = subparsers.add_parser("probe", help="Проверить разрешённые read-only операции")
    probe.add_argument("--config", default="config/target.yaml")
    probe.add_argument("--map", default="output/operation-map.jsonl")
    probe.add_argument("--output", default="input/probed-observations.jsonl")
    probe.set_defaults(handler=command_probe)

    merge = subparsers.add_parser("merge-observations", help="Объединить JSONL-наблюдения")
    merge.add_argument("--config", default="config/target.yaml")
    merge.add_argument("--inputs", nargs="+", required=True)
    merge.add_argument("--output", default="input/observations.jsonl")
    merge.set_defaults(handler=command_merge)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Выполняет команду и возвращает предсказуемый код завершения."""

    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

