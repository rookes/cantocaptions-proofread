import pytest

from ccp import corpus, lint
from ccp.groups import listen_span, make_groups
from ccp.srtio import Cue
from conftest import needs_corpus


def test_comma_ends_the_clause_for_collocation():
    t = "一定佢未死喇，梗係唔會啦"
    assert corpus._final_run(t, t.index("一定") + 2, 8) == "喇"
    t = "一定係佢啦"
    assert corpus._final_run(t, 2, 8) == "啦"
    # a wrapped line is the same clause; a new speaker line is not
    assert corpus._final_run("一定\n係佢啦", 2, 8) == "啦"
    assert corpus._final_run("一定\n-係佢啦", 2, 8) == "∅"


@needs_corpus
def test_corpus_is_strict_only():
    eps = corpus.episodes()
    lines = corpus.lines("strict")
    assert lines
    assert {eps[ln.episode]["tier"] for ln in lines} == {"strict"}


@needs_corpus
def test_collocation_yiding_prefers_laa3():
    r = corpus.colloc("一定", "final", among="laa")
    counts = {c["form"]: c["count"] for c in r["counts"]}
    assert counts.get("喇", 0) > 2 * counts.get("啦", 0)


def _cue(pos, start, end, text="字"):
    return Cue(pos=pos, number=str(pos), start=start, end=end, lines=[text])


def test_lint_hits():
    rows = lint.check_cue(_cue(1, 0, 1, "你俾我啦。"))
    kinds = {(r["kind"], r["found"]) for r in rows}
    assert ("variant", "俾") in kinds and ("punctuation", "。") in kinds
    rows = lint.check_cue(_cue(2, 0, 1, "佢係的士司機……"))
    assert not any(r["kind"] == "standard_written_chinese" for r in rows)   # 的士 is an exception
    assert any(r["found"] == "……" for r in rows)
    assert any(r["kind"] == "compound_particle" for r in lint.check_cue(_cue(3, 0, 1, "係噉架嘛")))
    # 架 counts as a particle only sentence-finally
    assert not any(r["kind"] == "particle_variant" for r in lint.check_cue(_cue(4, 0, 1, "架車好靚")))
    assert any(r["kind"] == "particle_variant" for r in lint.check_cue(_cue(5, 0, 1, "好靚架")))


def test_lint_respects_readme_over_dataset_heuristic():
    # README requires 牀; the dataset's heuristic rule (牀->床) is skipped
    assert any(r["found"] == "床" and r["suggest"] == "牀" for r in lint.check_cue(_cue(1, 0, 1, "上床瞓覺")))
    assert not any(r["found"] == "牀" for r in lint.check_cue(_cue(2, 0, 1, "上牀瞓覺")))


def test_groups_merge_pad_and_never_overlap():
    cues = [_cue(1, 1.0, 2.0), _cue(2, 2.3, 3.0), _cue(3, 5.0, 6.0), _cue(4, 6.2, 7.0)]
    an8 = Cue(pos=5, number="5", start=6.5, end=7.5, lines=["{\\an8}背景"])
    groups = make_groups(cues + [an8], gap=0.8, pad=0.5)
    main = [g for g in groups if 5 not in g.cues]
    assert [g.cues for g in main] == [[1, 2], [3, 4]]
    assert any(g.cues == [5] for g in groups)
    a, b = main
    assert a.start == 0.5 and b.end == 7.5
    assert a.end <= b.start          # padding stops at the gap midpoint
    assert a.end == 3.5 and b.start == 4.5


def test_groups_split_long_runs_at_largest_gap():
    cues = [_cue(i + 1, i * 3.0, i * 3.0 + 2.6) for i in range(10)]   # 0.4 s gaps, 29.6 s run
    cues[4] = _cue(5, 12.0, 14.0)                                       # a 1.0 s gap after cue 5
    groups = make_groups(cues, gap=1.2, max_len=20.0)
    assert all(g.cue_end - g.cue_start <= 20.0 for g in groups)
    assert any(g.cues[-1] == 5 for g in groups)       # the cut falls at the largest gap


def test_listen_span_clamps_to_neighbours():
    cues = [_cue(1, 0.0, 1.0), _cue(2, 1.4, 2.0), _cue(3, 5.0, 6.0)]
    s, e = listen_span(cues, 2, pad=1.0)
    assert (s, e) == pytest.approx((1.2, 3.0))
    s, e = listen_span(cues, 2, pad=1.0, clamp=False)
    assert (s, e) == pytest.approx((0.4, 3.0))


@needs_corpus
def test_corpus_search_context_stays_in_episode():
    r = corpus.search("一定", examples=3, context=2)
    for block in r["examples"]:
        header, *rows = block
        assert sum(1 for row in rows if row.startswith(">")) == 1
        assert 2 <= len(rows) <= 5
