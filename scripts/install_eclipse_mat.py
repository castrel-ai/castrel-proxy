#!/usr/bin/env python3
"""Mirror the Eclipse MAT update-site into a local MAT_HOME directory."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen


ENTRY_PATTERN = re.compile(
    r"<tr>.*?fa-(folder|file-text-o).*?<a href=['\"]([^'\"]+)['\"]>.*?</a>.*?</tr>",
    re.IGNORECASE,
)
FALLBACK_LAUNCHER_VERSIONS = ("1.7.100", "1.7.0", "1.6.1000", "1.6.900")


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "castrel-proxy-mat-installer/1.0"})
    with urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "ignore")


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "castrel-proxy-mat-installer/1.0"})
    with urlopen(request, timeout=120) as response:
        return response.read()


def list_entries(url: str) -> list[tuple[str, bool]]:
    html = fetch_text(url)
    entries: list[tuple[str, bool]] = []
    seen: set[str] = set()

    for kind, href in ENTRY_PATTERN.findall(html):
        if href in seen:
            continue
        seen.add(href)

        absolute = urljoin(url, href)
        is_dir = kind.lower() == "folder"
        entries.append((absolute, is_dir))

    return entries


def relative_path(root_path: str, entry_url: str) -> Path:
    parsed = urlparse(entry_url)
    query_file = parse_qs(parsed.query).get("file", [None])[0]
    raw_path = query_file or parsed.path

    if raw_path.startswith(root_path):
        raw_path = raw_path[len(root_path) :]
    else:
        raw_path = raw_path.rsplit("/", 1)[-1]

    return Path(raw_path.lstrip("/"))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_launcher(plugins_dir: Path) -> Path | None:
    existing = next(plugins_dir.glob("org.eclipse.equinox.launcher_*.jar"), None)
    if existing is not None:
        return existing

    for version in FALLBACK_LAUNCHER_VERSIONS:
        jar_name = f"org.eclipse.equinox.launcher_{version}.jar"
        jar_url = (
            "https://repo1.maven.org/maven2/org/eclipse/platform/"
            f"org.eclipse.equinox.launcher/{version}/org.eclipse.equinox.launcher-{version}.jar"
        )
        try:
            (plugins_dir / jar_name).write_bytes(fetch_bytes(jar_url))
            return plugins_dir / jar_name
        except Exception:
            continue

    return None


def download_tree(root_url: str, destination: Path) -> None:
    parsed_root = urlparse(root_url)
    root_path = parsed_root.path if parsed_root.path.endswith("/") else f"{parsed_root.path}/"

    queue: list[str] = [root_url]
    visited: set[str] = set()

    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)

        for entry_url, is_dir in list_entries(current):
            rel_path = relative_path(root_path, entry_url)
            if not rel_path.parts:
                continue
            if rel_path.parts[-1] == "..":
                continue

            target = destination / rel_path
            if is_dir:
                target.mkdir(parents=True, exist_ok=True)
                queue.append(f"{entry_url.rstrip('/')}/")
                continue

            ensure_parent(target)
            target.write_bytes(fetch_bytes(entry_url))


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default="https://download.eclipse.org/mat/latest/update-site/",
        help="Eclipse MAT update-site URL",
    )
    parser.add_argument(
        "--output",
        default="/opt/eclipse-mat",
        help="Directory to populate as MAT_HOME",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    destination = Path(args.output).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    download_tree(args.source.rstrip("/") + "/", destination)

    plugins_dir = destination / "plugins"
    if not plugins_dir.is_dir():
        print(f"MAT installation is incomplete: missing {plugins_dir}", file=sys.stderr)
        return 1

    launcher = ensure_launcher(plugins_dir)
    if launcher is None:
        print("MAT installation is incomplete: launcher jar not found", file=sys.stderr)
        return 1

    print(f"Installed Eclipse MAT update-site into {destination}")
    print(f"Detected launcher: {launcher.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
