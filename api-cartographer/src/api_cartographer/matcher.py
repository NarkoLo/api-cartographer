"""Эвристическое сопоставление операций и вывод правил изменения путей."""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from api_cartographer.models import Observation, OperationMapping, RewriteRule, SourceOperation
from api_cartographer.openapi_loader import schema_property_names
from api_cartographer.pathing import (
    join_segments,
    longest_common_suffix,
    normalize_path,
    segments,
    static_tokens,
)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _example_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value}
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return {str(key) for key in value[0]}
    return set()


def score_match(source: SourceOperation, observed: Observation) -> float:
    """Оценивает соответствие на основе метода, пути, параметров и ответа."""

    if source.method != observed.method:
        return 0.0
    if observed.source == "probe" and (
        observed.status_code in {404, 405}
        or (observed.status_code is None and any("network-error" in item for item in observed.evidence))
    ):
        return 0.0
    target_path = observed.path_template or observed.path
    normalized_source = normalize_path(source.path)
    normalized_target = normalize_path(target_path)
    if normalized_source == normalized_target:
        path_score = 1.0
    else:
        path_score = SequenceMatcher(None, normalized_source, normalized_target).ratio()

    source_queries = {item.name for item in source.parameters if item.location == "query"}
    query_score = _jaccard(source_queries, set(observed.query_parameters))
    token_score = _jaccard(static_tokens(source.path), static_tokens(target_path))

    response_properties: set[str] = set()
    for schema in source.response_schemas.values():
        response_properties.update(schema_property_names(schema))
    example_score = _jaccard(response_properties, _example_keys(observed.response_example))

    hint_score = 0.0
    if observed.operation_hint:
        hint_score = SequenceMatcher(
            None, source.operation_id.lower(), observed.operation_hint.lower()
        ).ratio()

    score = (
        path_score * 0.58
        + token_score * 0.17
        + query_score * 0.10
        + example_score * 0.10
        + hint_score * 0.05
    )
    # Точное operationId является сильным внешним доказательством, но не отменяет
    # проверку совпадения HTTP-метода, выполненную выше.
    if observed.operation_hint and observed.operation_hint.lower() == source.operation_id.lower():
        score = max(score, 0.90)
    return min(1.0, score)


def match_operations(
    sources: list[SourceOperation],
    observations: list[Observation],
    minimum_confidence: float,
) -> list[OperationMapping]:
    """Строит карту операций и сохраняет альтернативы для неоднозначных случаев."""

    mappings: list[OperationMapping] = []
    for source in sources:
        ranked = sorted(
            (
                (score_match(source, observed), observed)
                for observed in observations
                if observed.method == source.method
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        ranked = [item for item in ranked if item[0] >= minimum_confidence]
        if not ranked:
            mappings.append(
                OperationMapping(
                    operation_id=source.operation_id,
                    method=source.method,
                    source_path=source.path,
                    target_path=None,
                    status="unresolved",
                    confidence=0.0,
                    tags=source.tags,
                    read_only=source.method in {"GET", "HEAD", "OPTIONS"},
                )
            )
            continue

        top_score, top = ranked[0]
        ambiguous = len(ranked) > 1 and top_score - ranked[1][0] < 0.05
        status = "ambiguous" if ambiguous else "observed"
        if top.status_code in {401, 403}:
            status = "blocked"
        elif top.validated and top.status_code is not None and 200 <= top.status_code < 400:
            status = "validated"

        candidates = [
            {
                "path": item.path_template or item.path,
                "score": round(score, 4),
                "source": item.source,
            }
            for score, item in ranked[:5]
        ]
        evidence = list(top.evidence)
        evidence.append(f"{top.source}:{top.method} {top.path}")
        mappings.append(
            OperationMapping(
                operation_id=source.operation_id,
                method=source.method,
                source_path=source.path,
                target_path=top.path_template or top.path,
                status=status,
                confidence=top_score,
                evidence=sorted(set(evidence)),
                query_parameters=top.query_parameters,
                tags=source.tags,
                read_only=source.method in {"GET", "HEAD", "OPTIONS"},
                candidates=candidates if ambiguous else [],
            )
        )
    return mappings


def infer_rewrite_rules(mappings: list[OperationMapping]) -> list[RewriteRule]:
    """Выводит правила замены префикса только из уверенных наблюдений."""

    groups: dict[tuple[str, str], list[OperationMapping]] = defaultdict(list)
    for mapping in mappings:
        if (
            mapping.status not in {"observed", "validated"}
            or not mapping.target_path
            or mapping.confidence < 0.75
        ):
            continue
        suffix = longest_common_suffix(mapping.source_path, mapping.target_path)
        if suffix <= 0:
            continue
        source_parts = segments(mapping.source_path)
        target_parts = segments(mapping.target_path)
        source_prefix = join_segments(source_parts[:-suffix])
        target_prefix = join_segments(target_parts[:-suffix])
        if source_prefix == target_prefix:
            continue
        groups[(source_prefix, target_prefix)].append(mapping)

    rules: list[RewriteRule] = []
    for (source_prefix, target_prefix), support in groups.items():
        average = sum(item.confidence for item in support) / len(support)
        # Несколько независимых подтверждений повышают доверие к правилу.
        confidence = min(0.99, average + min(0.08, (len(support) - 1) * 0.02))
        rules.append(
            RewriteRule(
                source_prefix=source_prefix,
                target_prefix=target_prefix,
                confidence=confidence,
                support_operation_ids=sorted(item.operation_id for item in support),
            )
        )
    return sorted(rules, key=lambda item: (-len(segments(item.source_prefix)), -item.confidence))


def apply_rewrite_rules(
    mappings: list[OperationMapping], rules: list[RewriteRule]
) -> list[OperationMapping]:
    """Заполняет нерешённые операции предположениями, не повышая их до validated."""

    for mapping in mappings:
        if mapping.status != "unresolved":
            continue
        source_parts = segments(mapping.source_path)
        for rule in rules:
            prefix_parts = segments(rule.source_prefix)
            if source_parts[: len(prefix_parts)] != prefix_parts:
                continue
            remainder = source_parts[len(prefix_parts) :]
            mapping.target_path = join_segments(segments(rule.target_prefix) + remainder)
            mapping.status = "inferred"
            mapping.confidence = rule.confidence * 0.85
            mapping.evidence = [
                f"rewrite:{rule.source_prefix}->{rule.target_prefix}",
                *[f"support:{value}" for value in rule.support_operation_ids],
            ]
            break
    return mappings
