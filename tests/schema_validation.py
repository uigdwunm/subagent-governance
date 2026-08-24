"""Small JSON Schema validator for repository contract tests.

The test environment intentionally has no third-party JSON Schema package.  This
module implements the Draft 2020-12 keywords used by this repository and fails
explicitly on unsupported keywords instead of silently skipping validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_ANNOTATION_KEYWORDS = {
    "$id",
    "$schema",
    "$comment",
    "$defs",
    "title",
    "description",
    "default",
    "examples",
    "readOnly",
    "writeOnly",
    "deprecated",
}
_SUPPORTED_KEYWORDS = _ANNOTATION_KEYWORDS | {
    "$ref",
    "type",
    "enum",
    "const",
    "required",
    "properties",
    "patternProperties",
    "additionalProperties",
    "propertyNames",
    "minProperties",
    "maxProperties",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "anyOf",
    "allOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "dependentRequired",
}


@dataclass(frozen=True)
class SchemaValidationError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _json_equal(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _type_matches(instance: Any, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "object":
        return isinstance(instance, dict)
    raise AssertionError(f"unsupported JSON Schema type: {expected}")


def _resolve_pointer(root: Any, reference: str) -> Any:
    if not reference.startswith("#/"):
        raise AssertionError(f"only local JSON Pointer refs are supported: {reference}")
    value = root
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise AssertionError(f"unresolved JSON Schema ref: {reference}")
        value = value[token]
    return value


def validate_instance(instance: Any, schema: Any, *, root_schema: Any | None = None) -> list[SchemaValidationError]:
    """Return deterministic validation errors for the supported schema subset."""
    root = schema if root_schema is None else root_schema
    errors: list[SchemaValidationError] = []
    _validate(instance, schema, root, "$", errors)
    return errors


def assert_schema_supported(schema: Any) -> None:
    """Reject unsupported assertion keywords anywhere in a repository schema."""
    def walk(value: Any, path: str, *, schema_position: bool) -> None:
        if isinstance(value, dict):
            if schema_position:
                unsupported = sorted(
                    key for key in value if key not in _SUPPORTED_KEYWORDS and not key.startswith("x-")
                )
                if unsupported:
                    raise AssertionError(f"{path}: unsupported schema keywords {unsupported}")
            for key, child in value.items():
                child_is_schema = key in {
                    "$defs", "properties", "patternProperties"
                } or key in {
                    "additionalProperties", "propertyNames", "items", "not", "if", "then", "else"
                }
                if key in {"anyOf", "allOf", "oneOf", "prefixItems"} and isinstance(child, list):
                    for index, item in enumerate(child):
                        walk(item, f"{path}.{key}[{index}]", schema_position=True)
                elif key in {"$defs", "properties", "patternProperties"} and isinstance(child, dict):
                    for name, item in child.items():
                        walk(item, f"{path}.{key}.{name}", schema_position=True)
                elif child_is_schema:
                    walk(child, f"{path}.{key}", schema_position=True)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]", schema_position=False)

    walk(schema, "$", schema_position=True)


def _validate(instance: Any, schema: Any, root: Any, path: str, errors: list[SchemaValidationError]) -> None:
    if schema is True:
        return
    if schema is False:
        errors.append(SchemaValidationError(path, "boolean schema is false"))
        return
    if not isinstance(schema, dict):
        raise AssertionError(f"{path}: schema must be an object or boolean")

    if "$ref" in schema:
        _validate(instance, _resolve_pointer(root, schema["$ref"]), root, path, errors)

    if "type" in schema:
        expected = schema["type"]
        expected_types = [expected] if isinstance(expected, str) else expected
        if not isinstance(expected_types, list) or not all(isinstance(item, str) for item in expected_types):
            raise AssertionError(f"{path}: invalid type keyword")
        if not any(_type_matches(instance, item) for item in expected_types):
            errors.append(SchemaValidationError(path, f"expected type {expected_types}"))
            return

    if "enum" in schema and not any(_json_equal(instance, item) for item in schema["enum"]):
        errors.append(SchemaValidationError(path, "value is not in enum"))
    if "const" in schema and not _json_equal(instance, schema["const"]):
        errors.append(SchemaValidationError(path, "value does not match const"))

    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        branches = schema[keyword]
        if not isinstance(branches, list):
            raise AssertionError(f"{path}: {keyword} must be an array")
        branch_errors: list[list[SchemaValidationError]] = []
        for branch in branches:
            current: list[SchemaValidationError] = []
            _validate(instance, branch, root, path, current)
            branch_errors.append(current)
        successes = sum(not current for current in branch_errors)
        if keyword == "allOf":
            for current in branch_errors:
                errors.extend(current)
        elif keyword == "anyOf" and successes == 0:
            errors.append(SchemaValidationError(path, "no anyOf branch matched"))
        elif keyword == "oneOf" and successes != 1:
            errors.append(SchemaValidationError(path, f"expected one oneOf match, got {successes}"))

    if "not" in schema:
        current: list[SchemaValidationError] = []
        _validate(instance, schema["not"], root, path, current)
        if not current:
            errors.append(SchemaValidationError(path, "not schema matched"))

    if "if" in schema:
        condition_errors: list[SchemaValidationError] = []
        _validate(instance, schema["if"], root, path, condition_errors)
        branch = schema.get("then") if not condition_errors else schema.get("else")
        if branch is not None:
            _validate(instance, branch, root, path, errors)

    if isinstance(instance, dict):
        required = schema.get("required", [])
        for field in required:
            if field not in instance:
                errors.append(SchemaValidationError(path, f"missing required property {field}"))
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append(SchemaValidationError(path, "too few properties"))
        if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
            errors.append(SchemaValidationError(path, "too many properties"))
        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        evaluated: set[str] = set()
        for field, child_schema in properties.items():
            if field in instance:
                evaluated.add(field)
                _validate(instance[field], child_schema, root, f"{path}.{field}", errors)
        for pattern, child_schema in patterns.items():
            expression = re.compile(pattern)
            for field, child in instance.items():
                if expression.search(field):
                    evaluated.add(field)
                    _validate(child, child_schema, root, f"{path}.{field}", errors)
        additional = schema.get("additionalProperties", True)
        for field, child in instance.items():
            if field in evaluated:
                continue
            if additional is False:
                errors.append(SchemaValidationError(f"{path}.{field}", "additional property is not allowed"))
            elif isinstance(additional, (dict, bool)):
                _validate(child, additional, root, f"{path}.{field}", errors)
        if "propertyNames" in schema:
            for field in instance:
                _validate(field, schema["propertyNames"], root, f"{path}.{field}<name>", errors)
        for trigger, dependencies in schema.get("dependentRequired", {}).items():
            if trigger in instance:
                for dependency in dependencies:
                    if dependency not in instance:
                        errors.append(SchemaValidationError(path, f"{trigger} requires {dependency}"))

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(SchemaValidationError(path, "too few items"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(SchemaValidationError(path, "too many items"))
        if schema.get("uniqueItems") is True:
            encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in instance]
            if len(encoded) != len(set(encoded)):
                errors.append(SchemaValidationError(path, "items are not unique"))
        prefix = schema.get("prefixItems", [])
        for index, child_schema in enumerate(prefix):
            if index < len(instance):
                _validate(instance[index], child_schema, root, f"{path}[{index}]", errors)
        items = schema.get("items")
        if items is not None:
            for index in range(len(prefix), len(instance)):
                _validate(instance[index], items, root, f"{path}[{index}]", errors)

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(SchemaValidationError(path, "string is too short"))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(SchemaValidationError(path, "string is too long"))
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(SchemaValidationError(path, "string does not match pattern"))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(SchemaValidationError(path, "number is below minimum"))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(SchemaValidationError(path, "number is above maximum"))
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(SchemaValidationError(path, "number is not above exclusiveMinimum"))
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errors.append(SchemaValidationError(path, "number is not below exclusiveMaximum"))
        if "multipleOf" in schema and instance % schema["multipleOf"] != 0:
            errors.append(SchemaValidationError(path, "number is not a multipleOf value"))
