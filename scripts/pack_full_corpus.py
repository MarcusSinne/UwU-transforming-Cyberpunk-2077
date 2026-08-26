from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from maximum_meow.build import (
    _run_cli,
    canonical_json_bytes,
    normalize_redarchive_timestamps,
    production_archive_name,
    sha256_file,
    validate_staged_cr2w_manifest,
)


parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--run-id", required=True)
parser.add_argument("--cli", type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
run_root = root / "build" / args.run_id
stage_root = run_root / "stage"
archives_root = run_root / "archives"
logs_root = run_root / "logs"
reports_root = run_root / "reports"
compiled_manifest_path = reports_root / "compiled-resource-manifest.json"
if not compiled_manifest_path.is_file():
    raise SystemExit(f"missing compiled manifest: {compiled_manifest_path}")
compiled_manifest = json.loads(compiled_manifest_path.read_text(encoding="utf-8"))
if archives_root.exists():
    shutil.rmtree(archives_root)
archives_root.mkdir(parents=True)

package_rows: list[dict] = []
for corpus in ("base", "ep1"):
    corpus_stage = stage_root / corpus
    expected_paths = sorted(
        row["depot_path"] for row in compiled_manifest if row["corpus"] == corpus
    )
    validate_staged_cr2w_manifest(corpus_stage, compiled_manifest, corpus)
    pack_output = archives_root / f"{corpus}-pack"
    pack_output.mkdir(parents=True)
    print(f"{corpus}: packing {len(expected_paths)} resources", flush=True)
    _run_cli(
        args.cli.resolve(),
        ["pack", str(corpus_stage), "-o", str(pack_output), "-v", "Detailed"],
        logs_root / f"{corpus}-pack.log",
    )
    candidates = sorted(pack_output.glob("*.archive"))
    if len(candidates) != 1:
        raise SystemExit(f"{corpus} pack produced {len(candidates)} archives")
    final_archive = archives_root / production_archive_name(corpus)
    normalize_redarchive_timestamps(candidates[0])
    shutil.copyfile(candidates[0], final_archive)
    listing = _run_cli(
        args.cli.resolve(),
        ["archive", str(final_archive), "--list", "-v", "Detailed"],
        logs_root / f"{corpus}-archive-list.log",
    )
    actual_paths = sorted(
        line.strip().replace("\\", "/")
        for line in listing.splitlines()
        if line.strip().lower().endswith(".json")
    )
    if actual_paths != expected_paths:
        missing = sorted(set(expected_paths) - set(actual_paths))
        extra = sorted(set(actual_paths) - set(expected_paths))
        raise SystemExit(
            f"{corpus} archive listing mismatch: missing={missing[:20]}, extra={extra[:20]}"
        )
    package_rows.append(
        {
            "corpus": corpus,
            "filename": final_archive.name,
            "sha256": sha256_file(final_archive),
            "size": final_archive.stat().st_size,
            "entry_count": len(actual_paths),
            "depot_paths": actual_paths,
        }
    )
    print(f"{corpus}: archive readback matched {len(actual_paths)} paths", flush=True)

(reports_root / "package-manifest.json").write_bytes(canonical_json_bytes(package_rows))
print(json.dumps(package_rows, indent=2)[:4000])
