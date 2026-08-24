"""Cross-domain pure value validators used by governance protocols."""

from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.governance_semantics import SEMANTIC_DEFINITIONS
except ModuleNotFoundError:
    from governance_semantics import SEMANTIC_DEFINITIONS


def required_fields(value: Any, fields: Iterable[str]) -> list[str]:
    if not isinstance(value, dict):
        return ["根节点必须是对象"]
    return [f"缺少字段 {field_name}" for field_name in fields if field_name not in value]


def validate_text(
    value: Any,
    field_name: str,
    *,
    maximum: int,
    nullable: bool = False,
) -> list[str]:
    if value is None and nullable:
        return []
    if not isinstance(value, str):
        return [f"字段 {field_name} 必须是字符串" + ("或 null" if nullable else "")]
    if not value.strip():
        return [f"字段 {field_name} 不能为空"]
    if len(value) > maximum:
        return [f"字段 {field_name} 长度不能超过 {maximum}"]
    return []


def validate_text_list(
    value: Any,
    field_name: str,
    *,
    minimum: int = 0,
) -> list[str]:
    definition = SEMANTIC_DEFINITIONS["text_list"]
    maximum_items = int(definition["maxItems"])
    item_maximum = int(definition["items"]["maxLength"])
    if not isinstance(value, list):
        return [f"字段 {field_name} 必须是数组"]
    errors: list[str] = []
    if len(value) < minimum:
        errors.append(f"字段 {field_name} 至少需要 {minimum} 项")
    if len(value) > maximum_items:
        errors.append(f"字段 {field_name} 不能超过 {maximum_items} 项")
    for index, item in enumerate(value):
        errors.extend(validate_text(item, f"{field_name}[{index}]", maximum=item_maximum))
    return errors


# Runtime facade compatibility aliases.  The implementation remains here.
_required_fields = required_fields
_validate_text = validate_text
_validate_text_list = validate_text_list
