"""Where a Cantonese line may be cut without cutting a word: a port of cantocaptions-ai's
`languages/yue/words.py`, which every cue cutter there asks before it cuts (this light
environment cannot import cantocaptions-ai).

pycantonese's segmentation decides, with its dictionary as a check on the one thing it gets
wrong. Its boundaries are trusted (表現 / 有啲, though 現有 is also a word). A token of up
to three characters is one word, colloquial ones included (早啲, 好啦). A longer token is not
trusted whole, because the segmenter glues what it does not know into one blob (演奏一首):
inside one, a cut is inside a word only where a dictionary word of 2-4 characters spans it.
A run of code-switched English or digits is one word.
"""
from __future__ import annotations

import re
from functools import lru_cache

_LATIN = "A-Za-z0-9À-ÖØ-öø-ɏḀ-ỿ"
LATIN_WORD = re.compile(rf"[{_LATIN}]+(?:['’\-.][{_LATIN}]+)*")
_CJK_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f]+")
_MAX_WORD = 4
_MAX_TRUSTED_TOKEN = 3


@lru_cache(maxsize=1)
def _dictionary() -> frozenset[str]:
    from pycantonese.corpus import hkcancor
    from pycantonese.data.rime_cantonese import CHARS_TO_JYUTPING
    words = set(CHARS_TO_JYUTPING)
    for utterance in hkcancor().words(by_utterance=True):
        words.update(utterance)
    return frozenset(w for w in words if 2 <= len(w) <= _MAX_WORD)


@lru_cache(maxsize=4096)
def _token_spans(run: str) -> tuple[tuple[int, int], ...]:
    import pycantonese
    tokens = pycantonese.segment(run)
    if "".join(tokens) != run:
        return ()
    spans, at = [], 0
    for token in tokens:
        spans.append((at, at + len(token)))
        at += len(token)
    return tuple(spans)


def _inside_chinese_word(run: str, at: int) -> bool:
    for start, end in _token_spans(run):
        if not start < at < end:
            continue
        if end - start <= _MAX_TRUSTED_TOKEN:
            return True
        words = _dictionary()
        return any(run[lo:hi] in words
                   for lo in range(max(start, at - _MAX_WORD + 1), at)
                   for hi in range(at + 1, min(end, lo + _MAX_WORD) + 1))
    return False


def inside_word(text: str, at: int) -> bool:
    """Whether cutting *text* before ``text[at]`` would split a word."""
    if not 0 < at < len(text):
        return False
    for match in LATIN_WORD.finditer(text):
        if match.start() < at < match.end():
            return True
    for match in _CJK_RUN.finditer(text):
        if match.start() < at < match.end():
            return _inside_chinese_word(match.group(), at - match.start())
    return False


def word_across(before: str, after: str) -> str | None:
    """The word a cut between *before* and *after* (two neighbouring cues) splits, or None.
    Only the few characters on each side are segmented, as the cut sees them. For a hint to
    the proofreader the word must be one a dictionary knows (pycantonese's or words.hk): the
    segmenter also glues the end of one lyric to the start of the next (不會老|夢境 as 老夢境)."""
    a, b = before[-6:], after[:6]
    joined = a + b
    if not inside_word(joined, len(a)):
        return None
    for match in list(LATIN_WORD.finditer(joined)) + list(_CJK_RUN.finditer(joined)):
        if match.start() < len(a) < match.end():
            run = match.group()
            if LATIN_WORD.fullmatch(run):
                return run
            at = len(a) - match.start()
            for s, e in _token_spans(run):
                if s < at < e and _known(run[s:e]):
                    return run[s:e]
            return _known_across(run, at)
    return None


def _known(word: str) -> bool:
    if word in _dictionary():
        return True
    try:
        from .dictionary import has_term
        return has_term(word)
    except Exception:          # no words.hk on this machine: pycantonese's words only
        return False


def _known_across(run: str, at: int) -> str | None:
    """A known word of 2-4 characters in *run* that spans position *at*, longest first."""
    for size in range(_MAX_WORD, 1, -1):
        for lo in range(max(0, at - size + 1), at):
            w = run[lo:lo + size]
            if len(w) == size and _known(w):
                return w
    return None
