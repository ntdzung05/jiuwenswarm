# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Unit tests for the swarm member-skill visibility provider.

Skills live in exactly one physical library and a member's view of it is
metadata (``skills-visibility.json`` at the member workspace root), not a
materialized directory of symlinks. These tests call the provider helpers
directly (no customizer, no live ``DeepAgent``) and cover:

* the swarm side never writes the document — seeding has exactly one owner,
  openjiuwen's team Skill rail (D1: the file is the authority, config is only
  its seed),
* the composed effective view is ``member.allow | team.allow`` for enabled and
  ``member.deny | team.deny | global disabled`` for disabled (D6),
* an empty ``allow`` list means "inherit the whole library" rather than "deny
  everything", matching ``SkillUseRail._filter_skills``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from openjiuwen.agent_teams.skill import (
    SCOPE_MEMBER,
    SCOPE_TEAM,
    SkillVisibility,
    compose_skill_visibility,
    read_skill_visibility,
    set_skill_visibility,
)

from jiuwenswarm.agents.swarm.context import SwarmBuildContext
from jiuwenswarm.agents.swarm.providers import skills

logger = logging.getLogger(__name__)


def _make_context(
    tmp_path: Path,
    *,
    member_name: str = "coder",
    team_id: str = "unit-team",
    config: dict | None = None,
) -> SwarmBuildContext:
    """Build a context whose member workspace lives under *tmp_path*."""
    member_root = tmp_path / "workspaces" / f"{member_name}_workspace"
    member_root.mkdir(parents=True, exist_ok=True)
    team_root = tmp_path / "team-workspace"
    team_root.mkdir(parents=True, exist_ok=True)
    return SwarmBuildContext(
        team_id=team_id,
        team_ws_root=str(team_root),
        team_skill_visibility_path=str(team_root / "skills-visibility.json"),
        global_skills_dir=str(tmp_path / "library"),
        member_name=member_name,
        workspace=SimpleNamespace(root_path=str(member_root)),
        config=config,
    )


def test_member_skill_toolkit_provider_writes_no_visibility_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The toolkit provider never seeds: the team Skill rail is the sole seeder.

    Two writers of the same document would contend for its lock on every build
    and their skip rules would drift apart, so this pins that the swarm side
    only reads the path.
    """
    context = _make_context(tmp_path)
    visibility_path = Path(context.resolve_member_skill_visibility_path())
    monkeypatch.setattr(skills, "SkillManager", lambda workspace_dir: object())

    rail = skills.build_member_skill_toolkit({"skills": ["alpha"]}, context)

    assert rail is not None
    assert not visibility_path.exists()
    logger.info(f"no document seeded at {visibility_path}")


def test_member_skill_toolkit_input_takes_no_seed_param() -> None:
    """The seed allow-list is not an input of the toolkit rail any more."""
    assert "skills" not in skills.MemberSkillToolkitInput.model_fields
    assert not hasattr(skills, "bootstrap_member_skill_visibility")


def test_member_visibility_path_is_a_method_and_team_path_a_field(
    tmp_path: Path,
) -> None:
    """The two visibility paths differ in shape on purpose.

    ``team_skill_visibility_path`` is a per-team value carried on the context,
    while the member path can only be derived once the per-member view is
    filled in. The method name says so, so a consumer cannot hand the bound
    method to ``Path()`` by mistake.
    """
    context = _make_context(tmp_path)

    assert isinstance(context.team_skill_visibility_path, str)
    assert callable(context.resolve_member_skill_visibility_path)
    resolved = context.resolve_member_skill_visibility_path()
    assert isinstance(resolved, str)
    assert Path(resolved).name == "skills-visibility.json"
    # The field-shaped one must not be callable; the method-shaped one must not
    # be mistakable for a value.
    assert not callable(context.team_skill_visibility_path)


def test_compose_skill_visibility_unions_allow_and_prefers_deny() -> None:
    """Enabled is the allow union; deny wins over allow and adds the global list."""
    member = SkillVisibility(
        scope=SCOPE_MEMBER,
        id="coder",
        allow=["alpha", "shared"],
        deny=["member-denied"],
    )
    team = SkillVisibility(
        scope=SCOPE_TEAM,
        id="unit-team",
        allow=["beta", "shared"],
        deny=["team-denied"],
    )

    enabled, disabled = compose_skill_visibility(member, team, ["globally-disabled"])

    assert enabled == {"alpha", "beta", "shared"}
    assert disabled == {"member-denied", "team-denied", "globally-disabled"}


def test_compose_skill_visibility_keeps_empty_allow_empty() -> None:
    """An empty allow union stays empty so later library additions stay visible."""
    member = SkillVisibility(scope=SCOPE_MEMBER, id="coder")
    team = SkillVisibility(scope=SCOPE_TEAM, id="unit-team")

    enabled, disabled = compose_skill_visibility(member, team, None)

    assert enabled == set()
    assert disabled == set()


def test_member_visibility_provider_composes_member_team_and_global(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live provider unions both documents and adds the global disabled list."""
    context = _make_context(tmp_path)
    member_path = Path(context.resolve_member_skill_visibility_path())
    team_path = Path(context.team_skill_visibility_path)
    set_skill_visibility(
        member_path,
        scope=SCOPE_MEMBER,
        entity_id="coder",
        allow=["alpha"],
        deny=["gamma"],
    )
    set_skill_visibility(
        team_path,
        scope=SCOPE_TEAM,
        entity_id="unit-team",
        allow=["beta"],
        deny=[],
    )
    monkeypatch.setattr(skills, "_load_global_disabled_skills", lambda: ["blocked"])

    provider = skills.build_member_skill_visibility_provider(context)
    enabled, disabled = provider()

    assert enabled == {"alpha", "beta"}
    assert disabled == {"gamma", "blocked"}
    # The metadata files are part of the rail's snapshot signature.
    signed_paths = {entry[0] for entry in provider.metadata_signature()}
    assert signed_paths == {str(member_path), str(team_path)}


def test_browser_child_skill_is_transiently_denied_across_team_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The team parent excludes browser Skills without persisting a deny."""

    context = _make_context(
        tmp_path,
        config={
            "react": {
                "subagents": {
                    "browser_agent": {"skills": ["browser-task"]},
                }
            }
        },
    )
    member_path = Path(context.resolve_member_skill_visibility_path())
    set_skill_visibility(
        member_path,
        scope=SCOPE_MEMBER,
        entity_id="coder",
        allow=["alpha", "browser-task"],
        deny=[],
    )
    monkeypatch.setattr(skills, "_load_global_disabled_skills", lambda: ["blocked"])
    monkeypatch.setattr(skills, "get_config", lambda: context.config)

    provider = skills.build_member_skill_visibility_provider(context)
    enabled, disabled = provider()

    assert enabled == {"alpha", "browser-task"}
    assert disabled == {"blocked", "browser-task"}
    persisted = read_skill_visibility(
        member_path,
        scope=SCOPE_MEMBER,
        entity_id="coder",
    )
    assert persisted.deny == []


def test_actual_team_skill_rail_uses_parent_exclusion_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered rail behavior agrees with list/retrieval visibility."""

    library = tmp_path / "library"
    for name in ("alpha", "browser-task"):
        skill_dir = library / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\ndescription: {name}\n---\n",
            encoding="utf-8",
        )
    context = _make_context(
        tmp_path,
        config={
            "react": {
                "subagents": {
                    "browser_agent": {"skills": ["browser-task"]},
                }
            }
        },
    )
    monkeypatch.setattr(skills, "_load_global_disabled_skills", list)
    monkeypatch.setattr(skills, "get_config", lambda: context.config)

    rail = skills.build_member_team_skill_use_rail(
        {
            "member_visibility_path": context.resolve_member_skill_visibility_path(),
            "team_visibility_path": context.team_skill_visibility_path,
            "member_name": context.member_name,
            "team_name": context.team_id,
            "skills_dir": [str(library)],
            "bootstrap_allow": [],
            "skill_mode": "all",
            "include_tools": False,
        },
        context,
    )

    assert rail is not None
    assert rail.disabled_skills == {"browser-task"}
    enabled, disabled = rail.visibility_provider()
    assert enabled == set()
    assert disabled == {"browser-task"}


def test_team_skill_rail_tracks_live_browser_child_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One live rail adopts additions and removals from config hot reloads."""

    library = tmp_path / "library"
    for name in ("browser-old", "browser-new"):
        skill_dir = library / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\ndescription: {name}\n---\n",
            encoding="utf-8",
        )

    current_config = {
        "value": {
            "react": {
                "subagents": {
                    "browser_agent": {"skills": ["browser-old"]},
                }
            }
        }
    }
    context = _make_context(tmp_path, config=current_config["value"])
    monkeypatch.setattr(skills, "_load_global_disabled_skills", list)
    monkeypatch.setattr(skills, "get_config", lambda: current_config["value"])

    rail = skills.build_member_team_skill_use_rail(
        {
            "member_visibility_path": context.resolve_member_skill_visibility_path(),
            "team_visibility_path": context.team_skill_visibility_path,
            "member_name": context.member_name,
            "team_name": context.team_id,
            "skills_dir": [str(library)],
            "bootstrap_allow": [],
            "skill_mode": "all",
            "include_tools": False,
        },
        context,
    )

    assert rail is not None
    assert rail.disabled_skills == {"browser-old"}

    current_config["value"] = {
        "react": {
            "subagents": {
                "browser_agent": {"skills": ["browser-new"]},
            }
        }
    }
    rail._apply_visibility()
    assert rail.disabled_skills == {"browser-new"}

    current_config["value"] = {
        "react": {"subagents": {"browser_agent": {"skills": []}}}
    }
    rail._apply_visibility()
    assert rail.disabled_skills == set()


def test_member_visibility_provider_reflects_revocation_without_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A metadata edit takes effect on the next provider call, no rebuild needed."""
    context = _make_context(tmp_path)
    member_path = Path(context.resolve_member_skill_visibility_path())
    set_skill_visibility(
        member_path,
        scope=SCOPE_MEMBER,
        entity_id="coder",
        allow=["alpha", "beta"],
        deny=[],
    )
    monkeypatch.setattr(skills, "_load_global_disabled_skills", list)

    provider = skills.build_member_skill_visibility_provider(context)
    assert provider()[0] == {"alpha", "beta"}

    set_skill_visibility(
        member_path,
        scope=SCOPE_MEMBER,
        entity_id="coder",
        allow=["alpha"],
        deny=["beta"],
    )

    enabled, disabled = provider()
    assert enabled == {"alpha"}
    assert disabled == {"beta"}


def test_member_visibility_provider_without_identity_returns_none() -> None:
    """A context with neither workspace nor (team, member) identity has no provider."""
    context = SwarmBuildContext()

    assert skills.build_member_skill_visibility_provider(context) is None


def test_missing_member_document_is_fully_permissive(tmp_path: Path) -> None:
    """A missing document must never strip an agent of every Skill."""
    visibility = read_skill_visibility(
        tmp_path / "skills-visibility.json",
        scope=SCOPE_MEMBER,
        entity_id="coder",
    )

    assert visibility.is_unrestricted
    assert visibility.allow == []
    assert visibility.deny == []
