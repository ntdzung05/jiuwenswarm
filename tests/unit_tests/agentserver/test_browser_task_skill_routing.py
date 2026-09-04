# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Focused routing tests for browser-child-only Skills."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from openjiuwen.core.runner.runner import Runner
from openjiuwen.core.single_agent.rail.base import AgentCallbackContext
from openjiuwen.core.sys_operation import LocalWorkConfig, OperationMode, SysOperationCard
from openjiuwen.harness.prompts.builder import SystemPromptBuilder
from openjiuwen.harness.rails import SkillUseRail

from jiuwenswarm.agents.harness.common import browser_defaults
from jiuwenswarm.common import utils
from jiuwenswarm.server.runtime.agent_adapter import interface_code
from jiuwenswarm.server.runtime.agent_adapter import interface_deep
from jiuwenswarm.server.runtime.agent_adapter.interface_code import (
    JiuwenSwarmCodeAdapter,
)
from jiuwenswarm.server.runtime.agent_adapter.interface_deep import (
    JiuWenSwarmDeepAdapter,
)


_REACT_CONFIG = {
    "subagents": {
        "browser_agent": {
            "enabled": True,
            "skills": [" browser-task ", "browser-task", "browser-extra", 1],
        }
    }
}


def test_browser_skill_names_normalize_from_full_or_react_config() -> None:
    expected = ["browser-task", "browser-extra"]

    assert browser_defaults.configured_browser_agent_skill_names(_REACT_CONFIG) == expected
    assert browser_defaults.configured_browser_agent_skill_names(
        {"react": _REACT_CONFIG}
    ) == expected
    assert browser_defaults.configured_browser_agent_skill_names({}) == []


def test_browser_child_rail_is_an_exact_allow_list_with_library_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        browser_defaults,
        "collect_disabled_skills",
        lambda roots: ["browser-extra"],
    )

    rail = browser_defaults.build_browser_agent_skill_rail(
        "X:/shared-skills",
        ["browser-task", "browser-extra", "browser-task"],
    )

    assert isinstance(rail, SkillUseRail)
    assert rail.skills_dir == "X:/shared-skills"
    assert rail.skill_mode == SkillUseRail.SKILL_MODE_ALL
    assert rail.enabled_skills == {"browser-task", "browser-extra"}
    assert rail.disabled_skills == {"browser-extra"}
    assert rail.include_tools is False


def test_browser_child_clone_reloads_library_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled_states = iter([[], ["browser-task"]])
    monkeypatch.setattr(
        browser_defaults,
        "collect_disabled_skills",
        lambda roots: next(disabled_states),
    )

    blueprint = browser_defaults.build_browser_agent_skill_rail(
        "X:/shared-skills",
        ["browser-task"],
    )
    assert blueprint is not None
    materialized = blueprint.clone_for_agent()

    assert materialized is not blueprint
    assert materialized.enabled_skills == {"browser-task"}
    assert materialized.disabled_skills == {"browser-task"}
    assert materialized.include_tools is False


@pytest.mark.asyncio
async def test_materialized_browser_child_can_load_skill_and_relative_reference(
    tmp_path,
) -> None:
    skills_root = utils.get_builtin_skills_dir()
    blueprint = browser_defaults.build_browser_agent_skill_rail(
        skills_root,
        ["browser-task"],
    )
    assert blueprint is not None
    rail = blueprint.clone_for_agent()

    card = SysOperationCard(
        id=f"browser_task_skill_test_{tmp_path.name}",
        mode=OperationMode.LOCAL,
        work_config=LocalWorkConfig(work_dir=str(skills_root)),
    )
    Runner.resource_mgr.add_sys_operation(card)
    rail.set_sys_operation(Runner.resource_mgr.get_sys_operation(card.id))

    class _Abilities:
        def __init__(self) -> None:
            self.cards: dict[str, object] = {}
            self.tools: dict[str, object] = {}

        def get(self, name: str) -> object | None:
            return self.cards.get(name)

        def add_ability(self, tool_card: object, tool: object) -> SimpleNamespace:
            name = str(getattr(tool_card, "name"))
            self.cards[name] = tool_card
            self.tools[name] = tool
            return SimpleNamespace(added=True)

    class _Session:
        def __init__(self) -> None:
            self.state: dict[str, object] = {}

        def get_state(self, key: str) -> object | None:
            return self.state.get(key)

        def update_state(self, values: dict[str, object]) -> None:
            self.state.update(values)

    abilities = _Abilities()
    agent = SimpleNamespace(
        ability_manager=abilities,
        system_prompt_builder=SystemPromptBuilder(language="en"),
        prompt_attachment_manager=None,
        card=SimpleNamespace(id="browser-child"),
        deep_config=SimpleNamespace(enable_read_image_multimodal=False),
    )
    rail.init(agent)
    session = _Session()
    await rail.before_invoke(AgentCallbackContext(agent=agent, session=session))

    skill_tool = abilities.tools["skill_tool"]
    skill_result = await skill_tool.invoke(
        {"skill_name": "browser-task"},
        session=session,
    )
    reference_result = await skill_tool.invoke(
        {
            "skill_name": "browser-task",
            "relative_file_path": "references/tool-contract.md",
        },
        session=session,
    )

    assert skill_result.success is True
    assert "# Browser Task" in skill_result.data["skill_content"]
    assert reference_result.success is True
    assert "# Browser Tool Contract" in reference_result.data["skill_content"]


@pytest.mark.asyncio
async def test_persistent_browser_child_observes_disable_then_reenable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled_states = iter([[], ["browser-task"], []])
    monkeypatch.setattr(
        browser_defaults,
        "collect_disabled_skills",
        lambda roots: next(disabled_states),
    )
    observed: list[set[str]] = []

    async def _base_before_invoke(rail, ctx) -> None:
        del ctx
        observed.append(set(rail.disabled_skills))

    monkeypatch.setattr(SkillUseRail, "before_invoke", _base_before_invoke)
    rail = browser_defaults.build_browser_agent_skill_rail(
        "X:/shared-skills",
        ["browser-task"],
    )
    assert rail is not None

    await rail.before_invoke(object())
    await rail.before_invoke(object())

    assert observed == [{"browser-task"}, set()]
    assert rail.enabled_skills == {"browser-task"}


def test_parent_disabled_composition_is_transient_and_deterministic() -> None:
    assert browser_defaults.compose_parent_disabled_skill_names(
        {"react": _REACT_CONFIG},
        ["library-disabled", "browser-task"],
    ) == ["browser-extra", "browser-task", "library-disabled"]


def test_direct_deep_browser_builder_keeps_skill_names_off_config_skills(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _build_browser(*args, **kwargs):
        del args
        captured.update(kwargs)
        return SimpleNamespace(factory_kwargs={})

    adapter = JiuWenSwarmDeepAdapter.__new__(JiuWenSwarmDeepAdapter)
    adapter._workspace_dir = str(tmp_path)
    adapter._sys_operation = object()
    adapter._model_cache = {}
    adapter._resolve_runtime_language = lambda: "en"
    adapter._browser_runtime_enabled = lambda: True
    adapter._sync_browser_runtime_environment = lambda *args, **kwargs: None
    adapter._sync_mcp_credentials_environment = lambda: None
    monkeypatch.setenv("BROWSER_DRIVER", "managed")
    monkeypatch.setattr(interface_deep, "get_agent_skills_dir", lambda: tmp_path)
    monkeypatch.setattr(interface_deep, "build_browser_agent_config", _build_browser)
    monkeypatch.setattr(interface_deep, "_load_custom_subagents", lambda **kwargs: [])

    subagents, _ = adapter._build_configured_subagents(
        object(),
        {
            "subagents": {
                "statusline-setup": {"enabled": False},
                "browser_agent": {
                    "enabled": True,
                    "skills": ["browser-task"],
                },
            }
        },
        {},
    )

    assert subagents
    assert "skills" not in captured
    assert captured["rails"][0].enabled_skills == {"browser-task"}


def test_direct_code_browser_builder_preserves_settings_and_uses_skill_rail(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _plain_subagent(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(factory_kwargs={})

    def _build_browser(*args, **kwargs):
        del args
        captured.update(kwargs)
        return SimpleNamespace(factory_kwargs={"settings": "sentinel"})

    adapter = JiuwenSwarmCodeAdapter.__new__(JiuwenSwarmCodeAdapter)
    adapter._workspace_dir = str(tmp_path)
    adapter._sys_operation = object()
    adapter._coding_memory_rail = None
    adapter._resolve_runtime_language = lambda: "en"
    adapter._browser_runtime_enabled = lambda: True
    adapter._sync_browser_runtime_environment = lambda *args, **kwargs: None
    monkeypatch.setenv("BROWSER_DRIVER", "managed")
    monkeypatch.setattr(interface_code, "get_agent_skills_dir", lambda: tmp_path)
    monkeypatch.setattr(interface_code, "build_explore_agent_config", _plain_subagent)
    monkeypatch.setattr(interface_code, "build_plan_agent_config", _plain_subagent)
    monkeypatch.setattr(interface_code, "build_browser_agent_config", _build_browser)

    subagents, _ = adapter._build_configured_subagents(
        object(),
        {
            "subagents": {
                "statusline-setup": {"enabled": False},
                "browser_agent": {
                    "enabled": True,
                    "skills": ["browser-task"],
                },
            }
        },
        {},
    )

    browser_spec = subagents[-1]
    assert "skills" not in captured
    assert captured["rails"][0].enabled_skills == {"browser-task"}
    assert browser_spec.factory_kwargs == {
        "settings": "sentinel",
        "auto_create_workspace": False,
    }


class _SkillManager:
    def __init__(self, disabled: list[str] | None = None) -> None:
        self._disabled = list(disabled or [])

    def list_execution_disabled_skills(self) -> list[str]:
        return list(self._disabled)

    def list_disabled_skills(self) -> list[str]:
        return list(self._disabled)

    def reload_state(self) -> None:
        return None


def _bare_adapter() -> JiuWenSwarmDeepAdapter:
    adapter = JiuWenSwarmDeepAdapter.__new__(JiuWenSwarmDeepAdapter)
    adapter._config_base_cache = {"react": _REACT_CONFIG}
    adapter._config_cache = _REACT_CONFIG
    adapter._skill_manager = _SkillManager(["library-disabled"])
    adapter._skill_scan_dirs = lambda: ["X:/shared-skills"]
    adapter._skill_retrieval_session_enabled = False
    return adapter


def test_parent_skill_rail_excludes_browser_child_skills_at_initial_build() -> None:
    adapter = _bare_adapter()
    adapter._resolve_skill_mode = lambda *args, **kwargs: SkillUseRail.SKILL_MODE_ALL

    rail = adapter._build_skill_rail(_REACT_CONFIG, include_tools=False)

    assert rail is not None
    assert rail.disabled_skills == {
        "library-disabled",
        "browser-task",
        "browser-extra",
    }


def test_direct_parent_evolution_excludes_browser_child_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EvolutionRail:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    adapter = _bare_adapter()
    adapter._default_model_name = "model"
    adapter._model = object()
    monkeypatch.setattr(interface_deep, "SkillEvolutionRail", _EvolutionRail)
    monkeypatch.setattr(interface_deep, "get_skill_evolution_enabled", lambda config: True)
    monkeypatch.setattr(
        interface_deep,
        "get_evolution_auto_save_enabled",
        lambda config: False,
    )
    monkeypatch.setattr(
        "openjiuwen.extensions.observability.demand.get_trajectory_span_processor",
        lambda: object(),
    )

    rail = adapter._build_skill_evolution_rail(_REACT_CONFIG)

    assert rail is not None
    assert set(rail.kwargs["disabled_skills"]) == {
        "library-disabled",
        "browser-task",
        "browser-extra",
    }


def test_parent_symphony_inventory_uses_same_browser_child_exclusion() -> None:
    adapter = _bare_adapter()

    assert adapter._live_skill_retrieval_disabled_skills() == [
        "browser-extra",
        "browser-task",
        "library-disabled",
    ]


@pytest.mark.asyncio
async def test_lightweight_refresh_clears_parent_baseline_for_child_only_change() -> None:
    adapter = _bare_adapter()

    class _Rail:
        skills_dir = []
        disabled_skills: set[str] = set()

        async def reload_skills(self) -> None:
            return None

    class _EvolutionRail:
        skills_dir = []

        def __init__(self) -> None:
            self._disabled_skills = {"stale-disabled"}

        @property
        def disabled_skills(self) -> set[str]:
            return self._disabled_skills

    baseline_updates: list[dict] = []
    adapter._skill_rail = _Rail()
    evolution_rail = _EvolutionRail()
    adapter._skill_evolution_rail = evolution_rail
    adapter._instance = SimpleNamespace(
        _loop_session=SimpleNamespace(
            update_state=lambda state: baseline_updates.append(state)
        ),
        deep_config=SimpleNamespace(skills=None),
    )
    adapter._is_session_scoped_adapter = True
    adapter._session_adapters = {}

    await adapter.refresh_skill_rails()

    assert adapter._skill_rail.disabled_skills == {
        "library-disabled",
        "browser-task",
        "browser-extra",
    }
    assert evolution_rail.disabled_skills == {
        "library-disabled",
        "browser-task",
        "browser-extra",
    }
    assert baseline_updates == [{"skill_use": None}]


def test_config_reload_updates_parent_and_evolution_skill_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _bare_adapter()
    adapter._config_base_cache = {"react": {}}

    class _ParentRail:
        skill_mode = SkillUseRail.SKILL_MODE_ALL
        disabled_skills = {"stale-disabled"}

    class _EvolutionRail:
        def __init__(self) -> None:
            self._disabled_skills = {"stale-disabled"}
            self.auto_save = False
            self.updated_model = None

        @property
        def disabled_skills(self) -> set[str]:
            return self._disabled_skills

        def update_llm(self, model, model_name) -> None:
            self.updated_model = (model, model_name)

    adapter._skill_rail = _ParentRail()
    evolution_rail = _EvolutionRail()
    original_evolution_disabled = evolution_rail.disabled_skills
    adapter._skill_evolution_rail = evolution_rail
    adapter._model = object()
    adapter._default_model_name = "test-model"
    adapter._filesystem_rail = None
    adapter._context_assemble_rail = None
    adapter._context_processor_rail = None
    adapter._memory_rail = None
    adapter._avatar_rail = None
    adapter._memory_forbidden_rail = None
    adapter._permission_rail = None
    adapter._heartbeat_rail = object()
    adapter._filesystem_rail_enabled_for_profile = lambda: False
    adapter._update_permission_rail = lambda config: None
    adapter._resolve_skill_mode = lambda *args, **kwargs: SkillUseRail.SKILL_MODE_ALL
    adapter._skill_retrieval_tools_enabled_for_runtime = lambda config: False
    baseline_clears: list[bool] = []
    adapter._clear_skill_session_baseline = lambda: baseline_clears.append(True)
    monkeypatch.setattr(
        interface_deep,
        "get_evolution_auto_save_enabled",
        lambda config: True,
    )

    adapter._get_current_agent_rails(
        _REACT_CONFIG,
        {"react": _REACT_CONFIG},
    )

    expected_disabled = {
        "library-disabled",
        "browser-task",
        "browser-extra",
    }
    assert adapter._skill_rail.disabled_skills == expected_disabled
    assert evolution_rail.disabled_skills is original_evolution_disabled
    assert evolution_rail.disabled_skills == expected_disabled
    assert evolution_rail.auto_save is True
    assert evolution_rail.updated_model == (adapter._model, "test-model")
    assert baseline_clears == [True]
