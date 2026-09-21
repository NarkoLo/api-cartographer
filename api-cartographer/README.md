# API Cartographer для OpenCode

API Cartographer — универсальный OpenCode-агент, который сопоставляет операции
исходной OpenAPI/Swagger-спецификации с фактическими маршрутами целевой системы.

Проект не привязан к Argo Workflows или другому конкретному продукту. Исходная
спецификация определяет, какие операции требуется найти. Результат предназначен
для следующего агента, который проектирует MCP-skill или MCP-сервер.

## Что делает агент

1. Загружает OpenAPI 3.x или Swagger 2.0.
2. Исследует read-only экраны веб-интерфейса через Playwright MCP.
3. Получает фактические сетевые запросы.
4. Сопоставляет их с операциями исходной спецификации.
5. Выводит повторяющиеся правила изменения путей.
6. Может безопасно проверить только `GET`, `HEAD` и `OPTIONS`.
7. Создаёт формализованный пакет знаний для другого агента.

Изменяющие операции не вызываются. Для них агент может построить только
предположение на основании доказанного правила переписывания.

## Требования

- Python 3.11 или новее;
- PyYAML 6.0 или новее;
- Node.js 18 или новее;
- OpenCode;
- доступ к `npx` для запуска `@playwright/mcp`.

Установка Python-пакета необязательна: переносимые скрипты работают напрямую из
репозитория. Для установки в виртуальное окружение:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

В PowerShell активация выглядит так:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Первичная настройка

Создайте рабочую конфигурацию:

```bash
cp config/target.example.yaml config/target.yaml
```

Поместите исходную спецификацию в путь, указанный в `source.openapi`:

```yaml
source:
  openapi: input/openapi.yaml
```

Создайте локальный файл секретов:

```bash
cp .env.example .env.local
```

Пример `.env.local`:

```dotenv
API_BEARER_TOKEN=actual-token
API_BEARER_ORIGINS=https://api.example.internal,https://example.internal
```

`API_BEARER_ORIGINS` обязателен для браузерной подстановки токена. Это защита от
отправки заголовка `Authorization` стороннему origin. Значение должно содержать
только доверенные origin без путей.

Файлы `.env` и `.env.local` исключены из Git.

## Bearer-аутентификация

Конфигурация API:

```yaml
auth:
  type: bearer
  token_env: API_BEARER_TOKEN
  header: Authorization
  scheme: Bearer
```

Python-пробер читает токен только из переменной окружения и отправляет его
только разрешённому origin. Playwright получает токен через локальный процесс и
добавляет заголовок только для `API_BEARER_ORIGINS`.

При запуске CLI файл `.env.local` автоматически загружается из корня проекта.
Уже заданные переменные процесса имеют приоритет. Значение токена не передаётся
в инструкции агента и не печатается в диагностике.

Playwright MCP маскирует значения из `.env.local` в ответах инструментов. Это
дополнительная защита, но не полноценная граница безопасности. Для исследования
следует использовать токен с правами только на чтение.

## Проверка готовности

Git Bash, Linux или macOS:

```bash
./scripts/healthcheck.sh
```

PowerShell:

```powershell
.\scripts\healthcheck.ps1
```

Универсальный вариант:

```bash
python scripts/healthcheck.py
```

Healthcheck проверяет:

- обязательные файлы агента;
- версию Python;
- конфигурацию OpenCode и Playwright MCP;
- наличие русских инструкций и комментариев;
- безопасность примерной конфигурации;
- загрузку `.env.local` без вывода значений;
- отсутствие похожих на Bearer token значений;
- наличие `node` и `npx`;
- наличие OpenCode CLI;
- все модульные тесты;
- полный smoke-сценарий формирования пакета знаний.

Строгий режим считает отсутствие Node.js, `npx` или OpenCode CLI ошибкой:

```bash
python scripts/healthcheck.py --strict
```

После работы агента дополнительно проверяется итоговый пакет:

```bash
python scripts/healthcheck.py --check-output
```

## Запуск OpenCode-агента

Запустите OpenCode из корня проекта:

```bash
opencode
```

Агент доступен по имени:

```text
@api-cartographer исследуй API согласно config/target.yaml
```

Также доступна команда:

```text
/map-api
```

Агент сначала выполняет healthcheck, затем исследует интерфейс и сохраняет
наблюдения в `input/observations.jsonl`.

## Формат наблюдений

Каждая строка `input/observations.jsonl` является отдельным JSON-объектом:

```json
{"method":"GET","path":"/gateway/users/42","path_template":"/gateway/users/{id}","query_parameters":[],"status_code":200,"response_example":{"id":"42"},"operation_hint":"getUser","source":"browser","validated":false,"evidence":["browser-network-request:7"]}
```

Формальная схема находится в `schemas/observation.schema.json`.

Обязательные поля:

- `method` — HTTP-метод в верхнем регистре;
- `path` — фактический путь без домена.

`path_template` желательно задавать всегда, когда путь содержит идентификаторы.
Иначе эвристика попытается определить динамические сегменты самостоятельно.

## Команды Python-ядра

Проверить конфигурацию:

```bash
python scripts/cartographer.py validate-config --config config/target.yaml
```

Построить пакет знаний:

```bash
python scripts/cartographer.py build \
  --config config/target.yaml \
  --observations input/observations.jsonl
```

Объединить браузерные и пробные наблюдения:

```bash
python scripts/cartographer.py merge-observations \
  --config config/target.yaml \
  --inputs input/browser.jsonl input/probed.jsonl \
  --output input/observations.jsonl
```

Безопасно проверить предполагаемые read-only маршруты:

```bash
python scripts/cartographer.py probe \
  --config config/target.yaml \
  --map output/operation-map.jsonl \
  --output input/probed-observations.jsonl
```

Пробер на уровне кода отклоняет методы кроме `GET`, `HEAD` и `OPTIONS`, проверяет
origin и допустимый префикс пути, ограничивает частоту запросов и размер ответа.

## Результат

```text
output/
├── manifest.yaml
├── operation-map.jsonl
├── rewrite-rules.yaml
├── discovered-openapi.yaml
├── unresolved-operations.yaml
├── discovery-report.md
└── examples/
```

Статусы операций:

- `observed` — операция замечена в реальном трафике;
- `validated` — операция проверена безопасным запросом;
- `inferred` — путь получен из доказанного правила;
- `ambiguous` — несколько кандидатов имеют близкие оценки;
- `unresolved` — соответствие не найдено;
- `blocked` — проверка заблокирована правами или сетью.

`inferred` нельзя считать эквивалентом `validated`.

Сопоставление схем используется как дополнительный сигнал. Локальные и внешние
`$ref` сохраняются в итоговой спецификации, но текущая версия не выполняет
полное разыменование внешних документов. Для сложных составных схем главным
доказательством остаются фактический трафик и `operation_hint`.

## Использование следующим агентом

Агент создания MCP-skill должен начинать с `output/manifest.yaml`, затем читать
`operation-map.jsonl` и `discovered-openapi.yaml`. Он не должен автоматически
публиковать `inferred` или `ambiguous` операции как надёжные MCP tools.

Картограф намеренно не принимает решений о количестве MCP tools и не объединяет
REST-операции в бизнес-команды. Это отдельный этап проектирования.

## Возможное развитие

Python-ядро разделено на независимые функции загрузки, сопоставления, проверки и
экспорта. Если потребуется удалённый MCP-сервер, эти функции можно обернуть в
FastMCP без изменения формата пакета знаний и инструкций OpenCode-агента.
