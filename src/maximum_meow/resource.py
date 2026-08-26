from __future__ import annotations

from copy import deepcopy
from collections import Counter
from dataclasses import dataclass
import re
from typing import Iterable

from .corpus import classify_surface
from .transformer import (
    TransformContext,
    extract_visible_directive_payloads,
    extract_structural_tokens,
    transform_visible_text,
)


class ResourceValidationError(ValueError):
    """Raised when a resource mutation exceeds the approved visible fields."""


def classify_unchanged_exception(value: str) -> str:
    if not re.search(r"[A-Za-z]", value):
        return "punctuation-or-numeric-only"

    directive_payloads = extract_visible_directive_payloads(value)
    if directive_payloads:
        classifications = [
            classify_unchanged_exception(payload) for payload in directive_payloads
        ]
        if "manual-review-required" in classifications:
            return "manual-review-required"
        for classification in (
            "consonant-utterance-or-acronym",
            "one-letter-name-or-code",
            "protected-structure-only",
            "punctuation-or-numeric-only",
        ):
            if classification in classifications:
                return classification
    if value.startswith(("<kiroshi", "<mothertongue")):
        return "protected-structure-only"

    remainder = value
    for token in extract_structural_tokens(value):
        remainder = remainder.replace(token, "", 1)
    if not re.search(r"[A-Za-z]", remainder):
        return "protected-structure-only"

    words = re.findall(r"[A-Za-z]+", remainder)
    if words and all(len(word) == 1 for word in words):
        return "one-letter-name-or-code"
    if words and all(
        not re.search(r"[aeiouy]", word, re.IGNORECASE) for word in words
    ):
        return "consonant-utterance-or-acronym"
    return "manual-review-required"


@dataclass(frozen=True)
class SampleSelection:
    category: str
    id_field: str
    id_value: str
    fields: tuple[str, ...]
    surface: str


def _entries(document: dict) -> list[dict]:
    try:
        entries = document["Data"]["RootChunk"]["root"]["Data"]["entries"]
    except (KeyError, TypeError) as exc:
        raise ResourceValidationError("unsupported localization resource schema") from exc
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ResourceValidationError("localization entries are not a list of objects")
    return entries


def _selection_map(selections: Iterable[SampleSelection]) -> dict[tuple[str, str], SampleSelection]:
    mapped: dict[tuple[str, str], SampleSelection] = {}
    for selection in selections:
        key = (selection.id_field, selection.id_value)
        if key in mapped:
            raise ResourceValidationError(f"duplicate selection {selection.id_field}={selection.id_value}")
        mapped[key] = selection
    return mapped


def transform_resource(
    source: dict,
    resource_path: str,
    selections: tuple[SampleSelection, ...],
    seed: str,
) -> tuple[dict, list[dict]]:
    output = deepcopy(source)
    header = output.setdefault("Header", {})
    header["ExportedDateTime"] = "1970-01-01T00:00:00Z"
    header["ArchiveFileName"] = resource_path

    mapped = _selection_map(selections)
    matched: set[tuple[str, str]] = set()
    report: list[dict] = []

    for entry in _entries(output):
        for key, selection in mapped.items():
            id_field, id_value = key
            if str(entry.get(id_field, "")) != id_value:
                continue
            matched.add(key)
            changed_fields: list[str] = []
            before: dict[str, str] = {}
            after: dict[str, str] = {}
            for field in selection.fields:
                value = entry.get(field)
                if not isinstance(value, str):
                    raise ResourceValidationError(
                        f"{id_field}={id_value} field {field} is not a string"
                    )
                before[field] = value
                if value == "":
                    after[field] = value
                    continue
                context = TransformContext(
                    seed=seed,
                    resource=resource_path,
                    entry_id=f"{id_field}={id_value}",
                    field=field,
                    surface=selection.surface,
                )
                transformed = transform_visible_text(value, context)
                if transformed == value:
                    raise ResourceValidationError(
                        f"{id_field}={id_value} field {field} did not change"
                    )
                entry[field] = transformed
                changed_fields.append(field)
                after[field] = transformed
            report.append(
                {
                    "category": selection.category,
                    "id_field": id_field,
                    "id_value": id_value,
                    "surface": selection.surface,
                    "changed_fields": changed_fields,
                    "before": before,
                    "after": after,
                }
            )

    missing = sorted(set(mapped) - matched)
    if missing:
        rendered = ", ".join(f"{field}={value}" for field, value in missing)
        raise ResourceValidationError(f"selection not found: {rendered}")

    report.sort(key=lambda row: (row["category"], row["id_field"], row["id_value"]))
    validate_resource_pair(source, output, selections)
    return output, report


def transform_full_resource(
    source: dict,
    resource_path: str,
    seed: str,
) -> tuple[dict, dict]:
    output = deepcopy(source)
    root_data = output.get("Data", {}).get("RootChunk", {}).get("root", {}).get("Data", {})
    root_type = root_data.get("$type")
    identifier_by_root = {
        "localizationPersistenceOnScreenEntries": "primaryKey",
        "localizationPersistenceSubtitleEntries": "stringId",
    }
    if root_type not in identifier_by_root:
        raise ResourceValidationError(f"unsupported root type: {root_type}")

    header = output.setdefault("Header", {})
    header["ExportedDateTime"] = "1970-01-01T00:00:00Z"
    header["ArchiveFileName"] = resource_path

    entries = _entries(output)
    identifier_field = identifier_by_root[root_type]
    surfaces: Counter[str] = Counter()
    nonblank_variants = 0
    changed_variants = 0
    unchanged_variants: list[dict] = []
    for index, entry in enumerate(entries):
        identifier = entry.get(identifier_field)
        if identifier is None:
            raise ResourceValidationError(
                f"entry {index} missing identifier field {identifier_field}"
            )
        entry_id = f"{identifier_field}={identifier}"
        secondary_key = str(entry.get("secondaryKey", ""))
        for field in ("femaleVariant", "maleVariant"):
            value = entry.get(field)
            if not isinstance(value, str):
                raise ResourceValidationError(f"{entry_id} field {field} is not a string")
            if value == "":
                continue
            nonblank_variants += 1
            surface = classify_surface(resource_path, secondary_key, value)
            surfaces[surface] += 1
            try:
                transformed = transform_visible_text(
                    value,
                    TransformContext(
                        seed=seed,
                        resource=resource_path,
                        entry_id=entry_id,
                        field=field,
                        surface=surface,
                    ),
                )
            except Exception as error:
                raise ResourceValidationError(
                    f"{entry_id} field {field}: {error}"
                ) from error
            if transformed == value:
                unchanged_variants.append(
                    {
                        "entry_id": entry_id,
                        "field": field,
                        "reason": classify_unchanged_exception(value),
                        "value": value,
                    }
                )
                continue
            entry[field] = transformed
            changed_variants += 1

    expected = deepcopy(source)
    expected.setdefault("Header", {})["ExportedDateTime"] = "1970-01-01T00:00:00Z"
    expected["Header"]["ArchiveFileName"] = resource_path
    for expected_entry, output_entry in zip(
        _entries(expected), entries, strict=True
    ):
        for field in ("femaleVariant", "maleVariant"):
            expected_entry[field] = output_entry[field]
    if expected != output:
        raise ResourceValidationError("full transform changed an unapproved field")

    return output, {
        "resource": resource_path,
        "root_type": root_type,
        "entry_count": len(entries),
        "nonblank_variants": nonblank_variants,
        "changed_variants": changed_variants,
        "unchanged_variants": unchanged_variants,
        "surfaces": dict(sorted(surfaces.items())),
    }


def validate_resource_pair(
    source: dict,
    output: dict,
    selections: tuple[SampleSelection, ...],
) -> None:
    source_entries = _entries(source)
    output_entries = _entries(output)
    if len(source_entries) != len(output_entries):
        raise ResourceValidationError("entry count changed")

    selected = _selection_map(selections)
    identifier_fields = ("$type", "primaryKey", "secondaryKey", "stringId")

    for index, (before, after) in enumerate(zip(source_entries, output_entries, strict=True)):
        for field in identifier_fields:
            if before.get(field) != after.get(field):
                raise ResourceValidationError(f"identifier changed at entry {index}: {field}")

        selection = next(
            (
                item
                for (field, value), item in selected.items()
                if str(before.get(field, "")) == value
            ),
            None,
        )
        allowed = set(selection.fields) if selection else set()
        all_fields = set(before) | set(after)
        for field in all_fields:
            if field in allowed:
                source_value = before.get(field)
                output_value = after.get(field)
                if source_value == "" and output_value != "":
                    raise ResourceValidationError(f"blank variant changed at entry {index}: {field}")
                if source_value not in (None, "") and source_value == output_value:
                    raise ResourceValidationError(f"selected field unchanged at entry {index}: {field}")
                continue
            if before.get(field) != after.get(field):
                raise ResourceValidationError(f"unapproved field changed at entry {index}: {field}")
