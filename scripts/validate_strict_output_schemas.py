#!/usr/bin/env python3
"""Fail-closed validation for the Structured Outputs schema subset used by Luna v2.

The schema gate is deliberately independent from instance validation.  The latter
is a small ordinary JSON Schema validator for the exact vocabulary used by this
experiment, used by deterministic fixtures and the administrative preflight.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

UNSUPPORTED = {
    "allOf", "oneOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else",
    "patternProperties", "unevaluatedProperties", "contains", "prefixItems", "default",
}


def pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def pointer_join(path: str, token: str) -> str:
    return f"{path}/{pointer_token(token)}"


def resolve_local(root: dict[str, Any], ref: str) -> tuple[Any | None, str | None]:
    if not isinstance(ref, str) or not ref.startswith("#"):
        return None, "only local JSON Pointer $refs are supported"
    if ref == "#":
        return root, None
    current: Any = root
    for token in ref[2:].split("/") if ref.startswith("#/") else []:
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            return None, f"unresolved $ref {ref}"
        current = current[token]
    return current, None


def validate_schema(schema: Any, label: str = "schema") -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    counts = {"objects": 0, "properties": 0, "enums": 0, "strings": 0}
    counted_nodes: set[int] = set()
    active_refs: set[tuple[str, str]] = set()

    def error(path: str, message: str) -> None:
        errors.append({"path": path or "/", "message": message})

    if not isinstance(schema, dict):
        return [{"path": "/", "message": "root schema must be an object"}]
    if schema.get("type") != "object":
        error("", "root schema must have type object")
    if "anyOf" in schema:
        error("/anyOf", "root schema must not use anyOf")

    def declared_types(node: dict[str, Any]) -> set[str]:
        value = node.get("type")
        if isinstance(value, str):
            return {value}
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return set(value)
        return set()

    def json_type(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        return "object"

    def walk(node: Any, path: str, depth: int, ref_context: str = "root") -> None:
        if not isinstance(node, dict):
            error(path, "schema node must be an object")
            return
        for keyword in sorted(UNSUPPORTED.intersection(node)):
            error(pointer_join(path, keyword), f"unsupported keyword {keyword}")

        node_id = id(node)
        if node_id not in counted_nodes:
            counted_nodes.add(node_id)
            if isinstance(node.get("enum"), list):
                counts["enums"] += len(node["enum"])
                for value in node["enum"]:
                    if isinstance(value, str):
                        counts["strings"] += len(value)
            if isinstance(node.get("const"), str):
                counts["strings"] += len(node["const"])

        branches = node.get("anyOf")
        if branches is not None:
            if not isinstance(branches, list) or not branches:
                error(pointer_join(path, "anyOf"), "anyOf must be a non-empty array")
            else:
                for index, branch in enumerate(branches):
                    walk(branch, pointer_join(pointer_join(path, "anyOf"), str(index)), depth, ref_context)

        ref = node.get("$ref")
        if ref is not None:
            target, ref_error = resolve_local(schema, ref)
            ref_path = pointer_join(path, "$ref")
            if ref_error:
                error(ref_path, ref_error)
            elif (ref_context, ref) not in active_refs:
                active_refs.add((ref_context, ref))
                walk(target, ref_path, depth, ref)
                active_refs.remove((ref_context, ref))

        definitions = node.get("$defs")
        if definitions is not None:
            if not isinstance(definitions, dict):
                error(pointer_join(path, "$defs"), "$defs must be an object")
            else:
                counts["strings"] += sum(len(name) for name in definitions)
                for name, definition in definitions.items():
                    walk(definition, pointer_join(pointer_join(path, "$defs"), name), 0, ref_context)

        types = declared_types(node)
        is_object = "object" in types
        has_object_keywords = "properties" in node or "required" in node or "additionalProperties" in node
        if has_object_keywords and node.get("type") != "object":
            error(path, "object schema must declare type object")
        has_array_keywords = "items" in node or "minItems" in node or "maxItems" in node
        if has_array_keywords and node.get("type") != "array":
            error(path, "array schema must declare type array")

        is_array = node.get("type") == "array"
        if "type" not in node and "$ref" not in node and "anyOf" not in node:
            error(path, "schema node must have an explicit type, $ref, or anyOf")
        if "type" in node and not (isinstance(node["type"], str) or (isinstance(node["type"], list) and node["type"] and all(isinstance(item, str) for item in node["type"]))):
            error(pointer_join(path, "type"), "type must be a string or non-empty array of strings")

        if "const" in node:
            if "type" not in node:
                error(path, "const requires an explicit compatible type")
            elif json_type(node["const"]) not in types and not (json_type(node["const"]) == "integer" and "number" in types):
                error(pointer_join(path, "const"), "const value is incompatible with type")
        if "enum" in node:
            if not isinstance(node["enum"], list):
                error(pointer_join(path, "enum"), "enum must be an array")
            elif "type" not in node:
                error(path, "enum requires an explicit compatible type")
            else:
                for index, value in enumerate(node["enum"]):
                    value_type = json_type(value)
                    if value_type not in types and not (value_type == "integer" and "number" in types):
                        error(pointer_join(pointer_join(path, "enum"), str(index)), "enum value is incompatible with type")

        current_depth = depth + 1 if is_object else depth
        object_like = is_object or has_object_keywords
        if object_like:
            counts["objects"] += 1
            if current_depth > 10:
                error(path, "maximum object nesting depth is 10")
            properties = node.get("properties")
            if not isinstance(properties, dict):
                error(pointer_join(path, "properties"), "object schema must have a properties object")
                properties = {}
            else:
                counts["properties"] += len(properties)
                counts["strings"] += sum(len(name) for name in properties)
            if node.get("additionalProperties") is not False:
                error(pointer_join(path, "additionalProperties"), "object schema must set additionalProperties to false")
            required = node.get("required")
            if not isinstance(required, list):
                error(pointer_join(path, "required"), "object schema must have a required array")
                required = []
            if len(required) != len(set(required)):
                error(pointer_join(path, "required"), "required must not contain duplicate names")
            property_names = set(properties)
            required_names = set(required)
            if required_names - property_names:
                error(pointer_join(path, "required"), "required contains a name absent from properties")
            if required_names != property_names:
                error(pointer_join(path, "required"), "required names must equal property names")
            for name, child in properties.items():
                walk(child, pointer_join(pointer_join(path, "properties"), name), current_depth, ref_context)

        items = node.get("items")
        array_like = is_array or has_array_keywords
        if array_like:
            if items is None:
                error(pointer_join(path, "items"), "array schema must have an items schema")
        if items is not None:
            if isinstance(items, dict):
                walk(items, pointer_join(path, "items"), current_depth, ref_context)
            else:
                error(pointer_join(path, "items"), "items must be a schema object")

    walk(schema, "", 0)
    if counts["objects"] and counts["properties"] > 5000:
        error("/", "total object-property count exceeds 5000")
    if counts["strings"] > 120000:
        error("/", "total schema string material exceeds 120000 characters")
    if counts["enums"] > 1000:
        error("/", "total enum values exceeds 1000")
    return errors


def validate_instance(instance: Any, schema: dict[str, Any], root: dict[str, Any] | None = None) -> list[str]:
    """Validate instances against the JSON Schema vocabulary used by this suite."""
    root = schema if root is None else root

    def check(value: Any, node: dict[str, Any], path: str) -> list[str]:
        if "$ref" in node:
            target, message = resolve_local(root, node["$ref"])
            if message:
                return [f"{path or '/'}: {message}"]
            return check(value, target, path)
        if "anyOf" in node:
            branch_errors = [check(value, branch, path) for branch in node["anyOf"]]
            if any(not errors for errors in branch_errors):
                return []
            return [f"{path or '/'}: no anyOf branch matched"]
        errors: list[str] = []
        expected = node.get("type")
        types = expected if isinstance(expected, list) else [expected] if expected else []
        type_ok = True
        if types:
            type_ok = any(
                (kind == "null" and value is None)
                or (kind == "object" and isinstance(value, dict))
                or (kind == "array" and isinstance(value, list))
                or (kind == "string" and isinstance(value, str))
                or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
                or (kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
                or (kind == "boolean" and isinstance(value, bool))
                for kind in types
            )
            if not type_ok:
                return [f"{path or '/'}: expected {types}"]
        if "enum" in node and value not in node["enum"]:
            errors.append(f"{path or '/'}: value is not in enum")
        if isinstance(value, str) and "pattern" in node and re.search(node["pattern"], value) is None:
            errors.append(f"{path or '/'}: string does not match pattern")
        if isinstance(value, dict) and (node.get("type") == "object" or "properties" in node):
            properties = node.get("properties", {})
            missing = set(node.get("required", [])) - set(value)
            errors.extend(f"{path or '/'}/{name}: required property missing" for name in sorted(missing))
            if node.get("additionalProperties") is False:
                extras = set(value) - set(properties)
                errors.extend(f"{path or '/'}/{name}: additional property" for name in sorted(extras))
            for name, child in properties.items():
                if name in value:
                    errors.extend(check(value[name], child, pointer_join(path, name)))
        if isinstance(value, list) and isinstance(node.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(check(item, node["items"], pointer_join(path, str(index))))
        return errors

    return check(instance, schema, "")


def load_and_validate(paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for path in paths:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            result[str(path)] = validate_schema(schema, str(path))
        except Exception as exc:
            result[str(path)] = [{"path": "/", "message": f"could not load schema: {exc}"}]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema", nargs="+", type=Path)
    args = parser.parse_args(argv)
    result = load_and_validate(args.schema)
    errors = [(path, item) for path, items in result.items() for item in items]
    print(json.dumps({"valid": not errors, "schemas": result}, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
