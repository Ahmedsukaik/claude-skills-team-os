"""Cleaning text from people and models, and comparing names.

CONTROL matches characters that are never kept: control characters, every format character
(Unicode category Cf: zero width characters, the bidirectional controls that can make text read
differently from how it is stored, the soft hyphen, the Arabic letter mark, tag characters, the
byte order mark), and the other default ignorable characters that draw nothing: the combining
grapheme joiner, the Hangul fillers, the blank Braille pattern and the variation selectors. The
class is built from code points, so no invisible character sits in the source.

Names are compared folded: NFKC, case folded, accents removed, and only their letters and digits,
joined, so "Dána Whitlock", "DANA WHITLOCK" and "Da-na Whitlock" all match "Dana Whitlock", and
Arabic or Chinese names work too. A word that mixes alphabets ("Dana" with a Cyrillic "a") is
refused rather than compared, since it is almost always a lookalike.
"""
from __future__ import annotations

import re
import unicodedata

_FORMAT = [c for plane in (range(0x0000, 0x20000), range(0xE0000, 0xE1000)) for c in plane
           if unicodedata.category(chr(c)) == "Cf"]          # format characters: invisible by design
_IGNORABLE = [0x034F,                                         # combining grapheme joiner
              0x115F, 0x1160, 0x3164, 0xFFA0,                 # Hangul fillers
              0x17B4, 0x17B5,                                 # Khmer inherent vowels
              *range(0x180B, 0x1810),                         # Mongolian variation selectors and vowel separator
              0x2800,                                         # blank Braille pattern
              *range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)]   # variation selectors
_CONTROL_POINTS = sorted({*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), *range(0x7F, 0xA0), *_FORMAT, *_IGNORABLE})


def _ranges(points: list[int]) -> str:
    out, start, prev = [], points[0], points[0]
    for c in points[1:] + [-1]:
        if c != prev + 1:
            out.append(re.escape(chr(start)) + ("-" + re.escape(chr(prev)) if prev > start else ""))
            start = c
        prev = c
    return "".join(out)


CONTROL = re.compile("[" + _ranges(_CONTROL_POINTS) + "]")
SURROGATES = re.compile("[" + chr(0xD800) + "-" + chr(0xDFFF) + "]")
LETTER_OR_DIGIT = re.compile(r"[^\W_]")
_FAMILIES = {"HIRAGANA": "CJK", "KATAKANA": "CJK", "CJK": "CJK", "IDEOGRAPHIC": "CJK"}


def strip_control(text: str) -> str:
    return SURROGATES.sub("", CONTROL.sub("", text))


def fold(text: str) -> str:
    """'Dána' -> 'dana': NFKC, case folded, accents removed."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", fold(strip_control(text)))


def name_key(text: str) -> str:
    """A name as one run of letters and digits: separators cannot split it ("Da-na" is "dana")."""
    return "".join(words(text))


def has_letter_or_digit(text: str) -> bool:
    return bool(LETTER_OR_DIGIT.search(text))


def _script(ch: str) -> str:
    name = unicodedata.name(ch, "")
    first = name.split(" ")[0] if name else ""
    return _FAMILIES.get(first, first)


def mixed_script(text: str) -> str | None:
    """The first word whose letters come from more than one alphabet, if any."""
    for word in re.findall(r"\w+", unicodedata.normalize("NFKC", strip_control(text))):
        if len({_script(ch) for ch in word if ch.isalpha()}) > 1:
            return word
    return None
