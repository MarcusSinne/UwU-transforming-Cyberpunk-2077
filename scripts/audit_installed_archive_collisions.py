from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from maximum_meow.build import (
    canonical_json_bytes,
    fnv1a64_depot_path,
    is_maximum_meow_archive,
    production_archive_name,
    redarchive_file_hashes,
)


parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--game-root", type=Path, required=True)
parser.add_argument("--run-id", required=True)
args = parser.parse_args()
root = args.root.resolve()
game_root = args.game_root.resolve()
run_root = root / "build" / args.run_id
reports_root = run_root / "reports"
package_manifest = json.loads(
    (reports_root / "package-manifest.json").read_text(encoding="utf-8")
)
expected_paths = sorted(
    depot_path for row in package_manifest for depot_path in row["depot_paths"]
)
target_by_hash = {fnv1a64_depot_path(path): path for path in expected_paths}
if len(target_by_hash) != len(expected_paths):
    raise SystemExit("target depot-path hash collision")

mods_root = game_root / "archive" / "pc" / "mod"
archives = sorted(mods_root.glob("*.archive"), key=lambda path: path.name)
owners: defaultdict[str, list[str]] = defaultdict(list)
index_failures: list[dict] = []
self_archives: list[dict] = []
for archive in archives:
    try:
        matches = set(target_by_hash).intersection(redarchive_file_hashes(archive))
    except Exception as error:
        index_failures.append({"archive": archive.name, "error": str(error)})
        continue
    if is_maximum_meow_archive(archive.name):
        self_archives.append(
            {"archive": archive.name, "target_path_count": len(matches)}
        )
        continue
    for value in matches:
        owners[target_by_hash[value]].append(archive.name)

raw_scan_path = root / "build" / "installed-archive-localization-scan.txt"
raw_scan = raw_scan_path.read_text(encoding="utf-8", errors="replace")
listed_paths = [
    value.replace("\\", "/")
    for value in re.findall(
        r"(?:base|ep1)\\localization\\[^\r\n]+?\.json", raw_scan, re.IGNORECASE
    )
]
custom_paths = sorted(set(listed_paths) - set(expected_paths))
collisions = []
for depot_path in sorted(owners):
    archive_names = sorted(owners[depot_path])
    stale_self = "maximum-meow-phase0.archive" in archive_names
    collisions.append(
        {
            "depot_path": depot_path,
            "installed_archives": archive_names,
            "legacy_preview_self_collision": stale_self,
            "final_owner": (
                production_archive_name("ep1")
                if depot_path.startswith("ep1/")
                else production_archive_name("base")
            ),
            "expected_behavior": (
                "remove legacy preview archive before install; final ! archive otherwise loads first"
                if stale_self
                else "final ! archive loads first under ASCII first-wins and hides installed content at this exact path while active"
            ),
        }
    )

report = {
    "game_root": game_root.as_posix(),
    "installed_archive_count": len(archives),
    "target_depot_path_count": len(expected_paths),
    "exact_collision_path_count": len(collisions),
    "exact_collision_archive_count": len(
        {name for row in collisions for name in row["installed_archives"]}
    ),
    "installed_maximum_meow_archives": self_archives,
    "collisions": collisions,
    "custom_localization_paths_not_overridden": custom_paths,
    "index_parse_failures": index_failures,
    "wolvenkit_directory_scan_decompression_exceptions": raw_scan.count(
        "DecompressionException"
    ),
    "load_order_policy": {
        "rule": "legacy .archive conflicts are per-file; first archive in ASCII filename order wins",
        "source": "https://github.com/CDPR-Modding-Documentation/Cyberpunk-Modding-Docs/blob/main/for-mod-users/users-modding-cyberpunk-2077/load-order.md",
        "final_base_archive": production_archive_name("base"),
        "final_ep1_archive": production_archive_name("ep1"),
    },
    "limitations": [
        "Archive hashes prove same-depot-path ownership but do not identify which individual localization entries each installed owner changed.",
        "ArchiveXL new-key declarations remain outside the vanilla extracted corpus and are intentionally not transformed.",
        "WolvenKit logged four GuessFileType decompression exceptions during its directory scan despite exit code 0; direct version-12 index parsing succeeded for every installed archive.",
        "Combined in-game behavior has not been verified.",
    ],
}
if index_failures:
    raise SystemExit(f"installed archive indexes failed: {index_failures}")
output = reports_root / "installed-collision-audit.json"
output.write_bytes(canonical_json_bytes(report))
print(
    json.dumps(
        {
            "installed_archives": len(archives),
            "exact_collision_paths": len(collisions),
            "exact_collision_archives": report["exact_collision_archive_count"],
            "installed_self_archives": self_archives,
            "custom_localization_paths": len(custom_paths),
            "index_failures": len(index_failures),
            "wolvenkit_decompression_exceptions": report[
                "wolvenkit_directory_scan_decompression_exceptions"
            ],
        },
        indent=2,
    )
)
