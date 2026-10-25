"""The words.hk CSV export: its columns, its examples (with their Jyutping) and its quirks."""
from pathlib import Path

from ccp import dictionary

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wordshk_sample.csv"


def _senses():
    return dictionary._read_csv(FIXTURE)


def test_verbatim_duplicate_rows_are_read_once():
    assert [s.term for s in _senses()].count("囉") == 1


def test_columns_become_fields():
    s = next(s for s in _senses() if s.term == "仆街")
    assert s.pos == "名詞"
    assert s.labels == ["粗俗", "俚語"]
    assert (s.zh, s.en) == ("衰人", "jerk")
    assert s.measure == "個／條"
    assert s.synonyms == ["冚家鏟", "契弟"]
    assert not s.reviewed


def test_examples_carry_their_jyutping():
    lo1 = next(s for s in _senses() if s.term == "囉")
    first, second = lo1.examples
    assert (first.yue, first.jyutping, first.en) == ("係囉！", "hai6 lo1", "Of course!")   # link mark # dropped
    assert second.jyutping.endswith("tai2 m4 dou2")
    assert (lo1.example, lo1.example_en) == ("係囉！", "Of course!")


def test_example_without_jyutping_and_tagged_english():
    ex = next(s for s in _senses() if s.term == "仆街").examples[0]
    assert (ex.yue, ex.jyutping, ex.en) == ("佢真係正仆街。", "", "He is a real jerk.")


def test_every_yue_line_is_an_example_and_zho_is_skipped():
    exs = next(s for s in _senses() if s.term == "應付").examples
    assert [e.yue for e in exs] == ["你好好哋同我應付下。", "你小心啲同我應付下。"]
    assert all(e.en == "Handle it carefully for me." for e in exs)


def test_altterm_and_reading_pointer_rows():
    award = next(s for s in _senses() if s.term == "頒獎")
    assert award.altterm == "頒奬"
    pointer = next(s for s in _senses() if s.term == "黑白")
    assert (pointer.jyutping, pointer.other_reading, pointer.pos, pointer.zh) == ("hak1 baak6", "haak1 baak6", "", "")


def test_show_example():
    e = dictionary.Example("係囉！", "hai6 lo1", "Of course!")
    assert dictionary.show_example(e) == "係囉！ [hai6 lo1] (Of course!)"
