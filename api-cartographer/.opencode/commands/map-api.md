---
description: Построить карту фактического API по OpenAPI-спецификации
agent: api-cartographer
---

Исследуй целевой API согласно `config/target.yaml`. Продолжай автономно до
создания пакета знаний в `output/` и успешного выполнения
`python scripts/healthcheck.py --check-output`. Не выполняй изменяющие HTTP
операции. В конце выведи краткую статистику покрытия и список блокеров.

