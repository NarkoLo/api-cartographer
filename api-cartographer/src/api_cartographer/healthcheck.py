"""Самодиагностика проекта перед передачей управления OpenCode-агенту."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import yaml

from api_cartographer.config import load_config


@dataclass(slots=True)
class CheckResult:
    """Результат одной независимой проверки готовности."""

    name: str
    status: str
    message: str


def project_root() -> Path:
    """Определяет корень проекта относительно установленного или локального пакета."""

    return Path(__file__).resolve().parents[2]


def _check_files(root: Path) -> CheckResult:
    required = [
        "pyproject.toml",
        "README.md",
        "opencode.jsonc",
        ".opencode/agents/api-cartographer.md",
        ".opencode/commands/map-api.md",
        "config/target.example.yaml",
        "input/README.md",
        "schemas/observation.schema.json",
        "scripts/cartographer.py",
        "scripts/healthcheck.py",
        "scripts/healthcheck.sh",
        "scripts/healthcheck.ps1",
        "scripts/start-playwright-mcp.mjs",
        ".opencode/playwright/init-page.ts",
    ]
    missing = [value for value in required if not (root / value).is_file()]
    if missing:
        return CheckResult("структура", "ERROR", f"Отсутствуют файлы: {', '.join(missing)}")
    return CheckResult("структура", "OK", f"Обязательных файлов: {len(required)}")


def _check_python() -> CheckResult:
    if sys.version_info < (3, 11):
        return CheckResult("python", "ERROR", "Нужен Python 3.11 или новее")
    return CheckResult("python", "OK", sys.version.split()[0])


def _check_opencode(root: Path) -> CheckResult:
    try:
        data = json.loads((root / "opencode.jsonc").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CheckResult("opencode", "ERROR", f"Некорректный opencode.jsonc: {exc}")
    mcp = data.get("mcp", {}).get("playwright")
    if not mcp or mcp.get("type") != "local" or not mcp.get("enabled"):
        return CheckResult("opencode", "ERROR", "Не настроен локальный Playwright MCP")
    prompt_path = root / ".opencode/agents/api-cartographer.md"
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8")
        if not prompt_text.startswith("---\n") or "\n---\n" not in prompt_text[4:]:
            raise ValueError("нет корректного YAML frontmatter")
        frontmatter_text = prompt_text.split("---", 2)[1]
        frontmatter = yaml.safe_load(frontmatter_text)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return CheckResult("opencode", "ERROR", f"Некорректная инструкция агента: {exc}")
    if frontmatter.get("mode") not in {"all", "primary", "subagent"}:
        return CheckResult("opencode", "ERROR", "Недопустимый mode агента")
    if frontmatter.get("permission", {}).get("playwright_*") != "allow":
        return CheckResult("opencode", "ERROR", "Агенту не разрешены инструменты Playwright")
    return CheckResult("opencode", "OK", "Агент, инструкция и Playwright MCP настроены")


def _check_russian_content(root: Path) -> CheckResult:
    files = [
        root / "README.md",
        root / ".opencode/agents/api-cartographer.md",
        root / ".opencode/commands/map-api.md",
        *sorted((root / "src/api_cartographer").glob("*.py")),
        *sorted((root / "scripts").glob("*.py")),
        root / "scripts/start-playwright-mcp.mjs",
        root / ".opencode/playwright/init-page.ts",
    ]
    missing = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if not any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in text):
            missing.append(str(path.relative_to(root)))
    if missing:
        return CheckResult("русский-язык", "ERROR", f"Нет русского текста: {', '.join(missing)}")
    return CheckResult("русский-язык", "OK", f"Проверено файлов: {len(files)}")


def _check_example_config(root: Path) -> CheckResult:
    try:
        config = load_config(root / "config/target.example.yaml")
    except ValueError as exc:
        return CheckResult("пример-конфигурации", "ERROR", str(exc))
    if set(config.discovery.safe_methods) - {"GET", "HEAD", "OPTIONS"}:
        return CheckResult("пример-конфигурации", "ERROR", "Разрешены изменяющие методы")
    return CheckResult("пример-конфигурации", "OK", "Политика read-only активна")


def _check_secrets(root: Path) -> CheckResult:
    # Фрагменты собираются во время выполнения, чтобы проверка не находила сама себя.
    jwt_prefix = "ey" + "J"
    forbidden = (
        "Bearer " + jwt_prefix,
        "Authorization: Bearer " + jwt_prefix,
        "API_BEARER_TOKEN=" + jwt_prefix,
    )
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in {".git", ".venv", "output"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(value in text for value in forbidden):
            hits.append(str(path.relative_to(root)))
    if hits:
        return CheckResult("секреты", "ERROR", f"Возможные токены в файлах: {', '.join(hits)}")
    return CheckResult("секреты", "OK", "Явные Bearer token не обнаружены")


def _run_tests(root: Path) -> CheckResult:
    environment = dict(os.environ)
    source_path = str(root / "src")
    environment["PYTHONPATH"] = (
        source_path
        if not environment.get("PYTHONPATH")
        else source_path + os.pathsep + environment["PYTHONPATH"]
    )
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )
    if completed.returncode:
        tail = "\n".join(completed.stdout.splitlines()[-12:])
        return CheckResult("тесты", "ERROR", tail)
    count = sum(1 for line in completed.stdout.splitlines() if line.rstrip().endswith("... ok"))
    return CheckResult("тесты", "OK", f"Пройдено тестов: {count}")


def _smoke_build(root: Path) -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="api-cartographer-") as temporary:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/cartographer.py",
                "build",
                "--config",
                "tests/fixtures/target.yaml",
                "--observations",
                "tests/fixtures/observations.jsonl",
                "--output",
                temporary,
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
        required = {
            "manifest.yaml",
            "operation-map.jsonl",
            "rewrite-rules.yaml",
            "discovered-openapi.yaml",
            "unresolved-operations.yaml",
            "discovery-report.md",
        }
        produced = {path.name for path in Path(temporary).iterdir()}
        if completed.returncode or not required <= produced:
            return CheckResult("smoke-build", "ERROR", completed.stdout.strip())
        manifest = yaml.safe_load((Path(temporary) / "manifest.yaml").read_text(encoding="utf-8"))
        if manifest.get("source", {}).get("operations") != 3:
            return CheckResult("smoke-build", "ERROR", "Некорректное число операций в manifest")
    return CheckResult("smoke-build", "OK", "Пакет знаний успешно создан")


def _check_playwright(strict: bool) -> CheckResult:
    missing = [name for name in ("node", "npx") if shutil.which(name) is None]
    if missing:
        status = "ERROR" if strict else "WARN"
        return CheckResult("playwright", status, f"Не найдены команды: {', '.join(missing)}")
    return CheckResult("playwright", "OK", "node и npx доступны")


def _check_opencode_binary(strict: bool) -> CheckResult:
    """Проверяет наличие OpenCode, не мешая автономной проверке исходников."""

    executable = shutil.which("opencode")
    if executable is None:
        status = "ERROR" if strict else "WARN"
        return CheckResult("opencode-cli", status, "Команда opencode не найдена")
    return CheckResult("opencode-cli", "OK", executable)


def _check_output(root: Path, config_path: Path) -> CheckResult:
    try:
        config = load_config(config_path)
    except ValueError as exc:
        return CheckResult("результаты", "ERROR", str(exc))
    required = [
        "manifest.yaml",
        "operation-map.jsonl",
        "rewrite-rules.yaml",
        "discovered-openapi.yaml",
        "unresolved-operations.yaml",
        "discovery-report.md",
    ]
    missing = [name for name in required if not (config.output_path / name).is_file()]
    if missing:
        return CheckResult("результаты", "ERROR", f"Не созданы: {', '.join(missing)}")
    try:
        manifest = yaml.safe_load((config.output_path / "manifest.yaml").read_text(encoding="utf-8"))
        lines = (config.output_path / "operation-map.jsonl").read_text(encoding="utf-8").splitlines()
        mappings = [json.loads(line) for line in lines]
        discovered = yaml.safe_load(
            (config.output_path / "discovered-openapi.yaml").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        return CheckResult("результаты", "ERROR", f"Повреждён пакет знаний: {exc}")
    if manifest.get("source", {}).get("operations") != len(lines):
        return CheckResult("результаты", "ERROR", "manifest не соответствует operation-map.jsonl")
    if manifest.get("format_version") != 1:
        return CheckResult("результаты", "ERROR", "Неподдерживаемая версия формата manifest")
    allowed_statuses = {"observed", "validated", "inferred", "ambiguous", "unresolved", "blocked"}
    required_fields = {"operation_id", "method", "source_path", "target_path", "status", "confidence"}
    for index, mapping in enumerate(mappings, start=1):
        missing_fields = required_fields - mapping.keys()
        if missing_fields:
            return CheckResult(
                "результаты",
                "ERROR",
                f"Строка {index}: отсутствуют поля {sorted(missing_fields)}",
            )
        if mapping["status"] not in allowed_statuses:
            return CheckResult("результаты", "ERROR", f"Строка {index}: неизвестный статус")
        if mapping["status"] in {"observed", "validated", "inferred"} and not mapping["target_path"]:
            return CheckResult("результаты", "ERROR", f"Строка {index}: не задан target_path")
        if not 0 <= float(mapping["confidence"]) <= 1:
            return CheckResult("результаты", "ERROR", f"Строка {index}: confidence вне диапазона")
    if not isinstance(discovered, dict) or not isinstance(discovered.get("paths"), dict):
        return CheckResult("результаты", "ERROR", "discovered-openapi.yaml не содержит paths")
    token = os.environ.get(config.auth.token_env, "")
    if token and len(token) >= 8:
        for path in config.output_path.rglob("*"):
            if path.is_file() and token in path.read_text(encoding="utf-8", errors="ignore"):
                return CheckResult("результаты", "ERROR", f"Секрет попал в {path.name}")
    return CheckResult("результаты", "OK", f"Операций в карте: {len(lines)}")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Проверка готовности API Cartographer")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Считать отсутствие Node.js или OpenCode ошибкой",
    )
    parser.add_argument("--check-output", action="store_true", help="Проверить итоговый пакет знаний")
    parser.add_argument("--config", default="config/target.yaml", help="Конфигурация для проверки output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Выполняет все проверки и печатает единый отчёт."""

    args = create_parser().parse_args(argv)
    root = project_root()
    checks: list[Callable[[], CheckResult]] = [
        lambda: _check_files(root),
        _check_python,
        lambda: _check_opencode(root),
        lambda: _check_russian_content(root),
        lambda: _check_example_config(root),
        lambda: _check_secrets(root),
        lambda: _check_playwright(args.strict),
        lambda: _check_opencode_binary(args.strict),
        lambda: _run_tests(root),
        lambda: _smoke_build(root),
    ]
    if args.check_output:
        checks.append(lambda: _check_output(root, (root / args.config).resolve()))

    results = [check() for check in checks]
    for result in results:
        print(f"[{result.status}] {result.name}: {result.message}")
    errors = [result for result in results if result.status == "ERROR"]
    warnings = [result for result in results if result.status == "WARN"]
    print(f"Итог: ошибок — {len(errors)}, предупреждений — {len(warnings)}")
    return 1 if errors else 0
