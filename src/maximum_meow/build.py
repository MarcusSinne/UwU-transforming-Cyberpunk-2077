from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import zipfile



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

WHAT IT CHANGES
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

TEST IN GAME
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








