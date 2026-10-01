#!/usr/bin/env python3
"""Generate the dynamic sections of README.md from version.json and update.json."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
VERSION_FILE = ROOT / "version.json"
UPDATE_FILE = ROOT / "update.json"

VERSION_START = "<!-- VERSION:START -->"
VERSION_END = "<!-- VERSION:END -->"
UPDATES_START = "<!-- UPDATES:START -->"
UPDATES_END = "<!-- UPDATES:END -->"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def version_tuple(version: str) -> tuple[int, ...]:
    values = re.findall(r"\d+", str(version).strip().lstrip("v"))
    if not values:
        return (0, 0, 0, 0)
    result = tuple(int(value) for value in values)
    return result + (0,) * max(0, 4 - len(result))


def render_version(data: dict) -> str:
    version = str(data.get("version", "0.0.0"))
    patch = data.get("patch", 0)
    if patch:
        version = f"{version}.{patch}(beta{patch})"
    return f"{VERSION_START}\n**Version actuelle : `{version}`**\n{VERSION_END}"


def render_updates(data: dict) -> str:
    releases = data.get("versions", [])
    releases = sorted(
        releases,
        key=lambda item: version_tuple(item.get("version", "0.0.0")),
        reverse=True,
    )

    lines = [UPDATES_START]
    if not releases:
        lines.append("_Aucune mise à jour publiée pour le moment._")
    else:
        for release in releases:
            version = release.get("version", "?")
            date = release.get("date", "")
            title = release.get("title", "")
            heading = f"Version `{version}`"
            if date:
                heading += f" — {date}"
            if title:
                heading += f" · **{title}**"

            lines.append("<details>")
            lines.append(f"<summary>{heading}</summary>")
            lines.append("")
            for change in release.get("changes", []):
                lines.append(f"- {change}")
            lines.append("")
            lines.append("</details>")
            lines.append("")
    lines.append(UPDATES_END)
    return "\n".join(lines)


def replace_section(text: str, start: str, end: str, replacement: str) -> str:
    pattern = rf"{start}.*?{end}"
    if not re.search(pattern, text, flags=re.DOTALL):
        raise RuntimeError(f"Marqueurs manquants dans README.md: {start} / {end}")
    return re.sub(
        pattern,
        replacement,
        text,
        flags=re.DOTALL,
    )


def main() -> None:
    version = load_json(VERSION_FILE)
    updates = load_json(UPDATE_FILE)
    readme = README.read_text(encoding="utf-8")

    readme = replace_section(readme, VERSION_START, VERSION_END, render_version(version))
    readme = replace_section(readme, UPDATES_START, UPDATES_END, render_updates(updates))

    README.write_text(readme, encoding="utf-8")
    print(f"README.md généré depuis {VERSION_FILE.name} et {UPDATE_FILE.name}.")


if __name__ == "__main__":
    main()
