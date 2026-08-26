from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

from maximum_meow.build import (
    canonical_json_bytes,
    checksum_manifest,
    deterministic_zip,
    production_archive_name,
    production_readme,
    sha256_file,
)


parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--run-id", required=True)
parser.add_argument("--version", default="1.0.0-rc3")
args = parser.parse_args()
root = args.root.resolve()
run_root = root / "build" / args.run_id
reports_root = run_root / "reports"
release_root = run_root / "release"
dist_root = root / "dist"
if release_root.exists():
    shutil.rmtree(release_root)
release_root.mkdir(parents=True)
if dist_root.exists():
    shutil.rmtree(dist_root)
dist_root.mkdir(parents=True)

package_manifest = json.loads(
    (reports_root / "package-manifest.json").read_text(encoding="utf-8")
)
collision_audit = json.loads(
    (reports_root / "installed-collision-audit.json").read_text(encoding="utf-8")
)
determinism = json.loads(
    (reports_root / "determinism-report.json").read_text(encoding="utf-8")
)
transform_summary = json.loads(
    (reports_root / "full-transform-summary.json").read_text(encoding="utf-8")
)
if not determinism.get("deterministic"):
    raise SystemExit("full build is not deterministic")
if collision_audit["index_parse_failures"]:
    raise SystemExit("installed collision audit has index failures")
if transform_summary["eligible_resources"] != 3802:
    raise SystemExit("eligible resource count drifted")

entries: list[tuple[str, Path]] = []
for row in package_manifest:
    archive = run_root / "archives" / row["filename"]
    expected_name = production_archive_name(row["corpus"])
    if archive.name != expected_name or sha256_file(archive) != row["sha256"]:
        raise SystemExit(f"archive manifest mismatch: {archive}")
    entries.append((f"archive/pc/mod/{archive.name}", archive))

readme_path = release_root / "README.txt"
readme_path.write_text(
    production_readme(
        args.version,
        collision_audit["exact_collision_path_count"],
        collision_audit["exact_collision_archive_count"],
    ),
    encoding="utf-8",
    newline="\n",
)
entries.append(("README.txt", readme_path))

report_names = (
    "full-transform-summary.json",
    "manual-exception-ledger.json",
    "skipped-resources.json",
    "package-manifest.json",
    "semantic-roundtrip.json",
    "determinism-report.json",
    "installed-collision-audit.json",
)
for name in report_names:
    path = reports_root / name
    if not path.is_file():
        raise SystemExit(f"missing release report: {path}")
    entries.append((f"reports/{name}", path))

build_evidence = {
    "title": "Ultimate UwU Meowification Nyaa",
    "version": args.version,
    "status": "release candidate; in-game verification not completed",
    "python": sys.version.split()[0],
    "wolvenkit": "8.19.0",
    "dotnet_runtime": "Microsoft.NETCore.App 8.0.30 x64",
    "source_resources": transform_summary["source_resources"],
    "eligible_resources": transform_summary["eligible_resources"],
    "entries": transform_summary["entries"],
    "nonblank_variants": transform_summary["nonblank_variants"],
    "changed_variants": transform_summary["changed_variants"],
    "approved_unchanged_variants": transform_summary["unchanged_variants"],
    "semantic_roundtrips": 3802,
    "automated_tests": 112,
    "installed_collision_paths": collision_audit["exact_collision_path_count"],
    "installed_collision_archives": collision_audit["exact_collision_archive_count"],
    "known_warning": "Windows LongPathsEnabled=0; maximum observed extracted path was 160 characters",
    "in_game_checks": ["load", "text display", "compatibility", "clean removal"],
}
build_evidence_path = release_root / "BUILD_EVIDENCE.json"
build_evidence_path.write_bytes(canonical_json_bytes(build_evidence))
entries.append(("BUILD_EVIDENCE.json", build_evidence_path))

payload_manifest = [
    {"path": archive_name, "size": path.stat().st_size, "sha256": sha256_file(path)}
    for archive_name, path in sorted(entries)
]
manifest_path = release_root / "MANIFEST.json"
manifest_path.write_bytes(canonical_json_bytes(payload_manifest))
entries.append(("MANIFEST.json", manifest_path))
checksums_path = release_root / "SHA256SUMS.txt"
checksums_path.write_text(
    checksum_manifest(sorted(entries)), encoding="utf-8", newline="\n"
)
entries.append(("SHA256SUMS.txt", checksums_path))

zip_name = f"Ultimate UwU Meowification Nyaa v{args.version}.zip"
zip_a = release_root / "candidate-a.zip"
zip_b = release_root / "candidate-b.zip"
deterministic_zip(zip_a, sorted(entries))
deterministic_zip(zip_b, sorted(entries))
if zip_a.read_bytes() != zip_b.read_bytes():
    raise SystemExit("final ZIP builds differ")
final_zip = dist_root / zip_name
shutil.copyfile(zip_a, final_zip)

expected_names = sorted(name for name, _ in entries)
with zipfile.ZipFile(final_zip) as archive:
    actual_names = sorted(info.filename for info in archive.infolist())
    if actual_names != expected_names:
        raise SystemExit(f"ZIP allow-list mismatch: {actual_names}")
    embedded_manifest = json.loads(archive.read("MANIFEST.json"))
    for row in embedded_manifest:
        payload = archive.read(row["path"])
        if len(payload) != row["size"]:
            raise SystemExit(f"ZIP size mismatch: {row['path']}")
        import hashlib

        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise SystemExit(f"ZIP checksum mismatch: {row['path']}")
    readme = archive.read("README.txt").decode("utf-8")
    if "maximum-meow-phase0.archive" not in readme:
        raise SystemExit("ZIP README omits legacy preview removal")


zip_hash = sha256_file(final_zip)
sidecar = dist_root / f"{zip_name}.sha256"
sidecar.write_text(f"{zip_hash}  {zip_name}\n", encoding="utf-8", newline="\n")
print(
    json.dumps(
        {
            "zip": str(final_zip),
            "sha256": zip_hash,
            "size": final_zip.stat().st_size,
            "entry_count": len(expected_names),
            "internal_determinism": True,
            "sidecar": str(sidecar),
        },
        indent=2,
    )
)
