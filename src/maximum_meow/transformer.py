from __future__ import annotations

from dataclasses import dataclass, replace as dataclass_replace
import hashlib
import re


PRODUCTION_SEED = "game-of-the-nya-v1"
_FACES_BY_EMOTION = {
    "cute": ("UwU", ":3", "x3", "=3", "^w^", ".w.", "o3o", "(^-^)", "(uwu)", "(^w^)"),
    "happy": (":D", "XD", ";)", ":')", "<3", "^_^"),
    "curious": ("OwO", ">w<", ">_<", ":O", "(owo)", "(>w<)"),
    "distressed": ("QwQ", "T_T", "T.T", ";_;", "D:", ":(", "</3"),
    "tired": ("-w-", "-_-", ":P", "(-w-)"),
}
SAFE_ASCII_EMOTES = tuple(
    face for faces in _FACES_BY_EMOTION.values() for face in faces
)
_EMOTION_WORDS = {
    "distressed": {
        "afraid", "angry", "cry", "dead", "death", "died", "fear", "fuck",
        "gone", "hate", "hurt", "kill", "killed", "loss", "pain", "sad",
        "scared", "sorry", "terrible", "worried",
    },
    "happy": {
        "beautiful", "friend", "glad", "good", "happy", "love", "loved",
        "thanks", "wonderful",
    },
    "tired": {"bored", "exhausted", "sleep", "tired", "whatever"},
}


class UnknownMarkupError(ValueError):
    """Raised when visible text contains markup we cannot preserve safely."""


def extract_visible_directive_payloads(text: str) -> tuple[str, ...]:
    if _KIROSHI_FULL.fullmatch(text):
        return tuple(
            value
            for _, name, _, value, _ in _KIROSHI_ATTR.findall(text)
            if name in {"t", "b", "a"} and value
        )
    if _MOTHERTONGUE_FULL.fullmatch(text):
        return tuple(
            value
            for _, name, _, value, _ in _MOTHERTONGUE_ATTR.findall(text)
            if name in {"m", "b", "a"} and value
        )
    return ()


@dataclass(frozen=True)
class TransformContext:
    seed: str
    resource: str
    entry_id: str
    field: str
    surface: str = "prose"

    def digest(self, purpose: str) -> bytes:
        payload = "\x1f".join(
            (self.seed, self.resource, self.entry_id, self.field, self.surface, purpose)
        )
        return hashlib.sha256(payload.encode("utf-8")).digest()


_MOTHERTONGUE_FULL = re.compile(
    r'^<mothertongue'
    r'\s+l="(?:\\.|[^"\\])*"'
    r'\s+m="(?:\\.|[^"\\])*"'
    r'\s+b="(?:\\.|[^"\\])*"'
    r'\s+a="(?:\\.|[^"\\])*"\s*/>$'
)
_MOTHERTONGUE_ATTR = re.compile(
    r'(\s+)([lmba])=(")((?:\\.|[^"\\])*)(")'
)
_KIROSHI_FULL = re.compile(
    r'^<kiroshi'
    r'\s+l="(?:\\.|[^"\\])*"'
    r'\s+o="(?:\\.|[^"\\])*"'
    r'\s+t="(?:\\.|[^"\\])*"'
    r'\s+b="(?:\\.|[^"\\])*"'
    r'\s+a="(?:\\.|[^"\\])*"\s*/>$'
)
_KIROSHI_ATTR = re.compile(
    r'(\s+)([lotba])=(")((?:\\.|[^"\\])*)(")'
)
_RECOGNIZED_TOKEN = re.compile(
    r"<<<[^<>]*>>>"
    r"|<Rich\b[^<>]*>"
    r"|<Input\b[^<>]*>"
    r"|<Image\b[^<>]*>"
    r"|</>"
    r"|\{[^{}\r\n]+\}"
    r"|\\[nrt]"
    r"|https?://[^\s<>]+"
    r"|(?<![\w:])(?:€\$)?[+-]?\d+(?:[.,:]\d+)*(?:%|ms|s|m|h|kg|mg|GB|MB)?(?![\w])",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_UNKNOWN_ANGLE = re.compile(
    r'<[A-Za-z][A-Za-z0-9_-]*\b[^<>]{0,500}(?:=|["\'])[^<>]{0,500}>'
    r'|</[A-Za-z][^<>]*>'
)
_LITERAL_ANGLE = re.compile(r"<([^<>]*)>")
_MALFORMED_KNOWN_MARKUP = re.compile(
    r"<(?:Rich|Input|Image|mothertongue|kiroshi)\b", re.IGNORECASE
)


def extract_structural_tokens(text: str) -> tuple[str, ...]:
    """Return exact spans that ordinary prose transformation may not alter."""
    visible = text.rstrip()
    for face in sorted(SAFE_ASCII_EMOTES, key=len, reverse=True):
        suffix = f" {face}"
        if visible.endswith(suffix):
            visible = visible[: -len(suffix)]
            break
    return tuple(match.group(0) for match in _RECOGNIZED_TOKEN.finditer(visible))


def _phonetic_word(word: str) -> str:
    lowered = word.lower()
    original = lowered
    if lowered == "ok":
        lowered = "oki"
    lowered = re.sub(r"qu", "qw", lowered)
    lowered = re.sub(r"x", "ks", lowered)
    lowered = re.sub(r"ou", "ow", lowered)
    lowered = re.sub(r"ck$", "k", lowered)
    lowered = re.sub(r"(?:r|l)", "w", lowered)
    lowered = re.sub(r"n(?=[aeiou])", "ny", lowered)
    lowered = re.sub(r"ove", "uv", lowered)
    lowered = re.sub(r"th", "d", lowered)
    lowered = re.sub(r"s$", "z", lowered)
    lowered = re.sub(r"o$", "ow", lowered)
    if lowered == original and len(lowered) >= 2:
        for index, character in enumerate(lowered):
            replacement = (
                {"a": "aw", "e": "ye", "i": "wi", "o": "ow", "u": "uw"}.get(character)
                if index == 0
                else {"a": "ya", "e": "ye", "i": "wi", "o": "wo", "u": "wu"}.get(character)
            )
            if replacement:
                lowered = lowered[:index] + replacement + lowered[index + 1 :]
                break
    if lowered == original and len(lowered) >= 2 and "y" in lowered:
        index = lowered.index("y")
        lowered = lowered[:index] + "wy" + lowered[index + 1 :]

    if word.isupper():
        return lowered.upper()
    if word[:1].isupper():
        return lowered[:1].upper() + lowered[1:]
    return lowered


def _readable_phonetic_word(word: str) -> str:
    mutated = re.sub(r"w{2,}", "w", _phonetic_word(word), flags=re.IGNORECASE)
    if mutated.casefold() != word.casefold():
        return mutated
    lowered = word.lower()
    for source, replacement in (
        ("i", "y"),
        ("a", "ah"),
        ("e", "eh"),
        ("o", "oh"),
        ("u", "oo"),
    ):
        index = lowered.find(source)
        if index >= 0:
            lowered = lowered[:index] + replacement + lowered[index + 1 :]
            break
    if word.isupper():
        return lowered.upper()
    if word[:1].isupper():
        return lowered[:1].upper() + lowered[1:]
    return lowered


def _emotion_for_text(text: str) -> str:
    words = {match.group(0).casefold() for match in _WORD.finditer(text)}
    for emotion in ("distressed", "happy", "tired"):
        if words.intersection(_EMOTION_WORDS[emotion]):
            return emotion
    if "?" in text:
        return "curious"
    return "cute"


def _append_embellishment(
    text: str, context: TransformContext, *, source_text: str | None = None
) -> str:
    if context.surface == "compact":
        return text
    trailing_match = re.search(r"\s*$", text)
    trailing = trailing_match.group(0) if trailing_match else ""
    body = text[: len(text) - len(trailing)] if trailing else text
    roll = context.digest("embellishment")[0]
    emotion = _emotion_for_text(source_text if source_text is not None else text)
    faces = _FACES_BY_EMOTION[emotion]
    face = faces[context.digest(f"face:{emotion}")[0] % len(faces)]
    if len(body.strip()) >= 80:
        return f"{body} {face}{trailing}"
    if roll < 72:
        return f"{body} {face}{trailing}"
    if roll < 92:
        noises = ("nya", "meow", "nyaa", "mrow")
        noise = noises[context.digest("noise")[0] % len(noises)]
        return f"{body} — {noise}!{trailing}"
    if roll < 102 and len(body.strip()) >= 20:
        actions = (
            "*pounces on objective*",
            "*notices ur mission*",
            "*deploys tactical toe beans*",
            "*violently meows*",
        )
        action = actions[context.digest("action")[0] % len(actions)]
        return f"{body} {action}{trailing}"
    return text


def _transform_plain(
    text: str,
    context: TransformContext,
    *,
    embellish: bool = True,
    append_embellishment: bool = True,
) -> str:
    if not text or not re.search(r"[A-Za-z]", text):
        return text

    words = list(_WORD.finditer(text))
    if context.surface == "compact":
        mutate_indexes = set(range(len(words)))
        readable_mutations: dict[int, str] = {}
    else:
        readable_mutations = {
            index: _readable_phonetic_word(match.group(0))
            for index, match in enumerate(words)
        }
        eligible_indexes = [
            index
            for index, match in enumerate(words)
            if readable_mutations[index].casefold() != match.group(0).casefold()
        ]
        target_count = max(1, round(len(words) * 0.4))
        ranked = sorted(
            eligible_indexes,
            key=lambda index: context.digest(
                f"prose-word:{index}:{words[index].group(0).lower()}"
            ),
        )
        mutate_indexes = set(ranked[:target_count])
    stutter_index = next(
        (
            i
            for i, match in enumerate(words)
            if i in mutate_indexes and len(match.group(0)) >= 3
        ),
        None,
    )
    use_stutter = (
        embellish
        and context.surface != "compact"
        and context.digest("stutter")[0] < 32
    )
    pieces: list[str] = []
    cursor = 0
    for index, match in enumerate(words):
        pieces.append(text[cursor : match.start()])
        if index in mutate_indexes:
            mutated = (
                _phonetic_word(match.group(0))
                if context.surface == "compact"
                else readable_mutations[index]
            )
        else:
            mutated = match.group(0)
        if use_stutter and index == stutter_index:
            mutated = f"{mutated[0]}-{mutated}"
        pieces.append(mutated)
        cursor = match.end()
    pieces.append(text[cursor:])
    output = "".join(pieces)

    if embellish and append_embellishment:
        output = _append_embellishment(output, context, source_text=text)
    return output


def _transform_mothertongue(text: str, context: TransformContext) -> str:
    if not _MOTHERTONGUE_FULL.fullmatch(text):
        raise UnknownMarkupError("Malformed or unsupported mothertongue directive")

    def replace(match: re.Match[str]) -> str:
        space, name, quote_open, value, quote_close = match.groups()
        if name == "l" or not value:
            transformed = value
        else:
            transformed = transform_visible_text(
                value,
                dataclass_replace(context, surface="compact"),
            )
        return f"{space}{name}={quote_open}{transformed}{quote_close}"

    return _MOTHERTONGUE_ATTR.sub(replace, text)


def _transform_kiroshi(text: str, context: TransformContext) -> str:
    if not _KIROSHI_FULL.fullmatch(text):
        raise UnknownMarkupError("Malformed or unsupported kiroshi directive")

    def replace(match: re.Match[str]) -> str:
        space, name, quote_open, value, quote_close = match.groups()
        if name in {"l", "o"} or not value:
            transformed = value
        else:
            transformed = _transform_plain(
                value,
                dataclass_replace(context, surface="compact"),
                embellish=False,
            )
        return f"{space}{name}={quote_open}{transformed}{quote_close}"

    return _KIROSHI_ATTR.sub(replace, text)


def transform_visible_text(text: str, context: TransformContext) -> str:
    """Transform visible prose while preserving known structural spans exactly."""
    if text == "":
        return text
    if text.startswith("<mothertongue"):
        return _transform_mothertongue(text, context)
    if text.startswith("<kiroshi"):
        return _transform_kiroshi(text, context)

    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        marker = f"\x00MM{len(protected)}\x00"
        protected.append(match.group(0))
        return marker

    masked = _RECOGNIZED_TOKEN.sub(protect, text)

    def protect_literal_angle(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not inner or inner.startswith("/") or re.search(r"[=\"']", inner):
            return match.group(0)
        marker = f"\x00MM{len(protected)}\x00"
        protected.append(
            f"<{_transform_plain(inner, dataclass_replace(context, surface='compact'), embellish=False)}>"
        )
        return marker

    masked = _LITERAL_ANGLE.sub(protect_literal_angle, masked)
    unknown = _UNKNOWN_ANGLE.search(masked)
    if unknown:
        raise UnknownMarkupError(f"Unknown markup: {unknown.group(0)}")
    malformed_known = _MALFORMED_KNOWN_MARKUP.search(masked)
    if malformed_known:
        raise UnknownMarkupError(
            f"Malformed known markup: {malformed_known.group(0)}"
        )

    segments = re.split(r"(\x00MM\d+\x00)", masked)
    transformed_segments: list[str] = []
    stuttered = False
    has_visible_text = False
    for segment in segments:
        marker = re.fullmatch(r"\x00MM(\d+)\x00", segment)
        if marker:
            transformed_segments.append(protected[int(marker.group(1))])
            continue
        has_letters = bool(re.search(r"[A-Za-z]", segment))
        should_stutter = not stuttered and has_letters
        transformed_segments.append(
            _transform_plain(
                segment,
                context,
                embellish=should_stutter,
                append_embellishment=False,
            )
        )
        stuttered = stuttered or should_stutter
        has_visible_text = has_visible_text or has_letters

    output = "".join(transformed_segments)
    if extract_structural_tokens(output) != extract_structural_tokens(text):
        raise ValueError("protected structural token mismatch")
    if has_visible_text:
        output = _append_embellishment(output, context, source_text=text)
    return output
