from __future__ import annotations

import hashlib
from pathlib import Path
import struct

import pytest

from maximum_meow.build import (
    canonical_json_bytes,
    checksum_manifest,
    crc64,
    deterministic_zip,
    fnv1a64_depot_path,
    is_maximum_meow_archive,
    normalize_file_times,
    normalize_redarchive_timestamps,
    phase0_readme,
    phase0_report_payloads,
    production_archive_name,
    production_readme,
    redarchive_file_hashes,
    sha256_file,
    validate_staged_cr2w_manifest,
    wolvenkit_json_bytes,
)


@pytest.mark.parametrize(
    "name",
    [
        "maximum-meow-phase0.archive",
        "!ultimate-uwu-meowification-nyaa-base.archive",
        "!ultimate-uwu-meowification-nyaa-phantom-liberty.archive",
    ],
)
def test_collision_audit_identifies_installed_self_archives(name: str) -> None:
    assert is_maximum_meow_archive(name)


def test_collision_audit_does_not_hide_other_mods() -> None:
    assert not is_maximum_meow_archive("#PetTheCat.archive")


def test_canonical_json_is_order_independent_and_newline_terminated() -> None:
    first = canonical_json_bytes({"b": 2, "a": 1})
    second = canonical_json_bytes({"a": 1, "b": 2})

    assert first == second == b'{"a":1,"b":2}\n'


def test_wolvenkit_json_preserves_header_before_data() -> None:
    payload = wolvenkit_json_bytes({"Header": {"version": 1}, "Data": {"value": 2}})

    assert payload.startswith(b'{"Header":')
    assert payload.endswith(b'\n')


def test_production_archive_names_load_before_installed_ascii_colliders() -> None:
    assert production_archive_name("base") == "!ultimate-uwu-meowification-nyaa-base.archive"
    assert (
        production_archive_name("ep1")
        == "!ultimate-uwu-meowification-nyaa-phantom-liberty.archive"
    )


def test_production_readme_names_install_uninstall_and_collision_boundary() -> None:
    text = production_readme("1.0.0-rc1", 26, 24)

    assert "archive/pc/mod/!ultimate-uwu-meowification-nyaa-base.archive" in text
    assert "archive/pc/mod/!ultimate-uwu-meowification-nyaa-phantom-liberty.archive" in text
    assert "remove archive/pc/mod/maximum-meow-phase0.archive" in text
    assert "delete both prior !ultimate-uwu-meowification-nyaa archives" in text
    assert "26 exact localization resource paths across 24 installed archives" in text
    assert "No runtime framework dependency" in text
    assert "Removing both !ultimate" in text


def test_normalize_file_times_sets_stable_windows_creation_and_write_times(tmp_path: Path) -> None:
    target = tmp_path / "resource.bin"
    target.write_bytes(b"resource")

    normalize_file_times(target)
    first = target.stat()
    normalize_file_times(target)
    second = target.stat()

    assert first.st_ctime_ns == second.st_ctime_ns
    assert first.st_mtime_ns == second.st_mtime_ns


def _fake_archive(path: Path, timestamp: int) -> None:
    record = struct.pack("<QqIIIII20s", 123, timestamp, 0, 0, 1, 0, 0, b"x" * 20)
    table = struct.pack("<III", 1, 1, 0) + record + struct.pack("<QII", 128, 4, 4)
    index = struct.pack("<IIQ", 8, len(table) + 8, crc64(table)) + table
    header = struct.pack("<4sIQI QI Q", b"RDAR", 12, 64, len(index), 0, 0, 64 + len(index))
    path.write_bytes(header.ljust(64, b"\0") + index)


def test_archive_timestamp_normalization_recomputes_crc_and_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.archive"
    second = tmp_path / "second.archive"
    _fake_archive(first, 111)
    _fake_archive(second, 222)

    normalize_redarchive_timestamps(first)
    normalize_redarchive_timestamps(second)

    assert first.read_bytes() == second.read_bytes()


def test_depot_path_hash_matches_redengine_backslash_lowercase_fnv1a() -> None:
    assert (
        fnv1a64_depot_path("base/localization/en-us/onscreens/onscreens.json")
        == 0x67A8AE31C19EAEBD
    )


def test_redarchive_file_hashes_reads_version_12_index_records(tmp_path: Path) -> None:
    archive = tmp_path / "sample.archive"
    _fake_archive(archive, 111)

    assert redarchive_file_hashes(archive) == {123}


def test_pack_guard_rejects_staged_cr2w_changed_after_compile_manifest(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    target = stage / "base" / "localization" / "en-us" / "onscreens" / "onscreens.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"CR2W-verified")
    manifest = [
        {
            "corpus": "base",
            "depot_path": "base/localization/en-us/onscreens/onscreens.json",
            "cr2w_sha256": sha256_file(target),
        }
    ]
    target.write_bytes(b"CR2W-tampered")

    with pytest.raises(ValueError, match="CR2W hash mismatch"):
        validate_staged_cr2w_manifest(stage, manifest, "base")


def test_deterministic_zip_produces_identical_bytes(tmp_path: Path) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    deterministic_zip(first, [("archive/pc/mod/sample.archive", source)])
    deterministic_zip(second, [("archive/pc/mod/sample.archive", source)])

    assert first.read_bytes() == second.read_bytes()
    assert sha256_file(first) == hashlib.sha256(first.read_bytes()).hexdigest()


def test_checksum_manifest_uses_final_archive_names(tmp_path: Path) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")

    manifest = checksum_manifest([("archive/pc/mod/sample.archive", source)])

    assert manifest.endswith("  archive/pc/mod/sample.archive\n")


def test_phase0_report_payloads_cover_grammar_surface_and_expansion() -> None:
    rows = [{
        "category": "compact button",
        "depot_path": "base/example.json",
        "id_field": "primaryKey",
        "id_value": "1",
        "surface": "compact",
        "changed_fields": ["femaleVariant"],
        "before": {"femaleVariant": "Use"},
        "after": {"femaleVariant": "UwUse :3"},
    }]

    reports = phase0_report_payloads(rows)

    assert set(reports) == {"token-grammar.json", "surface-classifier.json", "expansion-report.json"}
    assert reports["surface-classifier.json"]["compact"] == ["compact button"]
    assert reports["surface-classifier.json"]["compact_policy"] == (
        "phonetic mutation only; no stutter, action, interjection, or emoticon"
    )
    assert "sparse" in reports["surface-classifier.json"]["prose_policy"]
    expansion = reports["expansion-report.json"][0]
    assert expansion["source_characters"] == 3
    assert expansion["output_characters"] == 8
    assert expansion["runtime_clipping_status"] == "pending user in-game test"


def test_phase0_readme_names_visible_corrected_validation_targets() -> None:
    text = phase0_readme("Ultimate UwU Meowification Nyaa")

    assert "Interface" in text
    assert "Controls" in text
    assert "Continue" in text
    assert "Return" not in text
    assert "Ammo" not in text
