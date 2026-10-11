"""Cleaning text from people and models, and comparing names.

CONTROL matches characters that are never kept: control characters, zero width characters, the
bidirectional controls (which can make text read differently from how it is stored) and the
byte order mark. The class is built from code points, so no invisible character sits in the
source.

Names are compared folded: NFKC, case folded, accents removed, split into words with \\w+, so
"Dána Whitlock" and "DANA WHITLOCK" both match "Dana Whitlock", and Arabic or Chinese names
work too. A word that mixes alphabets ("Dana" with a Cyrillic "a") is refused rather than
compared, since it is almost always a lookalike.
"""
from __future__ import annotations

import re
import unicodedata

_INVISIBLE = [*range(0x200B, 0x2010),   # zero width space, joiners, left to right and right to left marks
              *range(0x202A, 0x202F),   # bidi embeddings and overrides
              *range(0x2060, 0x206A),   # word joiner, invisible operators, bidi isolates
              0xFEFF]                   # byte order mark
_CONTROL_POINTS = [*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0x7F, *_INVISIBLE]
CONTROL = re.compile("[" + "".join(re.escape(chr(c)) for c in _CONTROL_POINTS) + "]")
SURROGATES = re.compile("[" + chr(0xD800) + "-" + chr(0xDFFF) + "]")
_FAMILIES = {"HIRAGANA": "CJK", "KATAKANA": "CJK", "CJK": "CJK", "IDEOGRAPHIC": "CJK"}


def strip_control(text: str) -> str:
    return SURROGATES.sub("", CONTROL.sub("", text))


def fold(text: str) -> str:
    """'Dána' -> 'dana': NFKC, case folded, accents removed."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def words(text: str) -> list[str]:
    return re.findall(r"\w+", fold(text))


def _script(ch: str) -> str:
    name = unicodedata.name(ch, "")
    first = name.split(" ")[0] if name else ""
    return _FAMILIES.get(first, first)


def mixed_script(text: str) -> str | None:
    """The first word whose letters come from more than one alphabet, if any."""
    for word in re.findall(r"\w+", unicodedata.normalize("NFKC", text)):
        if len({_script(ch) for ch in word if ch.isalpha()}) > 1:
            return word
    return None
