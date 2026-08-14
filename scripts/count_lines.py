#!/usr/bin/env python3
"""Count source and configuration lines in the repository.

The default count includes the current working tree, including untracked files,
while excluding dependencies, caches, runtime data, reports, and documentation.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


LANGUAGES = {
    ".css": "CSS",
    ".js": "JavaScript",
    ".json": "JSON",
    ".mjs": "JavaScript",
    ".py": "Python",
    ".sh": "Shell",
    ".sql": "SQL",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".yaml": "YAML",
    ".yml": "YAML",
}

SPECIAL_FILES = {
    "Dockerfile": "Dockerfile",
    "Makefile": "Makefile",
}

EXCLUDED_DIRECTORIES = {
    ".git",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "data",
    "dist",
    "node_modules",
    "reports",
    "venv",
}

EXCLUDED_FILES = {
    ".coverage",
    "package-lock.json",
}


@dataclass
class Counts:
    files: int = 0
    physical: int = 0
    blank: int = 0

    @property
    def code(self) -> int:
        return self.physical - self.blank

    def add(self, other: "Counts") -> None:
        self.files += other.files
        self.physical += other.physical
        self.blank += other.blank


def language_for(path: Path) -> str | None:
    if path.name in SPECIAL_FILES:
        return SPECIAL_FILES[path.name]
    if path.name in EXCLUDED_FILES:
        return None
    return LANGUAGES.get(path.suffix.lower())


def count_file(path: Path) -> Counts:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return Counts(files=1, physical=len(lines), blank=sum(not line.strip() for line in lines))


def collect_counts(root: Path) -> dict[str, Counts]:
    counts: dict[str, Counts] = defaultdict(Counts)
    for path in root.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_DIRECTORIES for part in path.parts):
            continue
        language = language_for(path)
        if language is not None:
            counts[language].add(count_file(path))
    return counts


def print_report(counts: dict[str, Counts]) -> None:
    total = Counts()
    print(f"{'Language':<12} {'Files':>7} {'lines':>10}")
    print("-" * 32)
    for language in sorted(counts):
        current = counts[language]
        total.add(current)
        print(f"{language:<12} {current.files:>7,} {current.physical:>10,}")
    print("-" * 32)
    print(f"{'Total':<12} {total.files:>7,} {total.physical:>10,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root to scan (default: this script's repository)",
    )
    args = parser.parse_args()
    print_report(collect_counts(args.root.resolve()))


if __name__ == "__main__":
    main()
