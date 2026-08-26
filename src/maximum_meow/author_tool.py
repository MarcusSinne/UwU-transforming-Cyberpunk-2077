from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

from .build import (
    _run_cli,
    canonical_json_bytes,
    normalize_redarchive_timestamps,
    sha256_file,
    wolvenkit_json_bytes,
)
from .corpus import folder_deserialization_command, folder_serialization_command
from .resource import transform_full_resource
from .transformer import PRODUCTION_SEED


def _depot_path(path: Path, input_root: Path) -> Path | None:
    relative = path.resolve().relative_to(input_root.resolve())
    parts = relative.parts
    lowered = tuple(part.lower() for part in parts)
    for index in range(len(parts) - 3):
        if (
            lowered[index] in {"base", "ep1"}
            and lowered[index + 1 : index + 3] == ("localization", "en-us")
            and lowered[index + 3] in {"onscreens", "subtitles"}
        ):
            return Path(*parts[index:])
    return None


def discover_localization_resources(input_root: Path) -> list[tuple[Path, Path]]:
    root = input_root.resolve()
    if not root.is_dir():
        raise ValueError(f"input is not a directory: {root}")
    discovered: list[tuple[Path, Path]] = []
    identities: set[str] = set()
    for path in sorted(root.rglob("*.json")):
        if path.name.endswith(".json.json"):
            continue
        depot_path = _depot_path(path, root)
        if depot_path is None:
            continue
        if path.read_bytes()[:4] != b"CR2W":
            raise ValueError(f"localization input is not CR2W: {depot_path.as_posix()}")
        identity = depot_path.as_posix().casefold()
        if identity in identities:
            raise ValueError(f"duplicate localization depot path: {depot_path.as_posix()}")
        identities.add(identity)
        discovered.append((depot_path, path))
    if not discovered:
        raise ValueError("no English onscreen/subtitle CR2W resources found")
    return discovered


def safe_patch_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("patch name must contain a letter or number")
    return slug


def author_tool_readme() -> str:
    return """Maximum Meow Author Tool

Transforms English Cyberpunk 2077 localization resources in a mod project folder.

BOUNDARY
- Input files are copied and never modified.
- Only CR2W resources under base/ep1 localization/en-us onscreens/subtitles are processed.
- Output is a separate archive and JSON manifest; nothing is installed into the game.
- Run again after the source mod changes. Do not redistribute another author's transformed text without permission.

USAGE
maximum-meow-author --input MOD_PROJECT_FOLDER --output OUTPUT_FOLDER --name MOD_NAME --wolvenkit WolvenKit.CLI.exe

The output archive must load before the source mod archive when both own the same custom depot paths.
"""


def build_author_patch(
    input_root: Path,
    output_root: Path,
    name: str,
    cli: Path,
    seed: str = PRODUCTION_SEED,
) -> dict:
    resources = discover_localization_resources(input_root)
    output = output_root.resolve()
    source_root = input_root.resolve()
    if output == source_root or source_root in output.parents:
        raise ValueError("output must be outside the input tree")
    slug = safe_patch_name(name)
    work = output / ".maximum-meow-work"
    if work.exists():
        shutil.rmtree(work)
    copied = work / "copied"
    transformed_root = work / "transformed"
    stage = work / "stage"
    packed = work / "packed"
    logs = work / "logs"
    output.mkdir(parents=True, exist_ok=True)

    source_hashes: dict[str, str] = {}
    for depot_path, source in resources:
        target = copied / depot_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        source_hashes[depot_path.as_posix()] = sha256_file(source)

    _run_cli(cli.resolve(), list(folder_serialization_command(cli.resolve(), copied))[1:], logs / "serialize.log")

    report_rows: list[dict] = []
    for depot_path, _ in resources:
        sidecar = (copied / depot_path).with_name(f"{depot_path.name}.json")
        if not sidecar.is_file():
            raise RuntimeError(f"WolvenKit did not serialize {depot_path.as_posix()}")
        document = json.loads(sidecar.read_text(encoding="utf-8"))
        transformed, report = transform_full_resource(document, depot_path.as_posix(), seed)
        destination = (transformed_root / depot_path).with_name(f"{depot_path.name}.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(wolvenkit_json_bytes(transformed))
        report_rows.append(report)

    _run_cli(
        cli.resolve(),
        list(folder_deserialization_command(cli.resolve(), transformed_root))[1:],
        logs / "deserialize.log",
    )
    for depot_path, _ in resources:
        binary = transformed_root / depot_path
        if binary.read_bytes()[:4] != b"CR2W":
            raise RuntimeError(f"WolvenKit did not compile {depot_path.as_posix()}")
        destination = stage / depot_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binary, destination)

    _run_cli(cli.resolve(), list(folder_serialization_command(cli.resolve(), stage))[1:], logs / "roundtrip.log")
    for depot_path, _ in resources:
        expected = json.loads(
            (transformed_root / depot_path).with_name(f"{depot_path.name}.json").read_text(encoding="utf-8")
        )["Data"]
        roundtrip_path = (stage / depot_path).with_name(f"{depot_path.name}.json")
        if not roundtrip_path.is_file():
            raise RuntimeError(f"roundtrip missing for {depot_path.as_posix()}")
        actual = json.loads(roundtrip_path.read_text(encoding="utf-8"))["Data"]
        if actual != expected:
            raise RuntimeError(f"semantic roundtrip mismatch: {depot_path.as_posix()}")
        roundtrip_path.unlink()

    packed.mkdir(parents=True)
    _run_cli(
        cli.resolve(),
        ["pack", str(stage), "-o", str(packed), "-v", "Detailed"],
        logs / "pack.log",
    )
    candidates = sorted(packed.glob("*.archive"))
    if len(candidates) != 1:
        raise RuntimeError(f"WolvenKit produced {len(candidates)} archives")
    archive = output / f"!maximum-meow-{slug}.archive"
    normalize_redarchive_timestamps(candidates[0])
    shutil.copyfile(candidates[0], archive)
    listing = _run_cli(
        cli.resolve(),
        ["archive", str(archive), "--list", "-v", "Detailed"],
        logs / "archive-list.log",
    )
    actual_paths = sorted(
        line.strip().replace("\\", "/")
        for line in listing.splitlines()
        if line.strip().lower().endswith(".json")
    )
    expected_paths = sorted(path.as_posix() for path, _ in resources)
    if actual_paths != expected_paths:
        raise RuntimeError("archive readback path set mismatch")

    manifest = {
        "name": name,
        "seed": seed,
        "archive": archive.name,
        "archive_sha256": sha256_file(archive),
        "resource_count": len(resources),
        "semantic_roundtrips": len(resources),
        "source_resources": [
            {"depot_path": path, "source_sha256": source_hashes[path]}
            for path in expected_paths
        ],
        "resource_reports": sorted(report_rows, key=lambda row: row["resource"]),
    }
    manifest_path = output / f"!maximum-meow-{slug}.manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    (output / "README.txt").write_text(author_tool_readme(), encoding="utf-8", newline="\n")
    shutil.rmtree(work)
    return {**manifest, "archive_path": str(archive), "manifest_path": str(manifest_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="UwU-transform another mod's English localization")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--wolvenkit", type=Path, required=True)
    parser.add_argument("--seed", default=PRODUCTION_SEED)
    args = parser.parse_args()
    result = build_author_patch(args.input, args.output, args.name, args.wolvenkit, args.seed)
    print(json.dumps(result, indent=2)[:8000])


if __name__ == "__main__":
    main()
