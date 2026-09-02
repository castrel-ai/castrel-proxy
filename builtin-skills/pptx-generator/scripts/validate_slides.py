#!/usr/bin/env python3
"""Validate a Castrel Slide IR deck before it is persisted.

The validator intentionally uses only the Python standard library so it can run
inside the dependency-complete sandbox image without installing anything.
Structural and security violations fail the command. Visual-quality findings
are warnings by default and become failures with ``--strict``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

CANVAS_WIDTH = 1000.0
CANVAS_HEIGHT = 562.5
ALLOWED_ELEMENT_TYPES = {
    "text",
    "image",
    "shape",
    "line",
    "table",
    "chart",
    "latex",
    "video",
    "audio",
}
ALLOWED_TEXT_TAGS = {"p", "div", "span", "strong", "b", "em", "i", "u", "ins", "br"}
ALLOWED_STYLE_PROPERTIES = {
    "color",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "line-height",
    "text-align",
    "text-decoration",
}
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
FONT_SIZE_PATTERN = re.compile(r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*px", re.I)
RAW_NEWLINE_PATTERN = re.compile(r"[\r\n]")


@dataclass
class Issue:
    severity: str
    code: str
    path: str
    message: str


class TextMarkupParser(HTMLParser):
    """Collect tags and visible text while checking the safe HTML subset."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str, str]] = []
        self.visible_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        self.tags.append(normalized_tag)
        for name, value in attrs:
            self.attributes.append((normalized_tag, name.lower(), value or ""))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        self.visible_text.append(data)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _visible_text(content: str) -> str:
    parser = TextMarkupParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception:
        return ""
    return " ".join("".join(parser.visible_text).split())


def _path_for(index: int, key: str | None = None) -> str:
    return f"slides[{index}]" if key is None else f"slides[{index}].{key}"


class SlideValidator:
    def __init__(self, strict: bool = False) -> None:
        self.strict = strict
        self.issues: list[Issue] = []
        self.slide_ids: set[str] = set()
        self.element_ids: set[str] = set()
        self.layout_signatures: list[tuple[Any, ...]] = []
        self.element_count = 0

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def add(self, severity: str, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(severity, code, path, message))

    def error(self, code: str, path: str, message: str) -> None:
        self.add("error", code, path, message)

    def warning(self, code: str, path: str, message: str) -> None:
        self.add("warning", code, path, message)

    def validate(self, raw: Any) -> None:
        if not isinstance(raw, dict):
            self.error("deck.type", "$", "Deck must be an object with a 'slides' array.")
            return

        slides = raw.get("slides")
        if not isinstance(slides, list):
            self.error("deck.slides", "slides", "Deck must contain a 'slides' array.")
            return
        if not slides:
            self.error("deck.empty", "slides", "Deck must contain at least one slide.")
            return

        for key, expected in (("width", CANVAS_WIDTH), ("height", CANVAS_HEIGHT)):
            if key in raw and (
                not _is_number(raw[key])
                or not math.isclose(float(raw[key]), expected, abs_tol=0.01)
            ):
                self.error(
                    "deck.canvas",
                    key,
                    f"{key} must be {expected:g} when provided; got {raw[key]!r}.",
                )

        for slide_index, slide in enumerate(slides):
            self._validate_slide(slide_index, slide)

        if len(self.layout_signatures) > 1:
            for index in range(1, len(self.layout_signatures)):
                if self.layout_signatures[index] == self.layout_signatures[index - 1]:
                    self.warning(
                        "layout.repeated",
                        _path_for(index),
                        "Consecutive slides use the same geometry/type composition; vary the visual narrative.",
                    )

    def _validate_slide(self, slide_index: int, slide: Any) -> None:
        path = _path_for(slide_index)
        if not isinstance(slide, dict):
            self.error("slide.type", path, "Slide must be an object.")
            return

        slide_id = slide.get("id")
        if not isinstance(slide_id, str) or not slide_id.strip():
            self.error("slide.id", f"{path}.id", "Slide id must be a non-empty stable string.")
        elif slide_id in self.slide_ids:
            self.error("slide.id_duplicate", f"{path}.id", f"Duplicate slide id: {slide_id!r}.")
        else:
            self.slide_ids.add(slide_id)
            if not ID_PATTERN.fullmatch(slide_id):
                self.error(
                    "slide.id_format",
                    f"{path}.id",
                    "Slide id may contain only letters, digits, '.', ':', '_' and '-'.",
                )

        elements = slide.get("elements")
        if not isinstance(elements, list):
            self.error(
                "slide.elements", f"{path}.elements", "Slide must contain an elements array."
            )
            return
        if not elements:
            self.warning("slide.empty", f"{path}.elements", "Slide contains no elements.")

        visible_chars = 0
        positioned_elements: list[tuple[str, dict[str, Any], tuple[float, float, float, float]]] = (
            []
        )
        for element_index, element in enumerate(elements):
            element_path = f"{path}.elements[{element_index}]"
            self._validate_element(element_path, element)
            if isinstance(element, dict):
                rect = self._element_rect(element)
                if rect is not None:
                    positioned_elements.append((element_path, element, rect))
            if isinstance(element, dict) and element.get("type") == "text":
                visible_chars += len(_visible_text(str(element.get("content", ""))))

        self._validate_overlaps(positioned_elements)
        if visible_chars > 420:
            self.warning(
                "slide.density",
                path,
                f"Slide contains approximately {visible_chars} visible characters; reduce copy or split the slide.",
            )
        if slide_index > 0 and not any(
            self._is_page_badge(element, slide_index + 1) for element in elements
        ):
            self.warning(
                "slide.page_badge",
                f"{path}.elements",
                f"Slide {slide_index + 1} has no detected bottom-right page number badge.",
            )
        if elements and all(
            isinstance(element, dict) and element.get("type") == "text" for element in elements
        ):
            self.warning(
                "slide.no_visual",
                path,
                "Content slide contains text only; add a chart, shape, image, table, or process visual.",
            )

        self.layout_signatures.append(self._layout_signature(elements))

    def _validate_element(self, path: str, element: Any) -> str | None:
        if not isinstance(element, dict):
            self.error("element.type", path, "Element must be an object.")
            return None

        element_type = element.get("type")
        if element_type not in ALLOWED_ELEMENT_TYPES:
            self.error(
                "element.type",
                f"{path}.type",
                f"Unsupported element type {element_type!r}; expected one of {sorted(ALLOWED_ELEMENT_TYPES)}.",
            )
            return None

        self.element_count += 1
        element_id = element.get("id")
        if not isinstance(element_id, str) or not element_id.strip():
            self.error("element.id", f"{path}.id", "Element id must be a non-empty stable string.")
        elif element_id in self.element_ids:
            self.error(
                "element.id_duplicate", f"{path}.id", f"Duplicate element id: {element_id!r}."
            )
        else:
            self.element_ids.add(element_id)
            if not ID_PATTERN.fullmatch(element_id):
                self.error(
                    "element.id_format",
                    f"{path}.id",
                    "Element id may contain only letters, digits, '.', ':', '_' and '-'.",
                )

        self._validate_frame(path, element, element_type)
        if element_type == "text":
            self._validate_text(path, element)
        elif element_type == "shape":
            self._validate_shape(path, element)
        elif element_type == "image":
            self._validate_required_string(path, element, "src")
        elif element_type == "chart":
            self._validate_chart(path, element)
        elif element_type == "table":
            self._validate_table(path, element)
        elif element_type == "line":
            self._validate_line(path, element)
        elif element_type == "latex":
            self._validate_required_string(path, element, "latex")
        return str(element_type)

    def _validate_frame(self, path: str, element: dict[str, Any], element_type: str) -> None:
        for key in ("left", "top"):
            if not _is_number(element.get(key)):
                self.error("element.frame", f"{path}.{key}", f"{key} must be a finite number.")

        if element_type == "line":
            return

        for key in ("width", "height"):
            value = element.get(key)
            if not _is_number(value) or float(value) <= 0:
                self.error("element.frame", f"{path}.{key}", f"{key} must be a positive number.")

        if all(_is_number(element.get(key)) for key in ("left", "top", "width", "height")):
            left = float(element["left"])
            top = float(element["top"])
            right = left + float(element["width"])
            bottom = top + float(element["height"])
            if left < 0 or top < 0 or right > CANVAS_WIDTH or bottom > CANVAS_HEIGHT:
                self.error(
                    "element.bounds",
                    path,
                    f"Element frame ({left:g}, {top:g}, {right:g}, {bottom:g}) exceeds the "
                    f"{CANVAS_WIDTH:g} x {CANVAS_HEIGHT:g} canvas.",
                )

    def _validate_text(self, path: str, element: dict[str, Any]) -> None:
        content = element.get("content")
        if not isinstance(content, str) or not _visible_text(content):
            self.error("text.content", f"{path}.content", "Text content must contain visible text.")
            return
        if RAW_NEWLINE_PATTERN.search(content):
            self.error(
                "text.raw_newline",
                f"{path}.content",
                "Use <br> or separate <p> elements instead of raw newline characters in HTML content.",
            )

        parser = TextMarkupParser()
        try:
            parser.feed(content)
            parser.close()
        except Exception as exc:
            self.error("text.html", f"{path}.content", f"Invalid HTML content: {exc}.")
            return

        for tag in parser.tags:
            if tag not in ALLOWED_TEXT_TAGS:
                self.error(
                    "text.html_tag",
                    f"{path}.content",
                    f"Unsupported or unsafe HTML tag <{tag}>; use the documented rich-text subset.",
                )
        for tag, attribute, value in parser.attributes:
            if attribute.startswith("on") or attribute in {"href", "src", "class", "id"}:
                self.error(
                    "text.html_attribute",
                    f"{path}.content",
                    f"Unsafe HTML attribute {attribute!r} on <{tag}> is not allowed.",
                )
            if attribute == "style":
                for declaration in value.split(";"):
                    if ":" not in declaration:
                        continue
                    property_name = declaration.split(":", 1)[0].strip().lower()
                    if property_name not in ALLOWED_STYLE_PROPERTIES:
                        self.error(
                            "text.style_property",
                            f"{path}.content",
                            f"Unsupported inline style property {property_name!r}.",
                        )

        sizes = [float(match.group(1)) for match in FONT_SIZE_PATTERN.finditer(content)]
        if not sizes:
            self.error(
                "text.font_size_missing",
                f"{path}.content",
                "Every text element must declare font-size in inline HTML style so preview and export agree.",
            )
        for size in sizes:
            if size < 10 or size > 120:
                self.warning(
                    "text.font_size_range",
                    f"{path}.content",
                    f"Font size {size:g}px is outside the recommended 10-120px range.",
                )

    def _validate_shape(self, path: str, element: dict[str, Any]) -> None:
        if not isinstance(element.get("path"), str) or not element["path"].strip():
            self.error("shape.path", f"{path}.path", "Shape must contain an SVG path.")
        view_box = element.get("viewBox")
        if (
            not isinstance(view_box, list)
            or len(view_box) < 2
            or not _is_number(view_box[0])
            or not _is_number(view_box[1])
            or float(view_box[0]) <= 0
            or float(view_box[1]) <= 0
        ):
            self.error(
                "shape.viewBox",
                f"{path}.viewBox",
                "Shape viewBox must contain positive width and height.",
            )

    def _validate_line(self, path: str, element: dict[str, Any]) -> None:
        valid_points = True
        for key in ("start", "end"):
            point = element.get(key)
            if (
                not isinstance(point, list)
                or len(point) != 2
                or not all(_is_number(value) for value in point)
            ):
                self.error("line.points", f"{path}.{key}", f"{key} must be a two-number point.")
                valid_points = False
        if valid_points:
            left = float(element["left"])
            top = float(element["top"])
            x_values = [left + float(element["start"][0]), left + float(element["end"][0])]
            y_values = [top + float(element["start"][1]), top + float(element["end"][1])]
            if (
                min(x_values) < 0
                or min(y_values) < 0
                or max(x_values) > CANVAS_WIDTH
                or max(y_values) > CANVAS_HEIGHT
            ):
                self.error(
                    "element.bounds",
                    path,
                    f"Line endpoints exceed the {CANVAS_WIDTH:g} x {CANVAS_HEIGHT:g} canvas.",
                )

    def _validate_chart(self, path: str, element: dict[str, Any]) -> None:
        data = element.get("data")
        if not isinstance(data, dict):
            self.error("chart.data", f"{path}.data", "Chart must contain a data object.")
            return
        labels = data.get("labels")
        series = data.get("series")
        if not isinstance(labels, list) or not labels:
            self.error(
                "chart.labels", f"{path}.data.labels", "Chart labels must be a non-empty array."
            )
        if (
            not isinstance(series, list)
            or not series
            or any(not isinstance(values, list) for values in series)
            or any(not _is_number(value) for values in series for value in values)
        ):
            self.error(
                "chart.series", f"{path}.data.series", "Chart series must contain numeric arrays."
            )

    def _validate_table(self, path: str, element: dict[str, Any]) -> None:
        data = element.get("data")
        if not isinstance(data, list) or not data or any(not isinstance(row, list) for row in data):
            self.error(
                "table.data",
                f"{path}.data",
                "Table data must be a non-empty two-dimensional array.",
            )
        col_widths = element.get("colWidths")
        if (
            not isinstance(col_widths, list)
            or not col_widths
            or any(not _is_number(value) or float(value) <= 0 for value in col_widths)
        ):
            self.error(
                "table.colWidths",
                f"{path}.colWidths",
                "Table colWidths must contain positive numbers.",
            )

    def _validate_required_string(self, path: str, element: dict[str, Any], key: str) -> None:
        if not isinstance(element.get(key), str) or not element[key].strip():
            self.error(f"element.{key}", f"{path}.{key}", f"{key} must be a non-empty string.")

    @staticmethod
    def _element_rect(element: dict[str, Any]) -> tuple[float, float, float, float] | None:
        if not all(_is_number(element.get(key)) for key in ("left", "top", "width", "height")):
            return None
        left = float(element["left"])
        top = float(element["top"])
        return left, top, left + float(element["width"]), top + float(element["height"])

    def _validate_overlaps(
        self,
        positioned_elements: list[tuple[str, dict[str, Any], tuple[float, float, float, float]]],
    ) -> None:
        for index, (path_a, element_a, rect_a) in enumerate(positioned_elements):
            for path_b, element_b, rect_b in positioned_elements[index + 1 :]:
                if self._is_background(element_a, rect_a) or self._is_background(element_b, rect_b):
                    continue
                if self._contains_surface(element_a, rect_a, rect_b) or self._contains_surface(
                    element_b, rect_b, rect_a
                ):
                    continue
                if {element_a.get("type"), element_b.get("type")} == {"shape", "text"}:
                    continue
                overlap = self._intersection_area(rect_a, rect_b)
                if overlap <= 0:
                    continue
                area_a = self._area(rect_a)
                area_b = self._area(rect_b)
                if overlap / max(min(area_a, area_b), 1.0) >= 0.55:
                    self.warning(
                        "layout.overlap",
                        path_a,
                        f"Large overlap with {path_b}; verify that the elements are intentionally layered.",
                    )

    @staticmethod
    def _is_background(element: dict[str, Any], rect: tuple[float, float, float, float]) -> bool:
        return (
            element.get("type") == "shape"
            and rect[0] <= 0
            and rect[1] <= 0
            and rect[2] >= CANVAS_WIDTH
            and rect[3] >= CANVAS_HEIGHT
        )

    @staticmethod
    def _contains_surface(
        element: dict[str, Any],
        container_rect: tuple[float, float, float, float],
        child_rect: tuple[float, float, float, float],
    ) -> bool:
        if element.get("type") != "shape":
            return False
        element_id = str(element.get("id", "")).lower()
        role = str(element.get("role", "")).lower()
        marked_surface = role in {"background", "surface", "container"} or element_id.endswith(
            ("-bg", "_bg", "-background", "_background")
        )
        return marked_surface and (
            container_rect[0] <= child_rect[0]
            and container_rect[1] <= child_rect[1]
            and container_rect[2] >= child_rect[2]
            and container_rect[3] >= child_rect[3]
        )

    @staticmethod
    def _area(rect: tuple[float, float, float, float]) -> float:
        return max(rect[2] - rect[0], 0) * max(rect[3] - rect[1], 0)

    @staticmethod
    def _intersection_area(
        rect_a: tuple[float, float, float, float], rect_b: tuple[float, float, float, float]
    ) -> float:
        width = max(min(rect_a[2], rect_b[2]) - max(rect_a[0], rect_b[0]), 0)
        height = max(min(rect_a[3], rect_b[3]) - max(rect_a[1], rect_b[1]), 0)
        return width * height

    @staticmethod
    def _is_page_badge(element: Any, page_number: int) -> bool:
        if not isinstance(element, dict) or element.get("type") != "text":
            return False
        if not _is_number(element.get("left")) or not _is_number(element.get("top")):
            return False
        if element["left"] < 850 or element["top"] < 480:
            return False
        content = _visible_text(str(element.get("content", "")))
        return content.isdigit() and int(content) == page_number

    @staticmethod
    def _layout_signature(elements: Any) -> tuple[Any, ...]:
        if not isinstance(elements, list):
            return ()
        signature: list[Any] = []
        for element in elements:
            if not isinstance(element, dict):
                continue
            signature.append(
                (
                    element.get("type"),
                    (
                        round(float(element.get("left", 0)) / CANVAS_WIDTH, 2)
                        if _is_number(element.get("left"))
                        else None
                    ),
                    (
                        round(float(element.get("top", 0)) / CANVAS_HEIGHT, 2)
                        if _is_number(element.get("top"))
                        else None
                    ),
                    (
                        round(float(element.get("width", 0)) / CANVAS_WIDTH, 2)
                        if _is_number(element.get("width"))
                        else None
                    ),
                    (
                        round(float(element.get("height", 0)) / CANVAS_HEIGHT, 2)
                        if _is_number(element.get("height"))
                        else None
                    ),
                )
            )
        return tuple(signature)


def _load_deck(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Deck file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Deck is not valid JSON: {exc}") from exc


def _print_report(path: Path, validator: SlideValidator, json_output: bool) -> None:
    if json_output:
        print(
            json.dumps(
                {
                    "path": str(path),
                    "ok": not validator.errors and (not validator.strict or not validator.warnings),
                    "slides": len(validator.slide_ids),
                    "elements": validator.element_count,
                    "errors": [asdict(issue) for issue in validator.errors],
                    "warnings": [asdict(issue) for issue in validator.warnings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    for issue in validator.issues:
        print(f"{issue.severity.upper()} {issue.path} [{issue.code}]: {issue.message}")
    warning_count = len(validator.warnings)
    print(
        f"Slide IR validation {'passed' if not validator.errors else 'failed'}: "
        f"{len(validator.slide_ids)} slides, {validator.element_count} elements, "
        f"{len(validator.errors)} errors, {warning_count} warnings."
    )
    if validator.strict and validator.warnings and not validator.errors:
        print("Strict mode failed because warnings are not allowed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("/workspace/artifacts/deck.slides.json"),
        help="Path to the Slide IR JSON (default: /workspace/artifacts/deck.slides.json)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat visual-quality warnings as failures.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit a machine-readable JSON report.",
    )
    args = parser.parse_args(argv)

    validator = SlideValidator(strict=args.strict)
    try:
        validator.validate(_load_deck(args.path))
    except ValueError as exc:
        validator.error("deck.read", str(args.path), str(exc))
    _print_report(args.path, validator, args.json_output)
    return 1 if validator.errors or (args.strict and validator.warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
