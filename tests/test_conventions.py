"""Convention checks follow the CantoCaptions tables (conventions.md): mandatory forms are
flagged, context-dependent ones are only queried, and protected words are left alone."""
import pytest

from ccp import lint
from ccp.srtio import Cue


def _hits(text):
    c = Cue(pos=1, number="1", start=0, end=1, lines=[text])
    return {(h["found"], h.get("suggest"), h["severity"]) for h in lint.check_cue(c)}


@pytest.mark.parametrize("text, found, suggest", [
    ("咪喐", "喐", "郁"), ("我吿你", "吿", "告"), ("唔只係佢", "唔只", "唔止"),
    ("唔好意思，打搞晒", "打搞晒", "打攪晒"), ("唔駛驚", "唔駛", "唔使"), ("姖話", "姖", "佢"),
    ("依個人", "依個", "呢個"), ("𠵱個人", "𠵱個", "呢個"),
])
def test_mandatory_forms_are_flagged(text, found, suggest):
    assert (found, suggest, "standard") in _hits(text)


def test_context_dependent_forms_are_queries():
    assert ("抖", "唞", "query") in _hits("早抖")
    assert ("攪", "搞", "query") in _hits("你攪錯咗")


def test_protected_words_are_left_alone():
    assert not any(f == "姐係" for f, _, _ in _hits("靜香小姐係全世界"))
    assert not any(f == "攪" for f, _, _ in _hits("打攪晒"))
    assert not any(f == "抖" for f, _, _ in _hits("佢嚇到發抖"))
