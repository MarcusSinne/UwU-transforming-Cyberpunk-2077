from __future__ import annotations

import re

import pytest

from maximum_meow.transformer import (
    PRODUCTION_SEED,
    SAFE_ASCII_EMOTES,
    TransformContext,
    UnknownMarkupError,
    extract_visible_directive_payloads,
    extract_structural_tokens,
    transform_visible_text,
)


def ctx(surface: str = "prose") -> TransformContext:
    return TransformContext(
        seed="game-of-the-nya-v1",
        resource="base/localization/en-us/onscreens/onscreens.json",
        entry_id="1141907775134830592",
        field="femaleVariant",
        surface=surface,
    )


def test_production_seed_matches_locked_spec() -> None:
    assert PRODUCTION_SEED == "game-of-the-nya-v1"


def test_plain_text_changes_deterministically() -> None:
    source = "Bring the parcel tomorrow!"
    first = transform_visible_text(source, ctx())
    second = transform_visible_text(source, ctx())

    assert first == second
    assert first != source
    assert "w" in first.lower()


def test_compact_surface_uses_readable_phonetics_without_decorations() -> None:
    output = transform_visible_text("Interface", ctx("compact"))

    assert output == "Intewface"
    assert not re.search(r"\b[A-Za-z]-[A-Za-z]", output)
    assert "*" not in output
    assert not re.search(r"UwU|OwO|:3|>w<", output)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Settings", "Settingz"),
        ("Sound", "Sownd"),
        ("Video", "Videow"),
        ("Ammo", "Ammow"),
        ("Quit", "Qwit"),
        ("Exit", "Eksit"),
        ("Back", "Bak"),
        ("OK", "OKI"),
        ("Map", "Myap"),
        ("Key", "Kyey"),
        ("Game", "Gyame"),
        ("Me", "Mye"),
        ("On", "Own"),
        ("It", "Wit"),
        ("Why", "Whwy"),
        ("Sky", "Skwy"),
        ("By", "Bwy"),
        ("DATA", "DYATA"),
    ],
)
def test_compact_fallback_phonetics_cover_common_menu_leaks(
    source: str, expected: str
) -> None:
    result = transform_visible_text(source, ctx(surface="compact"))

    assert result == expected


def test_prose_stutters_and_embellishments_are_occasional_not_universal() -> None:
    outputs = [
        transform_visible_text(
            "Meet the courier at sunrise.",
            TransformContext(
                seed="game-of-the-nya-v1",
                resource="base/localization/en-us/onscreens/onscreens.json",
                entry_id=str(index),
                field="femaleVariant",
                surface="prose",
            ),
        )
        for index in range(128)
    ]

    stuttered = sum(bool(re.search(r"\b[A-Za-z]-[A-Za-z]", output)) for output in outputs)
    embellished = sum(
        " — " in output or "*" in output or bool(re.search(r"UwU|OwO|:3|>w<", output))
        for output in outputs
    )

    assert 0 < stuttered < 64
    assert 0 < embellished < 64


def test_long_prose_stays_readable_and_always_carries_one_emoticon() -> None:
    source = (
        "The tiny blue courier crossed the cardboard city before sunrise, carrying "
        "three paper lanterns and a map drawn entirely in purple ink. Nobody asked "
        "why the map smelled like cinnamon, which was probably for the best."
    )

    output = transform_visible_text(source, ctx("prose"))
    face_pattern = "|".join(re.escape(face) for face in SAFE_ASCII_EMOTES)
    body = re.sub(rf" (?:{face_pattern})$", "", output)
    body = re.sub(r"\b[A-Za-z]-(?=[A-Za-z])", "", body)
    source_words = re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", source)
    output_words = re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", body)
    changed = sum(left != right for left, right in zip(source_words, output_words, strict=True))

    assert re.search(rf" (?:{face_pattern})$", output)
    assert not re.search(r"ww", body, re.IGNORECASE)
    assert len(source_words) * 0.25 <= changed <= len(source_words) * 0.5


def test_short_prose_surfaces_emoticons_often_enough_to_be_visible() -> None:
    outputs = [
        transform_visible_text(
            "Anyway, the workshop lights are out.",
            TransformContext(
                seed=PRODUCTION_SEED,
                resource="base/localization/en-us/subtitles/scene.json",
                entry_id=str(index),
                field="femaleVariant",
                surface="prose",
            ),
        )
        for index in range(128)
    ]

    face_pattern = "|".join(re.escape(face) for face in SAFE_ASCII_EMOTES)
    faces = sum(bool(re.search(face_pattern, output)) for output in outputs)
    assert 24 <= faces < 64


@pytest.mark.parametrize(
    ("source", "expected_faces"),
    [
        (
            "The road continues through the district while everyone watches the traffic move beneath the towers.",
            {"UwU", ":3", "x3", "=3", "^w^", ".w.", "o3o", "(^-^)", "(uwu)", "(^w^)"},
        ),
        (
            "I love this wonderful day and I am so happy to see my beautiful friend waiting beside the bright lights.",
            {":D", "XD", ";)", ":')", "<3", "^_^"},
        ),
        (
            "What happened here and why is everyone staring at that strange machine near the entrance? Tell me now.",
            {"OwO", ">w<", ">_<", ":O", "(owo)", "(>w<)"},
        ),
        (
            "I am afraid of the pain and loss after our friend died alone, and now everything we loved is gone forever.",
            {"QwQ", "T_T", "T.T", ";_;", "D:", ":(", "</3"},
        ),
        (
            "I am tired and bored after waiting all night, so whatever happens next can wait until I finally sleep.",
            {"-w-", "-_-", ":P", "(-w-)"},
        ),
    ],
)
def test_long_prose_uses_every_safe_ascii_face_for_its_emotion(
    source: str, expected_faces: set[str]
) -> None:
    observed = set()
    for index in range(1024):
        output = transform_visible_text(
            source,
            TransformContext(
                seed=PRODUCTION_SEED,
                resource="base/localization/en-us/subtitles/emotion-test.json",
                entry_id=str(index),
                field="femaleVariant",
                surface="prose",
            ),
        )
        matches = [face for face in expected_faces if output.endswith(f" {face}")]
        assert len(matches) == 1, output
        observed.add(matches[0])

    assert observed == expected_faces


@pytest.mark.parametrize(
    ("source", "entry_id"),
    [("Security Patrol Cart", "primaryKey=37338"), ("Switch", "primaryKey=39361")],
)
def test_prose_density_selects_a_word_that_remains_readably_changed(
    source: str, entry_id: str
) -> None:
    output = transform_visible_text(
        source,
        TransformContext(
            seed=PRODUCTION_SEED,
            resource="base/localization/en-us/onscreens/onscreens.json",
            entry_id=entry_id,
            field="femaleVariant",
            surface="prose",
        ),
    )
    body = re.sub(
        r" (?:UwU|OwO|:3|>w<|\*[^*]+\*)$| — (?:nya|meow|nyaa|mrow)!$",
        "",
        output,
    )

    assert body != source
    assert not re.search(r"ww", body, re.IGNORECASE)


def test_structural_tokens_numbers_and_escapes_survive_exactly() -> None:
    source = (
        '<Rich color="MainColors.Gold">Press and hold</> '
        '<Input actionName="RangedADS" color="MainColors.Blue" hold="Show"></> '
        'for {quantity,number} items at 70%\\nNow.'
    )
    output = transform_visible_text(source, ctx())

    assert output != source
    assert extract_structural_tokens(output) == extract_structural_tokens(source)
    assert "{quantity,number}" in output
    assert "70%" in output
    assert "\\n" in output


def test_embellishment_cannot_split_hyphenated_identifier_from_protected_number() -> None:
    source = "Send to krcpp-17."
    context = TransformContext(
        seed="ultimate-uwu-meowification-nyaa-v1",
        resource="base/localization/en-us/onscreens/onscreens.json",
        entry_id="primaryKey=7481",
        field="femaleVariant",
        surface="prose",
    )

    output = transform_visible_text(source, context)

    assert "kwcpp-17" in output
    assert extract_structural_tokens(output) == extract_structural_tokens(source)


def test_mothertongue_payload_changes_but_directive_shape_survives() -> None:
    source = '<mothertongue l="syn" m="Luma tora" b="" a=". Carry the parcel outside!"/>'
    output = transform_visible_text(source, ctx())

    assert output != source
    assert output.startswith('<mothertongue l="syn" m="')
    assert ' b="" a="' in output
    assert output.endswith('"/>')
    assert 'l="syn"' in output
    assert 'a=". Cawwy de pawcew owtside!"' in output


def test_mothertongue_supports_escaped_rich_markup_inside_visible_attribute() -> None:
    source = (
        '<mothertongue l="syn" m="Sola merin" b="" '
        'a=", blue signal. Follow the <Rich color=\\"MainColors.ActiveBlue\\">'
        'lantern</>."/>'
    )

    output = transform_visible_text(source, ctx())

    assert '<Rich color=\\"MainColors.ActiveBlue\\">' in output
    assert "lantern" not in output
    assert output.startswith('<mothertongue l="syn" m="')
    assert output.endswith('"/>')


def test_mothertongue_short_payload_uses_two_letter_fallback() -> None:
    source = '<mothertongue l="syn" m="\'Lo?" b="" a=""/>'

    output = transform_visible_text(source, ctx())
    assert output != source
    assert output.startswith('<mothertongue l="syn" m="')


def test_kiroshi_translation_changes_but_language_and_original_survive() -> None:
    source = '<kiroshi l="syn" o="blue-cat-phrase" t="Good morning, courier." b="" a=""/>'

    output = transform_visible_text(source, ctx())

    assert output != source
    assert output.startswith('<kiroshi l="syn" o="blue-cat-phrase" ')
    assert 't="Gwood mownying, cowwiew."' in output
    assert output.endswith(' b="" a=""/>')


def test_kiroshi_supports_escaped_quotes_inside_translation() -> None:
    source = (
        '<kiroshi l="syn" o="paper-moon-phrase" '
        't="She wrote, \\"A paper moon waits.\\"" b="" a=""/>'
    )

    output = transform_visible_text(source, ctx())

    assert output.startswith('<kiroshi l="syn" o="paper-moon-phrase" t="')
    assert '\\"' in output
    assert "paper moon waits" not in output
    assert output.endswith(' b="" a=""/>')


def test_kiroshi_with_no_transformable_translation_stays_exact_for_ledger() -> None:
    source = '<kiroshi l="syn" o="nonlatin-sound" t="Pfff..." b="" a=""/>'

    assert transform_visible_text(source, ctx()) == source


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            '<kiroshi l="syn" o="short-sound" t="Hm." b="" a=""/>',
            ("Hm.",),
        ),
        (
            '<mothertongue l="syn" m="\'Hm?" b="" a=""/>',
            ("\'Hm?",),
        ),
        ("plain text", ()),
    ],
)
def test_visible_directive_payloads_exclude_language_and_original(
    source: str, expected: tuple[str, ...]
) -> None:
    assert extract_visible_directive_payloads(source) == expected


def test_malformed_kiroshi_directive_fails_loud() -> None:
    with pytest.raises(UnknownMarkupError, match="kiroshi"):
        transform_visible_text('<kiroshi l="jpn" t="Missing original"/>', ctx())


def test_unknown_markup_fails_loud() -> None:
    with pytest.raises(UnknownMarkupError, match="Blink"):
        transform_visible_text("Use <Blink speed=\"4\">this</Blink> now", ctx())


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("<", "<"),
        (">", ">"),
        ("[db_db][<<Back]", "[db_db][<<Bak]"),
        ("Thanks <3", "Dankz <3"),
        ("idx < DATA", "idkz < DYATA"),
    ],
)
def test_bare_angle_symbols_survive_as_visible_punctuation(
    source: str, expected: str
) -> None:
    assert transform_visible_text(source, ctx(surface="compact")) == expected


def test_code_comparison_operators_do_not_form_a_false_attribute_tag() -> None:
    source = "while idx < DATA_MAX; idx += value; while value > end"

    output = transform_visible_text(source, ctx(surface="compact"))

    assert output.count("<") == 1
    assert output.count(">") == 1
    assert output != source


def test_unclosed_known_markup_fails_loud() -> None:
    with pytest.raises(UnknownMarkupError, match="Rich"):
        transform_visible_text('<Rich color="MainColors.Gold" broken', ctx())


def test_image_markup_survives_exactly() -> None:
    source = '<Image id="MappinIcons.QuestMappin" width="75" height="75"></> Open radar.'
    output = transform_visible_text(source, ctx())

    assert '<Image id="MappinIcons.QuestMappin" width="75" height="75"></>' in output
    assert output != source


@pytest.mark.parametrize(
    ("source", "expected_span"),
    [
        ("Status: <TRANSFERRING DATA>", "<TWANSFEWWING DYATA>"),
        ("Department: <administration>", "<adminyistwation>"),
        ("Template: <fstream>", "<fstweam>"),
    ],
)
def test_attribute_free_angle_literals_transform_as_visible_text(
    source: str, expected_span: str
) -> None:
    output = transform_visible_text(source, ctx())

    assert expected_span in output


def test_empty_variant_stays_empty() -> None:
    assert transform_visible_text("", ctx()) == ""
