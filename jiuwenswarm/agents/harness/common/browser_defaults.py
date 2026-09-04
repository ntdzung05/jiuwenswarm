"""Shared JiuwenSwarm defaults and Skill wiring for the browser sub-agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openjiuwen.harness.rails import SkillUseRail
from openjiuwen.harness.skills import collect_disabled_skills


DEFAULT_BROWSER_AGENT_MAX_ITERATIONS = 100


def normalize_browser_agent_skill_names(browser_agent_config: Any) -> list[str]:
    """Return the browser child's explicitly configured Skill names.

    The browser child has its own Skill scope.  Only
    ``react.subagents.browser_agent.skills`` is considered here; parent-agent
    selection and per-turn ``skills_to_use`` are deliberately not inherited.
    Names are exact, trimmed, and de-duplicated while preserving config order.
    """

    if not isinstance(browser_agent_config, dict):
        return []
    raw_names = browser_agent_config.get("skills")
    if isinstance(raw_names, str):
        candidates: list[Any] = [raw_names]
    elif isinstance(raw_names, (list, tuple)):
        candidates = list(raw_names)
    else:
        return []

    names: list[str] = []
    seen: set[str] = set()
    for raw_name in candidates:
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def configured_browser_agent_skill_names(config: Any) -> list[str]:
    """Return child-only Skill names from a full or ``react`` config mapping.

    The same names are used in two opposite directions: they form the browser
    child's exact allow-list and a transient deny-list on its parent.  Keeping
    the lookup here prevents the direct and team assembly paths from drifting.
    The deny-list is deliberately never persisted to ``skills_state.json``;
    that file is the library-wide kill switch and also governs the child.
    """

    if not isinstance(config, dict):
        return []
    react = config.get("react")
    react_config = react if isinstance(react, dict) else config
    subagents = react_config.get("subagents")
    if not isinstance(subagents, dict):
        return []
    return normalize_browser_agent_skill_names(subagents.get("browser_agent"))


def compose_parent_disabled_skill_names(
    config: Any,
    disabled_skills: Any = None,
) -> list[str]:
    """Combine library kill switches with browser-child-only routing denies.

    Browser Skills remain installed in the shared library so the browser child
    can load them, but every parent-facing Skill workflow must treat their
    configured names as disabled.  This helper keeps that deny list transient:
    callers use it for live rails and discovery only and never write it to
    ``skills_state.json``.
    """

    if isinstance(disabled_skills, str):
        candidates = [disabled_skills]
    else:
        try:
            candidates = list(disabled_skills or ())
        except TypeError:
            candidates = []

    disabled = {
        str(name).strip()
        for name in candidates
        if str(name).strip()
    }
    disabled.update(configured_browser_agent_skill_names(config))
    return sorted(disabled)


class BrowserAgentSkillUseRail(SkillUseRail):
    """Exact browser-child Skill scope with a live library kill switch.

    Browser sub-agent configs are reusable blueprints.  Re-read the shared
    disabled state both when a child is materialized and when a persistent
    child starts another invocation, instead of freezing the state that was
    present when its parent was assembled.
    """

    def __init__(self, skills_root: str | Path, skill_names: list[str]) -> None:
        self._browser_skills_root = str(skills_root)
        self._browser_skill_names = normalize_browser_agent_skill_names(
            {"skills": skill_names}
        )
        super().__init__(
            skills_dir=self._browser_skills_root,
            skill_mode=SkillUseRail.SKILL_MODE_ALL,
            enabled_skills=self._browser_skill_names,
            disabled_skills=self._load_library_disabled_skills() or None,
            include_tools=False,
        )

    def _load_library_disabled_skills(self) -> list[str]:
        return collect_disabled_skills([self._browser_skills_root])

    def clone_for_agent(self) -> "BrowserAgentSkillUseRail":
        return type(self)(
            self._browser_skills_root,
            list(self._browser_skill_names),
        )

    async def before_invoke(self, ctx: Any) -> None:
        self.disabled_skills = self._normalize_name_set(
            self._load_library_disabled_skills()
        )
        await super().before_invoke(ctx)


def build_browser_agent_skill_rail(
    skills_root: str | Path,
    skill_names: list[str],
) -> SkillUseRail | None:
    """Build a browser-child-only Skill rail for an explicit allow-list.

    ``include_tools=False`` keeps Skill loading from adding filesystem or shell
    tools to the browser worker.  The library-wide disabled state always wins
    over the configured allow-list.
    """

    names = normalize_browser_agent_skill_names({"skills": skill_names})
    if not names:
        return None

    return BrowserAgentSkillUseRail(skills_root, names)


__all__ = [
    "DEFAULT_BROWSER_AGENT_MAX_ITERATIONS",
    "BrowserAgentSkillUseRail",
    "build_browser_agent_skill_rail",
    "compose_parent_disabled_skill_names",
    "configured_browser_agent_skill_names",
    "normalize_browser_agent_skill_names",
]
