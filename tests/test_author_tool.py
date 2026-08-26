from __future__ import annotations

from pathlib import Path

import pytest

from maximum_meow.author_tool import (
    author_tool_readme,
    discover_localization_resources,
    safe_patch_name,
)


def test_author_tool_discovers_only_english_localization_cr2w(tmp_path: Path) -> None:
    wanted = tmp_path / "archive/base/localization/en-us/onscreens/my_mod.json"
    ignored = tmp_path / "archive/base/gameplay/items/not_localization.json"
    wanted.parent.mkdir(parents=True)
    ignored.parent.mkdir(parents=True)
    wanted.write_bytes(b"CR2Wpayload")
    ignored.write_bytes(b"CR2Wpayload")

    assert discover_localization_resources(tmp_path) == [
        (Path("base/localization/en-us/onscreens/my_mod.json"), wanted)
    ]


def test_author_tool_rejects_plain_json_in_runtime_localization_path(tmp_path: Path) -> None:
    invalid = tmp_path / "base/localization/en-us/subtitles/my_mod.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text('{"not":"cr2w"}', encoding="utf-8")

    with pytest.raises(ValueError, match="not CR2W.*my_mod.json"):
        discover_localization_resources(tmp_path)


def test_author_tool_rejects_casefolded_duplicate_depot_paths(tmp_path: Path) -> None:
    first = tmp_path / "a/base/localization/en-us/onscreens/MyMod.json"
    second = tmp_path / "b/base/localization/en-us/onscreens/mymod.json"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"CR2Wone")
    second.write_bytes(b"CR2Wtwo")

    with pytest.raises(ValueError, match="duplicate localization depot path"):
        discover_localization_resources(tmp_path)


def test_author_tool_name_and_documentation_are_safe() -> None:
    assert safe_patch_name("Enhanced Craft 2.0") == "enhanced-craft-2-0"
    readme = author_tool_readme()
    assert "never modified" in readme
    assert "nothing is installed into the game" in readme
    assert "without permission" in readme
