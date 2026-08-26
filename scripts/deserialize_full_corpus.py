from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from maximum_meow.build import canonical_json_bytes, normalize_file_times, sha256_file
from maximum_meow.corpus import (
    depot_path_from_sidecar,
    deserialized_binary_path,
    folder_deserialization_command,
)


parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--run-id", required=True)
parser.add_argument("--cli", type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
run_root = root / "build" / args.run_id
serialized_root = run_root / "serialized"
stage_root = run_root / "stage"
logs_root = run_root / "logs"
reports_root = run_root / "reports"
if not serialized_root.is_dir():
    raise SystemExit(f"missing transformed corpus: {serialized_root}")
if stage_root.exists():
    shutil.rmtree(stage_root)
stage_root.mkdir(parents=True)
logs_root.mkdir(parents=True, exist_ok=True)
reports_root.mkdir(parents=True, exist_ok=True)

manifest: list[dict] = []
expected_counts = {"base": 3086, "ep1": 716}
for corpus in ("base", "ep1"):
    corpus_serialized = serialized_root / corpus
    sidecars = sorted(corpus_serialized.rglob("*.json.json"))
    if len(sidecars) != expected_counts[corpus]:
        raise SystemExit(
            f"{corpus} transformed resource count drifted: {len(sidecars)} != {expected_counts[corpus]}"
        )
    for old_binary in corpus_serialized.rglob("*.json"):
        if not old_binary.name.endswith(".json.json"):
            old_binary.unlink()
    print(f"{corpus}: deserializing {len(sidecars)} resources", flush=True)
    completed = subprocess.run(
        folder_deserialization_command(args.cli.resolve(), corpus_serialized),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined_output = completed.stdout + completed.stderr
    log_path = logs_root / f"{corpus}-deserialize.log"
    log_path.write_text(combined_output, encoding="utf-8", newline="\n")
    logged_errors = re.findall(r"\[\s*\d+:\s*(?:Error|Warning)\s*\].*", combined_output)
    binaries = [deserialized_binary_path(sidecar) for sidecar in sidecars]
    missing = [binary for binary in binaries if not binary.is_file()]
    invalid = [binary for binary in binaries if binary.is_file() and binary.read_bytes()[:4] != b"CR2W"]
    if completed.returncode != 0 or logged_errors or missing or invalid:
        raise SystemExit(
            f"{corpus} deserialization failed: "
            f"returncode={completed.returncode}, errors={logged_errors[:20]}, "
            f"missing={len(missing)}, invalid={len(invalid)}; see {log_path}"
        )

    corpus_stage = stage_root / corpus
    for sidecar, binary in zip(sidecars, binaries, strict=True):
        depot_path = depot_path_from_sidecar(sidecar, corpus_serialized)
        staged = corpus_stage / depot_path
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binary, staged)
        normalize_file_times(staged)
        manifest.append(
            {
                "corpus": corpus,
                "depot_path": depot_path.as_posix(),
                "serialized_sha256": sha256_file(sidecar),
                "cr2w_sha256": sha256_file(staged),
                "cr2w_size": staged.stat().st_size,
            }
        )
    print(f"{corpus}: staged {len(sidecars)} CR2W resources", flush=True)

manifest.sort(key=lambda row: (row["corpus"], row["depot_path"]))
if len(manifest) != 3802:
    raise SystemExit(f"staged resource count mismatch: {len(manifest)}")
(reports_root / "compiled-resource-manifest.json").write_bytes(canonical_json_bytes(manifest))
print(json.dumps({"run_id": args.run_id, "staged_resources": len(manifest)}, indent=2))
