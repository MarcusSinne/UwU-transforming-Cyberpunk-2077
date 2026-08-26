from __future__ import annotations

import argparse
import json
from pathlib import Path

from maximum_meow.build import canonical_json_bytes, sha256_file


parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--run-a", required=True)
parser.add_argument("--run-b", required=True)
args = parser.parse_args()
root = args.root.resolve()
a_root = root / "build" / args.run_a
b_root = root / "build" / args.run_b
checks: list[dict] = []

report_names = (
    "source-manifest.json",
    "resource-validation.json",
    "manual-exception-ledger.json",
    "skipped-resources.json",
    "compiled-resource-manifest.json",
    "semantic-roundtrip.json",
    "package-manifest.json",
)
for name in report_names:
    a_path = a_root / "reports" / name
    b_path = b_root / "reports" / name
    if not a_path.is_file() or not b_path.is_file():
        raise SystemExit(f"missing deterministic report {name}")
    a_value = json.loads(a_path.read_text(encoding="utf-8"))
    b_value = json.loads(b_path.read_text(encoding="utf-8"))
    if a_value != b_value:
        raise SystemExit(f"report differs across runs: {name}")
    checks.append({"kind": "report", "path": name, "sha256": sha256_file(a_path)})

for corpus in ("base", "ep1"):
    a_files = sorted((a_root / "serialized" / corpus).rglob("*.json.json"))
    b_files = sorted((b_root / "serialized" / corpus).rglob("*.json.json"))
    a_relative = [path.relative_to(a_root / "serialized" / corpus) for path in a_files]
    b_relative = [path.relative_to(b_root / "serialized" / corpus) for path in b_files]
    if a_relative != b_relative:
        raise SystemExit(f"{corpus} transformed tree paths differ")
    for relative, a_path, b_path in zip(a_relative, a_files, b_files, strict=True):
        a_hash = sha256_file(a_path)
        b_hash = sha256_file(b_path)
        if a_hash != b_hash:
            raise SystemExit(f"transformed JSON differs: {corpus}:{relative}")
    checks.append(
        {
            "kind": "transformed-tree",
            "corpus": corpus,
            "file_count": len(a_files),
            "identical": True,
        }
    )

for archive_name in (
    "!ultimate-uwu-meowification-nyaa-base.archive",
    "!ultimate-uwu-meowification-nyaa-phantom-liberty.archive",
):
    a_path = a_root / "archives" / archive_name
    b_path = b_root / "archives" / archive_name
    a_hash = sha256_file(a_path)
    b_hash = sha256_file(b_path)
    if a_hash != b_hash:
        raise SystemExit(f"archive differs across runs: {archive_name}")
    checks.append(
        {
            "kind": "archive",
            "filename": archive_name,
            "sha256": a_hash,
            "identical": True,
        }
    )

result = {
    "run_a": args.run_a,
    "run_b": args.run_b,
    "deterministic": True,
    "checks": checks,
}
output = b_root / "reports" / "determinism-report.json"
output.write_bytes(canonical_json_bytes(result))
print(json.dumps(result, indent=2))
