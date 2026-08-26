from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil

from maximum_meow.build import canonical_json_bytes, sha256_file, wolvenkit_json_bytes
from maximum_meow.corpus import depot_path_from_sidecar, validate_serialization_manifest
from maximum_meow.resource import transform_full_resource
from maximum_meow.transformer import PRODUCTION_SEED


parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--run-id", required=True)
parser.add_argument("--seed", default=PRODUCTION_SEED)
args = parser.parse_args()
root = args.root.resolve()
run_root = root / "build" / args.run_id
serialization_manifest_path = root / "reports" / "full-serialization-manifest.json"
serialization_manifest = json.loads(serialization_manifest_path.read_text(encoding="utf-8"))
try:
    validate_serialization_manifest(serialization_manifest, root)
except (KeyError, OSError, ValueError) as error:
    raise SystemExit(f"serialized input verification failed: {error}") from error
serialized_output_root = run_root / "serialized"
reports_root = run_root / "reports"
if run_root.exists():
    shutil.rmtree(run_root)
serialized_output_root.mkdir(parents=True)
reports_root.mkdir(parents=True)

root_types: Counter[str] = Counter()
tag_names: Counter[str] = Counter()
source_manifest: list[dict] = []
resource_reports: list[dict] = []
exceptions: list[dict] = []
skipped: list[dict] = []
totals: Counter[str] = Counter()

for corpus in ("base", "ep1"):
    corpus_root = root / "raw" / "full" / corpus
    source_root = root / "source" / corpus
    sidecars = sorted(corpus_root.rglob("*.json.json"))
    print(f"{corpus}: transforming {len(sidecars)} serialized resources", flush=True)
    for index, sidecar in enumerate(sidecars, 1):
        depot_path = depot_path_from_sidecar(sidecar, corpus_root)
        depot_text = depot_path.as_posix()
        source_path = source_root / depot_path
        if not source_path.is_file():
            raise SystemExit(f"missing binary source for {depot_text}: {source_path}")
        document = json.loads(sidecar.read_text(encoding="utf-8"))
        root_data = document.get("Data", {}).get("RootChunk", {}).get("root", {}).get("Data", {})
        root_type = str(root_data.get("$type", "<missing>"))
        root_types[root_type] += 1
        entries = root_data.get("entries", [])
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                for field in ("femaleVariant", "maleVariant"):
                    value = entry.get(field)
                    if not isinstance(value, str) or not value:
                        continue
                    for match in re.finditer(r"<\s*/?\s*([A-Za-z][A-Za-z0-9_-]*)\b[^<>]*>", value):
                        tag_names[match.group(1).lower()] += 1

        source_manifest.append(
            {
                "corpus": corpus,
                "depot_path": depot_text,
                "source_sha256": sha256_file(source_path),
                "serialized_source_sha256": sha256_file(sidecar),
                "root_type": root_type,
            }
        )
        if root_type == "localizationPersistenceSubtitleMap":
            skipped.append(
                {
                    "corpus": corpus,
                    "depot_path": depot_text,
                    "reason": "subtitle map metadata contains no visible variants",
                    "root_type": root_type,
                }
            )
            continue
        try:
            transformed, report = transform_full_resource(document, depot_text, args.seed)
        except Exception as error:
            raise SystemExit(f"transform failed for {corpus}:{depot_text}: {error}") from error

        output_path = serialized_output_root / corpus / sidecar.relative_to(corpus_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(wolvenkit_json_bytes(transformed))
        report["corpus"] = corpus
        report["output_sha256"] = sha256_file(output_path)
        for row in report.pop("unchanged_variants"):
            exceptions.append({"corpus": corpus, "depot_path": depot_text, **row})
        resource_reports.append(report)
        totals["resources"] += 1
        totals["entries"] += report["entry_count"]
        totals["nonblank_variants"] += report["nonblank_variants"]
        totals["changed_variants"] += report["changed_variants"]
        if index % 250 == 0 or index == len(sidecars):
            print(f"{corpus}: {index}/{len(sidecars)} resources", flush=True)

source_manifest.sort(key=lambda row: (row["corpus"], row["depot_path"]))
resource_reports.sort(key=lambda row: (row["corpus"], row["resource"]))
exceptions.sort(key=lambda row: (row["corpus"], row["depot_path"], row["entry_id"], row["field"]))
skipped.sort(key=lambda row: (row["corpus"], row["depot_path"]))
summary = {
    "run_id": args.run_id,
    "seed": args.seed,
    "source_resources": len(source_manifest),
    "eligible_resources": totals["resources"],
    "skipped_resources": len(skipped),
    "entries": totals["entries"],
    "nonblank_variants": totals["nonblank_variants"],
    "changed_variants": totals["changed_variants"],
    "unchanged_variants": len(exceptions),
    "root_types": dict(sorted(root_types.items())),
    "tag_names": dict(sorted(tag_names.items())),
}
if summary["source_resources"] != 3804:
    raise SystemExit(f"source resource count drifted: {summary['source_resources']} != 3804")
if summary["eligible_resources"] != 3802 or summary["skipped_resources"] != 2:
    raise SystemExit(f"eligible resource count drifted: {summary}")
if summary["changed_variants"] + summary["unchanged_variants"] != summary["nonblank_variants"]:
    raise SystemExit(f"variant accounting mismatch: {summary}")
manual_review = [row for row in exceptions if row["reason"] == "manual-review-required"]
if manual_review:
    raise SystemExit(
        "unchanged variants require manual review: "
        + json.dumps(manual_review[:20], ensure_ascii=False)
    )

(reports_root / "full-transform-summary.json").write_bytes(canonical_json_bytes(summary))
(reports_root / "source-manifest.json").write_bytes(canonical_json_bytes(source_manifest))
(reports_root / "resource-validation.json").write_bytes(canonical_json_bytes(resource_reports))
(reports_root / "manual-exception-ledger.json").write_bytes(canonical_json_bytes(exceptions))
(reports_root / "skipped-resources.json").write_bytes(canonical_json_bytes(skipped))
print(json.dumps(summary, indent=2, ensure_ascii=False))
