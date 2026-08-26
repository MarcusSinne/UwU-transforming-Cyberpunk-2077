from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

from .resource import SampleSelection, transform_resource


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FIXED_WINDOWS_FILETIME = 125911584000000000  # 2000-01-01T00:00:00Z
_CRC64_POLYNOMIAL = 0xC96C5795D7870F42


def _crc64_table() -> tuple[int, ...]:
    table: list[int] = []
    for value in range(256):
        crc = value
        for _ in range(8):
            crc = (crc >> 1) ^ _CRC64_POLYNOMIAL if crc & 1 else crc >> 1
        table.append(crc & 0xFFFFFFFFFFFFFFFF)
    return tuple(table)


_CRC64_TABLE = _crc64_table()


def crc64(data: bytes) -> int:
    crc = 0xFFFFFFFFFFFFFFFF
    for value in data:
        crc = (crc >> 8) ^ _CRC64_TABLE[(crc ^ value) & 0xFF]
    return (~crc) & 0xFFFFFFFFFFFFFFFF


def normalize_redarchive_timestamps(path: Path) -> None:
    """Normalize documented REDarchive file timestamps and repair index CRC64."""
    payload = bytearray(path.read_bytes())
    if len(payload) < 40 or payload[:4] != b"RDAR":
        raise ValueError(f"not a REDarchive: {path}")
    version = struct.unpack_from("<I", payload, 4)[0]
    if version != 12:
        raise ValueError(f"unsupported REDarchive version {version}")
    index_position = struct.unpack_from("<Q", payload, 8)[0]
    index_size = struct.unpack_from("<I", payload, 16)[0]
    index_end = index_position + index_size
    if index_position + 28 > len(payload) or index_end > len(payload):
        raise ValueError("REDarchive index is out of bounds")

    stored_crc = struct.unpack_from("<Q", payload, index_position + 8)[0]
    table_payload = bytes(payload[index_position + 16 : index_end])
    if crc64(table_payload) != stored_crc:
        raise ValueError("REDarchive index CRC64 is invalid before normalization")

    file_entry_count = struct.unpack_from("<I", payload, index_position + 16)[0]
    records_start = index_position + 28
    record_size = 56
    if records_start + file_entry_count * record_size > index_end:
        raise ValueError("REDarchive file records exceed index bounds")
    for index in range(file_entry_count):
        timestamp_offset = records_start + index * record_size + 8
        struct.pack_into("<q", payload, timestamp_offset, FIXED_WINDOWS_FILETIME)

    repaired_crc = crc64(bytes(payload[index_position + 16 : index_end]))
    struct.pack_into("<Q", payload, index_position + 8, repaired_crc)
    path.write_bytes(payload)


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


def normalize_file_times(path: Path) -> None:
    """Pin creation/access/write times so REDarchive file records are reproducible."""
    if os.name != "nt":
        os.utime(path, (946684800, 946684800))
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    set_file_time = kernel32.SetFileTime
    set_file_time.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    set_file_time.restype = ctypes.c_int

    handle = create_file(str(path), 0x0100, 0x1 | 0x2 | 0x4, None, 3, 0, None)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise OSError(ctypes.get_last_error(), f"CreateFileW failed for {path}")
    file_time = _FileTime(
        FIXED_WINDOWS_FILETIME & 0xFFFFFFFF,
        FIXED_WINDOWS_FILETIME >> 32,
    )
    try:
        if not set_file_time(handle, ctypes.byref(file_time), ctypes.byref(file_time), ctypes.byref(file_time)):
            raise OSError(ctypes.get_last_error(), f"SetFileTime failed for {path}")
    finally:
        kernel32.CloseHandle(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_staged_cr2w_manifest(
    stage_root: Path,
    manifest_rows: list[dict],
    corpus: str,
) -> int:
    expected = {
        row["depot_path"]: row["cr2w_sha256"]
        for row in manifest_rows
        if row["corpus"] == corpus
    }
    actual = {
        path.relative_to(stage_root).as_posix(): path
        for path in stage_root.rglob("*.json")
        if not path.name.endswith(".json.json")
    }
    if actual.keys() != expected.keys():
        raise ValueError(f"{corpus} stage tree differs from compiled manifest")
    for depot_path, path in sorted(actual.items()):
        if sha256_file(path) != expected[depot_path]:
            raise ValueError(f"CR2W hash mismatch: {depot_path}")
    return len(actual)


def production_archive_name(corpus: str) -> str:
    names = {
        "base": "!ultimate-uwu-meowification-nyaa-base.archive",
        "ep1": "!ultimate-uwu-meowification-nyaa-phantom-liberty.archive",
    }
    try:
        return names[corpus]
    except KeyError as error:
        raise ValueError(f"unknown production corpus: {corpus}") from error


def is_maximum_meow_archive(name: str) -> bool:
    normalized = name.casefold()
    return normalized in {
        "maximum-meow-phase0.archive",
        production_archive_name("base").casefold(),
        production_archive_name("ep1").casefold(),
    }


def production_readme(
    version: str,
    collision_path_count: int,
    collision_archive_count: int,
) -> str:
    base_path = f"archive/pc/mod/{production_archive_name('base')}"
    ep1_path = f"archive/pc/mod/{production_archive_name('ep1')}"
    return f"""Ultimate UwU Meowification Nyaa {version}

STATUS
Production Phases 1-7 passed STATIC, COMPILE, PACKAGE, and deterministic-build checks.
LOAD, RUNTIME, clean removal, clipping, and combined-mod behavior remain user-owned Phase 8 checks.

BLAST RADIUS
This package replaces English onscreen and subtitle localization resources from the base game and Phantom Liberty.
It cannot change audio, scripts, quests, gameplay records, saves, input bindings, world state, or network behavior.
No runtime framework dependency is required.

INSTALL
1. In the Cyberpunk 2077 game root, remove archive/pc/mod/maximum-meow-phase0.archive if it exists.
2. For a clean update, delete both prior !ultimate-uwu-meowification-nyaa archives from archive/pc/mod if they exist.
3. Extract this ZIP into the game root. The final runtime files are:
   - {base_path}
   - {ep1_path}
4. Keep the leading ! characters. Cyberpunk legacy archive conflicts are first-wins in ASCII filename order; these names intentionally make the complete localization overhaul win.
5. If Phantom Liberty is not installed, omit {ep1_path}.

INSTALLED-STACK COLLISIONS
The build found {collision_path_count} exact localization resource paths across {collision_archive_count} installed archives.
While this mod is active, its leading-! archives win those files. Conflicting mods can lose added or edited text at those exact resources.
See reports/installed-collision-audit.json for owners and paths. This is deliberate for complete coverage, not a compatibility claim.

UNINSTALL
Removing both !ultimate archive files above restores the previous archive winners. No save migration or cache cleanup is designed.

PHASE 8 TEST
Launch with English text, then check main/settings menus, HUD/input glyphs, a cinematic subtitle, overhead dialogue, a quest objective, an item description, a shard/computer, and one Phantom Liberty scene.
Pass = transformed text on each surface; no raw tags, missing lines, wrong numbers, broken glyphs, or unusable navigation.
Then remove both archives and relaunch.
Clean-removal pass = vanilla/previous-mod text returns and the same save loads normally.
"""


def fnv1a64_depot_path(path: str) -> int:
    value = 0xCBF29CE484222325
    for byte in path.replace("/", "\\").lower().encode("utf-8"):
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value


def redarchive_file_hashes(path: Path) -> set[int]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(20)
        if len(header) != 20 or header[:4] != b"RDAR":
            raise ValueError(f"not a REDarchive: {path}")
        version = struct.unpack_from("<I", header, 4)[0]
        if version != 12:
            raise ValueError(f"unsupported REDarchive version {version}")
        index_position = struct.unpack_from("<Q", header, 8)[0]
        index_size = struct.unpack_from("<I", header, 16)[0]
        handle.seek(index_position + 16)
        count_payload = handle.read(4)
        if len(count_payload) != 4:
            raise ValueError("REDarchive index is truncated")
        file_entry_count = struct.unpack("<I", count_payload)[0]
        records_start = index_position + 28
        if records_start + file_entry_count * 56 > index_position + index_size:
            raise ValueError("REDarchive file records exceed index bounds")
        if index_position + index_size > size:
            raise ValueError("REDarchive index is out of bounds")
        handle.seek(records_start)
        hashes: set[int] = set()
        for _ in range(file_entry_count):
            record = handle.read(56)
            if len(record) != 56:
                raise ValueError("REDarchive file record is truncated")
            hashes.add(struct.unpack_from("<Q", record, 0)[0])
    return hashes


def checksum_manifest(entries: list[tuple[str, Path]]) -> str:
    return "".join(
        f"{sha256_file(path)}  {archive_name.replace(chr(92), '/')}\n"
        for archive_name, path in sorted(entries, key=lambda item: item[0])
    )


def phase0_readme(public_title: str) -> str:
    return (
        f"{public_title}\nPhase 0 candidate A — direct archive\n\n"
        "INSTALL (manual): copy archive/pc/mod/maximum-meow-phase0.archive into the matching game path.\n"
        "UNINSTALL: delete only archive/pc/mod/maximum-meow-phase0.archive.\n\n"
        "TEST: open Settings and confirm Interface becomes Intewface and Controls becomes Contwows; return to the main menu and confirm Continue becomes Continyue. Compact UI must contain no stutter, action, interjection, or emoticon. If your save reaches The Rescue, check the selected dialogue/subtitle. Phantom Liberty check: during q301_03_crash, the Myers objective line is transformed.\n"
        "PASS: transformed sample text appears, input glyphs/placeholders/numbers remain correct, voices and gameplay are unchanged, and deleting the archive restores source English on the same save.\n"
        "FAIL: blank text, raw tags, wrong quantities/glyphs, decorated compact UI, unchanged selected sample, save/load issue, or English does not return after removal.\n"
    )


def phase0_report_payloads(validation_rows: list[dict]) -> dict[str, object]:
    token_grammar = {
        "scope": "Phase 0 representative sample; unknown syntax remains fatal",
        "recognized_constructs": [
            {"kind": "rich_text", "forms": ["<Rich ...>", "</>"], "policy": "tags and attributes exact; visible text nodes transform"},
            {"kind": "input_glyph", "forms": ["<Input ...>", "</>"], "policy": "exact byte preservation"},
            {"kind": "mothertongue", "forms": ["<mothertongue l=... m=... b=... a=.../>"], "policy": "attribute names/order/quoting and language code exact; visible m/b/a payloads transform"},
            {"kind": "placeholder", "forms": ["{name}", "{name,number,integer}"], "policy": "exact byte preservation"},
            {"kind": "escaped_line_break", "forms": ["\\n"], "policy": "exact byte preservation"},
            {"kind": "numeric", "forms": ["70%", "€$10,000", "180"], "policy": "exact byte preservation"},
            {"kind": "directive", "forms": ["<<<...>>>"], "policy": "exact byte preservation"},
            {"kind": "url", "forms": ["http://...", "https://..."], "policy": "exact byte preservation"},
        ],
        "unknown_markup_behavior": "abort with resource, entry identifier, field, and span",
    }
    surface_classifier = {
        "compact": sorted(row["category"] for row in validation_rows if row["surface"] == "compact"),
        "prose": sorted(row["category"] for row in validation_rows if row["surface"] == "prose"),
        "compact_policy": "phonetic mutation only; no stutter, action, interjection, or emoticon",
        "prose_policy": "phonetic mutation with sparse deterministic stutter and at most one occasional action, interjection, or emoticon",
    }
    expansion_rows: list[dict] = []
    for row in validation_rows:
        for field in row["changed_fields"]:
            source_length = len(row["before"][field])
            output_length = len(row["after"][field])
            expansion_rows.append(
                {
                    "category": row["category"],
                    "depot_path": row["depot_path"],
                    "id_field": row["id_field"],
                    "id_value": row["id_value"],
                    "field": field,
                    "surface": row["surface"],
                    "source_characters": source_length,
                    "output_characters": output_length,
                    "delta_characters": output_length - source_length,
                    "ratio": round(output_length / source_length, 6),
                    "runtime_clipping_status": "pending user in-game test",
                }
            )
    return {
        "token-grammar.json": token_grammar,
        "surface-classifier.json": surface_classifier,
        "expansion-report.json": expansion_rows,
    }


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def wolvenkit_json_bytes(value: object) -> bytes:
    """Serialize without key sorting; WolvenKit requires Header before Data."""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def deterministic_zip(destination: Path, entries: list[tuple[str, Path]]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for archive_name, source in sorted(entries, key=lambda item: item[0]):
            info = zipfile.ZipInfo(archive_name.replace("\\", "/"), FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())


def _run_cli(cli: Path, args: list[str], log_path: Path) -> str:
    completed = subprocess.run(
        [str(cli), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
    if completed.returncode != 0:
        raise RuntimeError(f"WolvenKit failed ({completed.returncode}); see {log_path}")
    lowered = completed.stdout.lower()
    if "[ 0: error" in lowered or "unhandled exception" in lowered:
        raise RuntimeError(f"WolvenKit reported an error; see {log_path}")
    return completed.stdout


def _selections(resource: dict) -> tuple[SampleSelection, ...]:
    return tuple(
        SampleSelection(
            category=item["category"],
            id_field=item["id_field"],
            id_value=item["id_value"],
            fields=tuple(item["fields"]),
            surface=item["surface"],
        )
        for item in resource["selections"]
    )


def build_phase0(root: Path, run_id: str, cli: Path, game_root: Path) -> dict:
    config_path = root / "config" / "phase0-sample.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    extraction_record = json.loads(
        (root / "reports" / "extraction-record.json").read_text(encoding="utf-8")
    )
    archive_inventory: list[dict] = []
    maximum_extracted_path = 0
    for archive_record in extraction_record["archives"]:
        installed_archive = game_root / archive_record["installed_relative_path"]
        if not installed_archive.is_file():
            raise FileNotFoundError(f"installed source archive missing: {installed_archive}")
        installed_hash = sha256_file(installed_archive)
        if installed_hash != archive_record["sha256"]:
            raise RuntimeError(
                f"installed source archive changed after extraction: {archive_record['installed_relative_path']}"
            )
        if installed_archive.stat().st_size != archive_record["size"]:
            raise RuntimeError(f"installed source archive size changed: {archive_record['installed_relative_path']}")
        extracted_root = root / archive_record["source_root"]
        extracted_files = sorted(extracted_root.rglob("*.json"))
        if len(extracted_files) != archive_record["extracted_resources"]:
            raise RuntimeError(f"extracted resource count mismatch for {archive_record['corpus']}")
        if extracted_files:
            maximum_extracted_path = max(
                maximum_extracted_path,
                max(len(str(path)) for path in extracted_files),
            )
        archive_inventory.append(
            {
                "corpus": archive_record["corpus"],
                "installed_path": archive_record["installed_relative_path"],
                "sha256": installed_hash,
                "size": installed_archive.stat().st_size,
                "extracted_resources": len(extracted_files),
            }
        )
    run_root = root / "build" / run_id
    if run_root.exists():
        shutil.rmtree(run_root)
    transformed_root = run_root / "transformed"
    converted_root = run_root / "converted"
    stage_root = run_root / "stage"
    roundtrip_root = run_root / "roundtrip"
    logs_root = run_root / "logs"
    reports_root = run_root / "reports"
    archive_root = run_root / "archive"
    for path in (
        transformed_root,
        converted_root,
        stage_root,
        roundtrip_root,
        logs_root,
        reports_root,
        archive_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    validation_rows: list[dict] = []
    source_resources: list[dict] = []
    package_depot_paths: list[str] = []

    for index, resource in enumerate(config["resources"]):
        serialized_source = root / resource["serialized_source"]
        source_cr2w = root / resource["source_cr2w"]
        if not serialized_source.is_file() or not source_cr2w.is_file():
            raise FileNotFoundError(f"missing source for {resource['depot_path']}")
        source_document = json.loads(serialized_source.read_text(encoding="utf-8"))
        output_document, rows = transform_resource(
            source_document,
            resource["depot_path"],
            _selections(resource),
            config["seed"],
        )
        for row in rows:
            row["depot_path"] = resource["depot_path"]
            row["corpus"] = resource["corpus"]
        validation_rows.extend(rows)

        transformed_path = transformed_root / f"{index:02d}-{Path(resource['depot_path']).name}.json"
        transformed_path.write_bytes(wolvenkit_json_bytes(output_document))

        converted_dir = converted_root / f"{index:02d}"
        converted_dir.mkdir(parents=True)
        _run_cli(
            cli,
            ["convert", "deserialize", str(transformed_path), "-o", str(converted_dir), "-v", "Detailed"],
            logs_root / f"{index:02d}-deserialize.log",
        )
        converted_resource = converted_dir / transformed_path.name.removesuffix(".json")
        if not converted_resource.is_file():
            raise RuntimeError(f"deserializer did not produce {converted_resource}")

        staged_resource = stage_root / Path(resource["depot_path"])
        staged_resource.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(converted_resource, staged_resource)
        normalize_file_times(staged_resource)

        roundtrip_dir = roundtrip_root / f"{index:02d}"
        roundtrip_dir.mkdir(parents=True)
        _run_cli(
            cli,
            ["convert", "serialize", str(staged_resource), "-o", str(roundtrip_dir), "-v", "Detailed"],
            logs_root / f"{index:02d}-reserialize.log",
        )
        roundtrip_json = roundtrip_dir / f"{staged_resource.name}.json"
        if not roundtrip_json.is_file():
            raise RuntimeError(f"serializer did not produce {roundtrip_json}")
        roundtrip_document = json.loads(roundtrip_json.read_text(encoding="utf-8"))
        if roundtrip_document.get("Data") != output_document.get("Data"):
            raise RuntimeError(f"semantic round-trip mismatch for {resource['depot_path']}")

        source_resources.append(
            {
                "corpus": resource["corpus"],
                "depot_path": resource["depot_path"],
                "source_cr2w_sha256": sha256_file(source_cr2w),
                "serialized_source_sha256": sha256_file(serialized_source),
                "staged_cr2w_sha256": sha256_file(staged_resource),
                "selection_count": len(rows),
            }
        )
        package_depot_paths.append(resource["depot_path"])

    validation_rows.sort(key=lambda row: (row["depot_path"], row["id_field"], row["id_value"]))
    (reports_root / "validation-report.json").write_bytes(canonical_json_bytes(validation_rows))
    for report_name, report_payload in phase0_report_payloads(validation_rows).items():
        (reports_root / report_name).write_bytes(canonical_json_bytes(report_payload))

    source_inventory = {
        "archives": archive_inventory,
        "maximum_extracted_path_characters": maximum_extracted_path,
        "resources": source_resources,
    }
    (reports_root / "source-inventory.json").write_bytes(canonical_json_bytes(source_inventory))

    version_output = _run_cli(cli, ["--version"], logs_root / "wolvenkit-version.log")
    toolchain = {
        "wolvenkit_version": next(
            (line.strip() for line in version_output.splitlines() if line.strip().startswith("8.")), "unknown"
        ),
        "wolvenkit_cli_sha256": sha256_file(cli),
        "dotnet_runtime": "Microsoft.NETCore.App 8.0.30 x64",
        "python": "3.11",
        "known_warning": "Windows LongPathsEnabled=0; measured Phase 0 paths max at 160 characters",
    }
    (reports_root / "toolchain.json").write_bytes(canonical_json_bytes(toolchain))

    _run_cli(
        cli,
        ["pack", str(stage_root), "-o", str(archive_root), "-v", "Detailed"],
        logs_root / "pack.log",
    )
    packed = archive_root / "stage.archive"
    if not packed.is_file():
        candidates = list(archive_root.glob("*.archive"))
        if len(candidates) != 1:
            raise RuntimeError("pack did not produce exactly one archive")
        packed = candidates[0]
    normalize_redarchive_timestamps(packed)
    final_archive = run_root / "maximum-meow-phase0.archive"
    shutil.copyfile(packed, final_archive)

    listing = _run_cli(
        cli,
        ["archive", str(final_archive), "--list", "-v", "Detailed"],
        logs_root / "archive-list.log",
    )
    normalized_listing = listing.replace("\\", "/")
    missing_paths = [path for path in package_depot_paths if path not in normalized_listing]
    if missing_paths:
        raise RuntimeError(f"packed archive missing paths: {missing_paths}")

    package_manifest = {
        "public_title": config["public_title"],
        "slug": config["slug"],
        "version": config["version"],
        "archive_entry_count": len(package_depot_paths),
        "archive_sha256": sha256_file(final_archive),
        "depot_paths": sorted(package_depot_paths),
        "validation_sample_count": len(validation_rows),
    }
    (reports_root / "package-manifest.json").write_bytes(canonical_json_bytes(package_manifest))

    readme = run_root / "README.txt"
    readme.write_text(
        phase0_readme(config["public_title"]),
        encoding="utf-8",
        newline="\n",
    )

    checksums = run_root / "SHA256SUMS.txt"
    checksum_entries = [
        ("archive/pc/mod/maximum-meow-phase0.archive", final_archive),
        ("README.txt", readme),
    ] + [(f"reports/{path.name}", path) for path in sorted(reports_root.glob("*.json"))]
    checksums.write_text(checksum_manifest(checksum_entries), encoding="utf-8", newline="\n")

    zip_path = run_root / f"maximum-meow-{config['version']}.zip"
    zip_entries = [
        ("archive/pc/mod/maximum-meow-phase0.archive", final_archive),
        ("README.txt", readme),
        ("SHA256SUMS.txt", checksums),
    ] + [(f"reports/{path.name}", path) for path in sorted(reports_root.glob("*.json"))]
    deterministic_zip(zip_path, zip_entries)

    result = {
        "run_id": run_id,
        "archive": str(final_archive),
        "archive_sha256": sha256_file(final_archive),
        "zip": str(zip_path),
        "zip_sha256": sha256_file(zip_path),
        "validation_sample_count": len(validation_rows),
        "depot_path_count": len(package_depot_paths),
    }
    (run_root / "build-result.json").write_bytes(canonical_json_bytes(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--game-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_phase0(
                args.root.resolve(),
                args.run_id,
                args.cli.resolve(),
                args.game_root.resolve(),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
