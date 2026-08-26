from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from maximum_meow.build import canonical_json_bytes, sha256_file
from maximum_meow.corpus import folder_serialization_command


parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--run-id", required=True)
parser.add_argument("--cli", type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
run_root = root / "build" / args.run_id
stage_root = run_root / "stage"
serialized_root = run_root / "serialized"
logs_root = run_root / "logs"
reports_root = run_root / "reports"
expected_counts = {"base": 3086, "ep1": 716}
rows: list[dict] = []

for corpus in ("base", "ep1"):
    corpus_stage = stage_root / corpus
    corpus_serialized = serialized_root / corpus
    if not corpus_stage.is_dir() or not corpus_serialized.is_dir():
        raise SystemExit(f"missing stage/serialized root for {corpus}")
    for stale in corpus_stage.rglob("*.json.json"):
        stale.unlink()
    binaries = sorted(
        path for path in corpus_stage.rglob("*.json") if not path.name.endswith(".json.json")
    )
    if len(binaries) != expected_counts[corpus]:
        raise SystemExit(f"{corpus} stage count drifted: {len(binaries)}")
    print(f"{corpus}: reserializing {len(binaries)} staged resources", flush=True)
    completed = subprocess.run(
        folder_serialization_command(args.cli.resolve(), corpus_stage),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined_output = completed.stdout + completed.stderr
    log_path = logs_root / f"{corpus}-roundtrip-serialize.log"
    log_path.write_text(combined_output, encoding="utf-8", newline="\n")
    logged_errors = re.findall(r"\[\s*\d+:\s*(?:Error|Warning)\s*\].*", combined_output)
    sidecars = [binary.with_name(f"{binary.name}.json") for binary in binaries]
    missing = [sidecar for sidecar in sidecars if not sidecar.is_file()]
    if completed.returncode != 0 or logged_errors or missing:
        raise SystemExit(
            f"{corpus} roundtrip serialization failed: returncode={completed.returncode}, "
            f"errors={logged_errors[:20]}, missing={len(missing)}; see {log_path}"
        )

    for binary, sidecar in zip(binaries, sidecars, strict=True):
        relative_sidecar = sidecar.relative_to(corpus_stage)
        expected_path = corpus_serialized / relative_sidecar
        if not expected_path.is_file():
            raise SystemExit(f"missing transformed source for roundtrip: {expected_path}")
        actual_document = json.loads(sidecar.read_text(encoding="utf-8"))
        expected_document = json.loads(expected_path.read_text(encoding="utf-8"))
        if actual_document.get("Data") != expected_document.get("Data"):
            raise SystemExit(f"semantic roundtrip mismatch: {corpus}:{binary.relative_to(corpus_stage)}")
        rows.append(
            {
                "corpus": corpus,
                "depot_path": binary.relative_to(corpus_stage).as_posix(),
                "cr2w_sha256": sha256_file(binary),
                "semantic_data_sha256": hashlib.sha256(
                    canonical_json_bytes(actual_document["Data"])
                ).hexdigest(),
                "semantic_data_match": True,
            }
        )
        sidecar.unlink()
    print(f"{corpus}: {len(binaries)} semantic roundtrips matched", flush=True)

rows.sort(key=lambda row: (row["corpus"], row["depot_path"]))
if len(rows) != 3802:
    raise SystemExit(f"roundtrip resource count mismatch: {len(rows)}")
(reports_root / "semantic-roundtrip.json").write_bytes(canonical_json_bytes(rows))
print(json.dumps({"run_id": args.run_id, "semantic_roundtrips": len(rows)}, indent=2))
