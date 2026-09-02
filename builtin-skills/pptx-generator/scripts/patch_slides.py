"""Apply small, deterministic edits to an existing Castrel Slide IR file."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _pointer_tokens(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must start with '/': {pointer!r}")
    return [
        token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")
    ]


def _parent(document: Any, pointer: str) -> tuple[Any, str]:
    tokens = _pointer_tokens(pointer)
    if not tokens:
        raise ValueError("A root operation is not supported")
    current = document
    for token in tokens[:-1]:
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current, tokens[-1]


def _apply_operation(document: Any, operation: dict[str, Any]) -> None:
    action = operation.get("op")
    pointer = operation.get("path")
    required_keys = {
        "add": {"op", "path", "value"},
        "replace": {"op", "path", "value"},
        "remove": {"op", "path"},
    }.get(action)
    if required_keys is not None and set(operation) != required_keys:
        raise ValueError(f"{action} operation must contain exactly {sorted(required_keys)}")
    if action not in {"add", "replace", "remove"} or not isinstance(pointer, str):
        raise ValueError(
            "Each operation requires op=add|replace|remove and a JSON Pointer path"
        )
    parent, token = _parent(document, pointer)
    if isinstance(parent, list):
        if action == "add" and token == "-":
            parent.append(operation.get("value"))
            return
        index = int(token)
        if action == "remove":
            parent.pop(index)
        elif action == "replace":
            parent[index] = operation["value"]
        else:
            parent.insert(index, operation.get("value"))
        return
    if action == "remove":
        del parent[token]
    else:
        parent[token] = operation.get("value")


def _find_element(deck: dict[str, Any], element_id: str) -> dict[str, Any]:
    for slide in deck.get("slides", []):
        for element in slide.get("elements", []):
            if isinstance(element, dict) and element.get("id") == element_id:
                return element
    raise ValueError(f"Element id not found: {element_id}")


def _remove_element(deck: dict[str, Any], element_id: str) -> None:
    for slide in deck.get("slides", []):
        elements = slide.get("elements", [])
        for index, element in enumerate(elements):
            if isinstance(element, dict) and element.get("id") == element_id:
                del elements[index]
                return
    raise ValueError(f"Element id not found: {element_id}")


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _write_atomic(path: Path, deck: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary_path = Path(handle.name)
        json.dump(deck, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary_path, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--operation",
        action="append",
        default=[],
        help="JSON operation with op/path/value",
    )
    parser.add_argument(
        "--set-id",
        action="append",
        nargs=3,
        metavar=("ELEMENT_ID", "FIELD", "VALUE"),
        help="Set one field on an element selected by its stable id",
    )
    parser.add_argument(
        "--remove-id", action="append", default=[], metavar="ELEMENT_ID"
    )
    args = parser.parse_args(argv)

    deck = json.loads(args.path.read_text(encoding="utf-8"))
    if not isinstance(deck, dict):
        raise TypeError("Slide IR root must be an object")
    for raw_operation in args.operation:
        operation = json.loads(raw_operation)
        if not isinstance(operation, dict):
            raise TypeError("Operation must be a JSON object")
        action = operation.get("op")
        if action in {"add", "replace", "remove"}:
            _apply_operation(deck, operation)
        elif action == "set_id":
            if set(operation) != {"op", "element_id", "field", "value"}:
                raise ValueError("set_id operation must contain exactly ['element_id', 'field', 'op', 'value']")
            element_id = operation.get("element_id")
            field = operation.get("field")
            if not isinstance(element_id, str) or not element_id:
                raise ValueError("set_id requires a non-empty element_id")
            if not isinstance(field, str) or not field or field == "id":
                raise ValueError("set_id requires a mutable field other than id")
            if "value" not in operation:
                raise ValueError("set_id requires value")
            _find_element(deck, element_id)[field] = operation["value"]
        elif action == "remove_id":
            if set(operation) != {"op", "element_id"}:
                raise ValueError("remove_id operation must contain exactly ['element_id', 'op']")
            element_id = operation.get("element_id")
            if not isinstance(element_id, str) or not element_id:
                raise ValueError("remove_id requires a non-empty element_id")
            _remove_element(deck, element_id)
        else:
            raise ValueError(f"unsupported operation: {action!r}")
    for element_id, field, raw_value in args.set_id or []:
        _find_element(deck, element_id)[field] = _parse_value(raw_value)
    for element_id in args.remove_id:
        _remove_element(deck, element_id)
    _write_atomic(args.path, deck)
    print(f"patched {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
