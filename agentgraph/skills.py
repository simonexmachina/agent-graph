"""Install bundled AgentGraph skills into an agent skill directory."""

from __future__ import annotations

import shutil
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SkillTarget = Literal["user", "project"]


class SkillInstallError(ValueError):
    """Raised when a skill cannot be installed."""


@dataclass(frozen=True)
class SkillInstallResult:
    skill: str
    target: SkillTarget
    source: str
    destination: str
    overwritten: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "skill": self.skill,
            "target": self.target,
            "source": self.source,
            "destination": self.destination,
            "overwritten": self.overwritten,
        }


def _bundled_skill_roots() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    return [
        repo_root / ".agents" / "skills",
        Path(sysconfig.get_path("data")) / ".agents" / "skills",
    ]


def _find_source_skill(skill: str, source_root: Path | None) -> Path:
    roots = [source_root] if source_root is not None else _bundled_skill_roots()
    for root in roots:
        candidate = root / skill
        if (candidate / "SKILL.md").is_file():
            return candidate

    searched = ", ".join(str(root) for root in roots)
    raise SkillInstallError(f"Skill {skill!r} was not found. Searched: {searched}")


def _target_root(target: SkillTarget, project_dir: Path | None) -> Path:
    if target == "user":
        return Path.home() / ".agents" / "skills"
    if target == "project":
        return (project_dir or Path.cwd()) / ".agents" / "skills"
    raise SkillInstallError("Target must be 'user' or 'project'")


def install_skill(
    skill: str = "graph",
    *,
    target: SkillTarget = "user",
    force: bool = False,
    source_root: Path | None = None,
    project_dir: Path | None = None,
) -> SkillInstallResult:
    """Copy a bundled skill into the selected user or project skill directory."""
    source = _find_source_skill(skill, source_root)
    destination = _target_root(target, project_dir) / skill
    overwritten = destination.exists()

    if overwritten and not force:
        raise SkillInstallError(
            f"Skill {skill!r} already exists at {destination}. Use --force to overwrite it."
        )

    if overwritten:
        shutil.rmtree(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)

    return SkillInstallResult(
        skill=skill,
        target=target,
        source=str(source),
        destination=str(destination),
        overwritten=overwritten,
    )
