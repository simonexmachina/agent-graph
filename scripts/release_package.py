from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TAG_PREFIX = "agentgraph-"
TAG_VERSION_SEPARATOR = "-v"


@dataclass(frozen=True)
class ReleaseProject:
    name: str
    version: str
    path: Path


def project_paths(root: Path) -> list[Path]:
    return [root / "pyproject.toml", *sorted((root / "packages").glob("*/pyproject.toml"))]


def load_projects(root: Path) -> dict[str, ReleaseProject]:
    projects: dict[str, ReleaseProject] = {}
    for path in project_paths(root):
        with path.open("rb") as file:
            data: dict[str, Any] = tomllib.load(file)
        project = data["project"]
        name = str(project["name"])
        if name in projects:
            raise ValueError(f"Duplicate release project name: {name}")
        projects[name] = ReleaseProject(name=name, version=str(project["version"]), path=path)
    return projects


def parse_release_tag(tag: str) -> tuple[str, str]:
    package, separator, version = tag.rpartition(TAG_VERSION_SEPARATOR)
    if not separator or not package.startswith(TAG_PREFIX) or not version:
        raise ValueError(
            "Release tags must use the form agentgraph-<package>-v<version>: " f"{tag!r}"
        )
    return package, version


def resolve_release(tag: str, projects: dict[str, ReleaseProject]) -> ReleaseProject:
    package, version = parse_release_tag(tag)
    project = projects.get(package)
    if project is None:
        raise ValueError(f"Release tag refers to an unknown package: {package}")
    if project.version != version:
        raise ValueError(
            f"Release tag version {version!r} does not match {package} version {project.version!r}"
        )
    return project


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        print("Usage: release_package.py <release-tag>", file=sys.stderr)
        return 2

    try:
        project = resolve_release(arguments[0], load_projects(ROOT))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    print(f"package={project.name}")
    print(f"version={project.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
