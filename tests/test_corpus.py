from __future__ import annotations

from pathlib import Path

import pytest

from maximum_meow.corpus import (
    classify_surface,
    depot_path_from_sidecar,
    deserialized_binary_path,
    folder_deserialization_command,
    folder_serialization_command,
    serialization_batches,
    serialization_manifest_row,
    serialized_sidecar_path,
    validate_serialization_manifest,
)


def test_serialization_manifest_rejects_substituted_sidecar(tmp_path: Path) -> None:
    root = tmp_path
    source_root = root / "source" / "base"
    source = source_root / "base/localization/en-us/subtitles/line.json"
    serialized = root / "raw/full/base/base/localization/en-us/subtitles/line.json.json"
    source.parent.mkdir(parents=True)
    serialized.parent.mkdir(parents=True)
    source.write_bytes(b"CR2W-source")
    serialized.write_text('{"Data":{"value":"original"}}', encoding="utf-8")
    row = serialization_manifest_row("base", source, source_root, serialized, root)

    serialized.write_text('{"Data":{"value":"tampered"}}', encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="base:base/localization/en-us/subtitles/line.json.*serialized_sha256",
    ):
        validate_serialization_manifest([row], root)


def test_serialization_batches_preserve_depot_parent_and_limits(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    files = [
        source_root / "base/localization/en-us/subtitles/a" / f"line_{index:02d}.json"
        for index in range(7)
    ] + [
        source_root / "base/localization/en-us/subtitles/b" / f"other_{index:02d}.json"
        for index in range(3)
    ]

    batches = serialization_batches(files, source_root, max_files=3, max_path_characters=10_000)

    assert sum(len(batch.files) for batch in batches) == 10
    assert all(len(batch.files) <= 3 for batch in batches)
    assert all(len({path.parent for path in batch.files}) == 1 for batch in batches)
    assert all(batch.relative_parent == batch.files[0].parent.relative_to(source_root) for batch in batches)


def test_serialization_batches_split_before_path_budget(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    files = [source_root / "base/subtitles" / f"{'x' * 20}_{index}.json" for index in range(4)]
    single_cost = len(str(files[0]))

    batches = serialization_batches(
        files,
        source_root,
        max_files=100,
        max_path_characters=single_cost * 2 - 1,
    )

    assert [len(batch.files) for batch in batches] == [1, 1, 1, 1]


def test_serialization_batches_reject_files_outside_source_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside source root"):
        serialization_batches([tmp_path / "elsewhere.json"], tmp_path / "source")


@pytest.mark.parametrize(
    ("resource", "secondary_key", "text", "expected"),
    [
        ("base/localization/en-us/subtitles/quest/q001/line.json", "", "Right.", "prose"),
        ("base/localization/en-us/onscreens/onscreens.json", "UI-Settings-Interface-Title", "Interface", "compact"),
        ("base/localization/en-us/onscreens/onscreens.json", "UI-ScriptExports-Continue0", "Continue", "compact"),
        ("base/localization/en-us/onscreens/onscreens.json", "Story-Quest-Objective-Description", "Meet the courier at sunrise.", "prose"),
        ("base/localization/en-us/onscreens/onscreens.json", "Story-Message-Content", "Short message.", "prose"),
        ("base/localization/en-us/onscreens/onscreens.json", "Unknown-Key", "First line\\nSecond line", "prose"),
        ("base/localization/en-us/onscreens/onscreens.json", "Unknown-Key", "A" * 81, "prose"),
    ],
)
def test_classify_surface_uses_resource_key_and_layout(
    resource: str, secondary_key: str, text: str, expected: str
) -> None:
    assert classify_surface(resource, secondary_key, text) == expected


def test_serialized_sidecar_path_appends_json_without_losing_depot_path(tmp_path: Path) -> None:
    source = tmp_path / "base/localization/en-us/subtitles/line.json"

    assert serialized_sidecar_path(source) == source.with_name("line.json.json")


def test_folder_serialization_command_uses_cr2w_filter_not_pattern(tmp_path: Path) -> None:
    command = folder_serialization_command(Path("WolvenKit.CLI.exe"), tmp_path / "source")

    assert command == (
        "WolvenKit.CLI.exe",
        "convert",
        "serialize",
        str((tmp_path / "source").resolve()),
        "-v",
        "Minimal",
    )
    assert "--pattern" not in command
    assert "-w" not in command


def test_depot_path_from_sidecar_strips_only_serializer_suffix(tmp_path: Path) -> None:
    corpus_root = tmp_path / "raw/full/base"
    sidecar = corpus_root / "base/localization/en-us/subtitles/line.json.json"

    assert depot_path_from_sidecar(sidecar, corpus_root) == Path(
        "base/localization/en-us/subtitles/line.json"
    )


def test_depot_path_from_sidecar_rejects_wrong_suffix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.json\.json"):
        depot_path_from_sidecar(tmp_path / "line.json", tmp_path)


def test_deserialized_binary_path_removes_only_final_json_suffix(tmp_path: Path) -> None:
    sidecar = tmp_path / "line.json.json"

    assert deserialized_binary_path(sidecar) == tmp_path / "line.json"


def test_folder_deserialization_command_uses_clean_directory_without_pattern(
    tmp_path: Path,
) -> None:
    command = folder_deserialization_command(Path("WolvenKit.CLI.exe"), tmp_path / "serialized")

    assert command == (
        "WolvenKit.CLI.exe",
        "convert",
        "deserialize",
        str((tmp_path / "serialized").resolve()),
        "-v",
        "Minimal",
    )
    assert "--pattern" not in command
    assert "-w" not in command
