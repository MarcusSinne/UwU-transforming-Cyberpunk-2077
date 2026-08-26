from __future__ import annotations

from copy import deepcopy

import pytest

from maximum_meow.resource import (
    ResourceValidationError,
    SampleSelection,
    classify_unchanged_exception,
    transform_full_resource,
    transform_resource,
    validate_resource_pair,
)


def document() -> dict:
    return {
        "Header": {
            "WolvenKitVersion": "8.19.0",
            "ExportedDateTime": "volatile",
            "ArchiveFileName": "C:\\volatile\\onscreens.json",
        },
        "Data": {
            "RootChunk": {
                "root": {
                    "Data": {
                        "$type": "localizationPersistenceOnScreenEntries",
                        "entries": [
                            {
                                "$type": "localizationPersistenceOnScreenEntry",
                                "primaryKey": "40",
                                "secondaryKey": "Gameplay-News",
                                "femaleVariant": "News",
                                "maleVariant": "",
                            },
                            {
                                "$type": "localizationPersistenceOnScreenEntry",
                                "primaryKey": "41",
                                "secondaryKey": "Gameplay-Files",
                                "femaleVariant": "Files",
                                "maleVariant": "",
                            },
                        ],
                    }
                }
            }
        },
    }


def selection() -> SampleSelection:
    return SampleSelection(
        category="compact_label",
        id_field="primaryKey",
        id_value="40",
        fields=("femaleVariant", "maleVariant"),
        surface="compact",
    )


def test_only_selected_visible_variants_change() -> None:
    source = document()
    output, report = transform_resource(
        source,
        resource_path="base/localization/en-us/onscreens/onscreens.json",
        selections=(selection(),),
        seed="game-of-the-nya-v1",
    )

    entries = output["Data"]["RootChunk"]["root"]["Data"]["entries"]
    assert entries[0]["femaleVariant"] != "News"
    assert entries[0]["maleVariant"] == ""
    assert entries[1] == source["Data"]["RootChunk"]["root"]["Data"]["entries"][1]
    assert report[0]["changed_fields"] == ["femaleVariant"]
    validate_resource_pair(source, output, (selection(),))


def test_transform_is_deterministic_and_normalizes_volatile_header() -> None:
    first, _ = transform_resource(document(), "base/onscreens.json", (selection(),), "seed")
    second_source = document()
    second_source["Header"]["ExportedDateTime"] = "different"
    second_source["Header"]["ArchiveFileName"] = "D:\\elsewhere\\onscreens.json"
    second, _ = transform_resource(second_source, "base/onscreens.json", (selection(),), "seed")

    assert first == second
    assert first["Header"]["ExportedDateTime"] == "1970-01-01T00:00:00Z"
    assert first["Header"]["ArchiveFileName"] == "base/onscreens.json"


def test_missing_selection_fails_loud() -> None:
    missing = SampleSelection("missing", "primaryKey", "999", ("femaleVariant",), "prose")
    with pytest.raises(ResourceValidationError, match="999"):
        transform_resource(document(), "base/onscreens.json", (missing,), "seed")


def test_validator_rejects_changed_identifier() -> None:
    source = document()
    output, _ = transform_resource(source, "base/onscreens.json", (selection(),), "seed")
    output["Data"]["RootChunk"]["root"]["Data"]["entries"][0]["secondaryKey"] = "changed"

    with pytest.raises(ResourceValidationError, match="identifier"):
        validate_resource_pair(source, output, (selection(),))


def test_full_onscreen_resource_transforms_all_eligible_variants_and_reports_leaks() -> None:
    source = document()
    entries = source["Data"]["RootChunk"]["root"]["Data"]["entries"]
    entries[0]["femaleVariant"] = "Settings"
    entries[0]["secondaryKey"] = "UI-Settings-Title"
    entries[1]["femaleVariant"] = "B"

    output, report = transform_full_resource(
        source,
        "base/localization/en-us/onscreens/onscreens.json",
        "production-seed-v1",
    )

    output_entries = output["Data"]["RootChunk"]["root"]["Data"]["entries"]
    assert output_entries[0]["femaleVariant"] == "Settingz"
    assert output_entries[0]["maleVariant"] == ""
    assert output_entries[1]["femaleVariant"] == "B"
    assert report["root_type"] == "localizationPersistenceOnScreenEntries"
    assert report["entry_count"] == 2
    assert report["nonblank_variants"] == 2
    assert report["changed_variants"] == 1
    assert report["unchanged_variants"] == [
        {
            "entry_id": "primaryKey=41",
            "field": "femaleVariant",
            "reason": "one-letter-name-or-code",
            "value": "B",
        }
    ]
    assert output["Header"]["ArchiveFileName"] == "base/localization/en-us/onscreens/onscreens.json"
    assert source["Header"]["ExportedDateTime"] == "volatile"


def test_full_subtitle_resource_uses_string_id_and_prose_policy() -> None:
    source = document()
    data = source["Data"]["RootChunk"]["root"]["Data"]
    data["$type"] = "localizationPersistenceSubtitleEntries"
    data["entries"] = [
        {
            "$type": "localizationPersistenceSubtitleEntry",
            "stringId": "123",
            "femaleVariant": "Bring the parcel tomorrow!",
            "maleVariant": "",
        }
    ]

    output, report = transform_full_resource(
        source,
        "base/localization/en-us/subtitles/quest/q001/line.json",
        "production-seed-v1",
    )

    entry = output["Data"]["RootChunk"]["root"]["Data"]["entries"][0]
    assert entry["stringId"] == "123"
    assert entry["femaleVariant"] != "Bring the parcel tomorrow!"
    assert report["surfaces"] == {"prose": 1}


def test_full_transform_rejects_subtitle_map_metadata() -> None:
    source = document()
    source["Data"]["RootChunk"]["root"]["Data"]["$type"] = (
        "localizationPersistenceSubtitleMap"
    )

    with pytest.raises(ResourceValidationError, match="unsupported root type"):
        transform_full_resource(source, "base/localization/en-us/subtitles/subtitle_map.json", "seed")


def test_full_transform_error_names_entry_and_variant() -> None:
    source = document()
    source["Data"]["RootChunk"]["root"]["Data"]["entries"][0]["femaleVariant"] = (
        '<Blink speed="4">broken</Blink>'
    )

    with pytest.raises(
        ResourceValidationError,
        match=r"primaryKey=40 field femaleVariant: Unknown markup",
    ):
        transform_full_resource(source, "base/localization/en-us/onscreens/onscreens.json", "seed")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("...", "punctuation-or-numeric-only"),
        ("2076", "punctuation-or-numeric-only"),
        ("{Name} {Surname}", "protected-structure-only"),
        ('<Input context="UIMenu" actionName="Back"></>', "protected-structure-only"),
        ("B", "one-letter-name-or-code"),
        ("Mhm.", "consonant-utterance-or-acronym"),
        ("QRT", "consonant-utterance-or-acronym"),
        (
            '<kiroshi l="syn" o="short-sound" t="Hm." b="" a=""/>',
            "consonant-utterance-or-acronym",
        ),
        ("Normal English", "manual-review-required"),
    ],
)
def test_unchanged_exception_classifier_has_bounded_approval_classes(
    value: str, expected: str
) -> None:
    assert classify_unchanged_exception(value) == expected
