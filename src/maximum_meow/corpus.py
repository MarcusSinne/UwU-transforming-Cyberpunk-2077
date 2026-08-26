from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import groupby
from pathlib import Path


@dataclass(frozen=True)
class SerializationBatch:
    relative_parent: Path
    files: tuple[Path, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def serialization_manifest_row(
    corpus: str,
    source_path: Path,
    source_root: Path,
    serialized_path: Path,
    project_root: Path,
) -> dict[str, str | int]:
    return {
        "corpus": corpus,
        "source": source_path.resolve().relative_to(source_root.resolve()).as_posix(),
        "serialized": serialized_path.resolve().relative_to(project_root.resolve()).as_posix(),
        "source_size": source_path.stat().st_size,
        "serialized_size": serialized_path.stat().st_size,
        "source_sha256": _sha256(source_path),
        "serialized_sha256": _sha256(serialized_path),
    }


def validate_serialization_manifest(rows: list[dict], project_root: Path) -> None:
    root = project_root.resolve()
    seen: set[tuple[str, str]] = set()
    expected_serialized: set[Path] = set()
    for row in rows:
        corpus = str(row["corpus"])
        source_text = str(row["source"])
        identity = (corpus, source_text.casefold())
        if identity in seen:
            raise ValueError(f"duplicate serialization manifest row: {corpus}:{source_text}")
        seen.add(identity)
        source = root / "source" / corpus / source_text
        serialized = root / str(row["serialized"])
        expected_serialized.add(serialized.resolve())
        checks = {
            "source_size": source.stat().st_size,
            "serialized_size": serialized.stat().st_size,
            "source_sha256": _sha256(source),
            "serialized_sha256": _sha256(serialized),
        }
        for field, actual in checks.items():
            if row.get(field) != actual:
                raise ValueError(
                    f"serialization manifest mismatch for {corpus}:{source_text} field {field}"
                )
    actual_serialized = {
        path.resolve() for path in (root / "raw" / "full").rglob("*.json.json")
    }
    if actual_serialized != expected_serialized:
        raise ValueError("serialization manifest file set mismatch")


_PROSE_KEY_MARKERS = (
    "description",
    "objective",
    "message",
    "content",
    "tooltip",
    "shard",
    "journal",
    "email",
    "brief",
)


def classify_surface(resource_path: str, secondary_key: str, text: str) -> str:
    normalized_resource = resource_path.replace("\\", "/").lower()
    if "/subtitles/" in normalized_resource:
        return "prose"
    if "\\n" in text or "\n" in text or "\r" in text or len(text) > 80:
        return "prose"
    normalized_key = secondary_key.lower()
    if any(marker in normalized_key for marker in _PROSE_KEY_MARKERS):
        return "prose"
    return "compact"


def serialized_sidecar_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.name}.json")


def depot_path_from_sidecar(sidecar_path: Path, corpus_root: Path) -> Path:
    if not sidecar_path.name.endswith(".json.json"):
        raise ValueError(f"serialized sidecar must end with .json.json: {sidecar_path}")
    relative = sidecar_path.resolve().relative_to(corpus_root.resolve())
    return relative.with_name(relative.name.removesuffix(".json"))


def deserialized_binary_path(sidecar_path: Path) -> Path:
    if not sidecar_path.name.endswith(".json.json"):
        raise ValueError(f"serialized sidecar must end with .json.json: {sidecar_path}")
    return sidecar_path.with_name(sidecar_path.name.removesuffix(".json"))


def folder_deserialization_command(cli: Path, serialized_root: Path) -> tuple[str, ...]:
    return (
        str(cli),
        "convert",
        "deserialize",
        str(serialized_root.resolve()),
        "-v",
        "Minimal",
    )


def folder_serialization_command(cli: Path, source_root: Path) -> tuple[str, ...]:
    return (
        str(cli),
        "convert",
        "serialize",
        str(source_root.resolve()),
        "-v",
        "Minimal",
    )


def serialization_batches(
    files: list[Path],
    source_root: Path,
    *,
    max_files: int = 64,
    max_path_characters: int = 24_000,
) -> tuple[SerializationBatch, ...]:
    source_root = source_root.resolve()
    normalized: list[Path] = []
    for file_path in files:
        resolved = file_path.resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError as error:
            raise ValueError(f"file outside source root: {resolved}") from error
        normalized.append(resolved)

    batches: list[SerializationBatch] = []
    for parent, grouped in groupby(sorted(normalized), key=lambda path: path.parent):
        relative_parent = parent.relative_to(source_root)
        current: list[Path] = []
        current_cost = 0
        for file_path in grouped:
            path_cost = len(str(file_path))
            would_overflow = current and (
                len(current) >= max_files
                or current_cost + path_cost > max_path_characters
            )
            if would_overflow:
                batches.append(SerializationBatch(relative_parent, tuple(current)))
                current = []
                current_cost = 0
            current.append(file_path)
            current_cost += path_cost
        if current:
            batches.append(SerializationBatch(relative_parent, tuple(current)))
    return tuple(batches)
