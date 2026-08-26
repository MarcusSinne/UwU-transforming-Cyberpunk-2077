from __future__ import annotations

import json
from pathlib import Path

from maximum_meow.resource import SampleSelection, transform_resource


ROOT = Path(__file__).resolve().parents[1]


def test_real_phase0_manifest_resolves_and_changes_every_nonblank_sample() -> None:
    config = json.loads((ROOT / "config" / "phase0-sample.json").read_text(encoding="utf-8"))
    report = []

    for resource in config["resources"]:
        source = json.loads((ROOT / resource["serialized_source"]).read_text(encoding="utf-8"))
        selections = tuple(
            SampleSelection(
                category=item["category"],
                id_field=item["id_field"],
                id_value=item["id_value"],
                fields=tuple(item["fields"]),
                surface=item["surface"],
            )
            for item in resource["selections"]
        )
        _, rows = transform_resource(
            source,
            resource["depot_path"],
            selections,
            config["seed"],
        )
        report.extend(rows)

    assert len(report) == 14
    assert {row["category"] for row in report} == {
        "plain onscreen label",
        "settings tab",
        "main-menu button",
        "item description with numeric placeholders",
        "quest title",
        "quest objective with currency quantity",
        "dialogue choice",
        "cinematic subtitle",
        "overhead subtitle",
        "long shard/message",
        "rich-text markup",
        "whole-string localization directive / gender variant",
        "input token",
        "Phantom Liberty expansion entry",
    }
    assert all(row["changed_fields"] for row in report)
