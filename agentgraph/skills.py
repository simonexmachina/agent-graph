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
    claude_destination: str | None
    overwritten: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "skill": self.skill,
            "target": self.target,
            "source": self.source,
            "destination": self.destination,
            "claude_destination": self.claude_destination,
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
        if not root.is_dir():
            continue
        for candidate in root.iterdir():
            if candidate.name == skill and (candidate / "SKILL.md").is_file():
                return candidate

    searched = ", ".join(str(root) for root in roots)
    raise SkillInstallError(f"Skill {skill!r} was not found. Searched: {searched}")


def _target_root(target: SkillTarget, project_dir: Path | None) -> Path:
    if target == "user":
        return Path.home() / ".agents" / "skills"
    if target == "project":
        return (project_dir or Path.cwd()) / ".agents" / "skills"
    raise SkillInstallError("Target must be 'user' or 'project'")


def _claude_target_root(target: SkillTarget, project_dir: Path | None) -> Path:
    if target == "user":
        return Path.home() / ".claude" / "skills"
    if target == "project":
        return (project_dir or Path.cwd()) / ".claude" / "skills"
    raise SkillInstallError("Target must be 'user' or 'project'")


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def install_skill(
    skill: str = "agentgraph",
    *,
    target: SkillTarget = "user",
    force: bool = False,
    claude: bool = True,
    source_root: Path | None = None,
    project_dir: Path | None = None,
) -> SkillInstallResult:
    """Copy a bundled skill and link it into Claude's skill directory by default."""
    source = _find_source_skill(skill, source_root)
    destination = _target_root(target, project_dir) / skill
    claude_destination = _claude_target_root(target, project_dir) / skill if claude else None
    overwritten = _path_exists(destination)

    if overwritten and not force:
        raise SkillInstallError(
            f"Skill {skill!r} already exists at {destination}. Use --force to overwrite it."
        )
    if claude_destination is not None and _path_exists(claude_destination) and not force:
        raise SkillInstallError(
            f"Claude skill link for {skill!r} already exists at {claude_destination}. "
            "Use --force to overwrite it."
        )

    if overwritten:
        _remove_path(destination)
    if claude_destination is not None and _path_exists(claude_destination):
        _remove_path(claude_destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    if claude_destination is not None:
        claude_destination.parent.mkdir(parents=True, exist_ok=True)
        claude_destination.symlink_to(destination, target_is_directory=True)

    return SkillInstallResult(
        skill=skill,
        target=target,
        source=str(source),
        destination=str(destination),
        claude_destination=str(claude_destination) if claude_destination is not None else None,
        overwritten=overwritten,
    )
