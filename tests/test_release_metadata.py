from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.5.0"


def _project(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        data = tomllib.load(file)
    return data["project"]  # type: ignore[no-any-return]


def test_release_projects_use_public_names_and_matching_versions() -> None:
    root_project = _project(ROOT / "pyproject.toml")
    assert root_project["name"] == "agentgraph-server"
    assert root_project["version"] == VERSION

    connector_projects = [
        _project(path) for path in sorted((ROOT / "packages").glob("*/pyproject.toml"))
    ]
    assert len(connector_projects) == 5
    assert all(project["name"].startswith("agentgraph-connector-") for project in connector_projects)
    assert all(project["version"] == VERSION for project in connector_projects)
    connector_requirements = {
        requirement.split(">=", maxsplit=1)[0]
        for requirement in root_project["optional-dependencies"]["all"]
    }
    assert connector_requirements == {project["name"] for project in connector_projects}


def test_connectors_require_the_matching_agent_graph_release_line() -> None:
    for path in sorted((ROOT / "packages").glob("*/pyproject.toml")):
        project = _project(path)
        assert "agentgraph-server>=0.5.0,<0.6" in project["dependencies"]
