from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from maximum_meow.corpus import (
    folder_serialization_command,
    serialization_manifest_row,
    serialized_sidecar_path,
)


parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--cli", type=Path, required=True)
parser.add_argument("--clean", action="store_true")
args = parser.parse_args()
root = args.root.resolve()
cli = args.cli.resolve()
out_root = root / "raw" / "full"
log_path = root / "logs" / "full-serialize.log"
manifest_path = root / "reports" / "full-serialization-manifest.json"

if out_root.exists():
    if not args.clean:
        raise SystemExit(f"output exists; pass --clean: {out_root}")
    shutil.rmtree(out_root)
out_root.mkdir(parents=True)
log_path.parent.mkdir(parents=True, exist_ok=True)
manifest_path.parent.mkdir(parents=True, exist_ok=True)

manifest: list[dict] = []
with log_path.open("w", encoding="utf-8", newline="\n") as log:
    for corpus in ("base", "ep1"):
        source_root = root / "source" / corpus
        for stale_sidecar in source_root.rglob("*.json.json"):
            stale_sidecar.unlink()
        files = sorted(source_root.rglob("*.json"))
        print(f"{corpus}: serializing {len(files)} files in one WolvenKit process", flush=True)
        completed = subprocess.run(
            folder_serialization_command(cli, source_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        combined_output = completed.stdout + completed.stderr
        log.write(f"\n## {corpus}\n{combined_output}")
        log.flush()
        logged_errors = re.findall(r"\[\s*\d+:\s*(?:Error|Warning)\s*\].*", combined_output)
        sidecars = [serialized_sidecar_path(source_path) for source_path in files]
        missing = [sidecar for sidecar in sidecars if not sidecar.is_file()]
        if completed.returncode != 0 or logged_errors or missing:
            for sidecar in sidecars:
                sidecar.unlink(missing_ok=True)
            details = {
                "returncode": completed.returncode,
                "logged_errors": logged_errors[:20],
                "missing_count": len(missing),
            }
            raise SystemExit(f"WolvenKit serialization failed for {corpus}: {details}; see {log_path}")

        for source_path, sidecar in zip(files, sidecars, strict=True):
            output_path = out_root / corpus / sidecar.relative_to(source_root)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sidecar, output_path)
            manifest.append(
                serialization_manifest_row(corpus, source_path, source_root, output_path, root)
            )
            sidecar.unlink()
        print(f"{corpus}: collected {len(files)} serialized resources", flush=True)

manifest.sort(key=lambda row: (row["corpus"], row["source"]))
manifest_path.write_text(
    json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
    newline="\n",
)
print(json.dumps({"files": len(manifest), "manifest": str(manifest_path)}, indent=2))
