# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Packaging coverage for the built-in browser-task Skill."""

from __future__ import annotations

from pathlib import Path

from jiuwenswarm.common import utils


def _seed_browser_task(root: Path) -> None:
    skill_dir = root / "browser-task"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: browser-task\ndescription: Browser workflow.\n---\n",
        encoding="utf-8",
    )


def test_workspace_preparation_installs_browser_task(tmp_path: Path) -> None:
    builtin_dir = tmp_path / "builtin"
    user_skills_dir = tmp_path / "user" / "skills"
    _seed_browser_task(builtin_dir)

    utils._install_default_builtin_skills(
        builtin_dir,
        user_skills_dir,
        overwrite=False,
        cumulative_diff=utils.CopyDiffResult([], [], []),
    )

    assert (user_skills_dir / "browser-task" / "SKILL.md").is_file()


def test_startup_backfill_installs_browser_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builtin_dir = tmp_path / "builtin"
    user_skills_dir = tmp_path / "user" / "skills"
    _seed_browser_task(builtin_dir)
    monkeypatch.setattr(utils, "get_builtin_skills_dir", lambda: builtin_dir)
    monkeypatch.setattr(utils, "get_agent_skills_dir", lambda: user_skills_dir)

    utils.ensure_default_builtin_skills()

    assert (user_skills_dir / "browser-task" / "SKILL.md").is_file()
