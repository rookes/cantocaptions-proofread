"""Jyutping readings, the sound search, the dictionary and the render's comparison key."""
from ccp import jyutping, sound
from ccp.render import content_key
from conftest import needs_dictionary


@needs_dictionary
def test_polyphone_readings():
    assert {"lyun6", "lyun2"} <= set(jyutping.readings("亂"))
    assert jyutping.readings("攣")[0] == "lyun1"


@needs_dictionary
def test_particle_readings_follow_cantocaptions():
    assert jyutping.readings("㗎")[0] == "gaa3"
    assert jyutping.readings("𠿪")[0] == "gaa2"
    assert jyutping.readings("噉") == ["gam2"]
    assert jyutping.readings("咁") == ["gam3"]


def test_syllable_split_and_costs():
    assert sound.split("gwaa3") == ("gw", "aa", "3")
    assert sound.split("m4") == ("", "m", "4")
    assert sound.split("ngo5") == ("ng", "o", "5")
    assert sound.syllable_cost("lo1", "lo1") == 0
    # n/l is a cheap confusion, tone 3/6 cheaper than tone 1/4
    assert sound.syllable_cost("nei5", "lei5") < sound.syllable_cost("bei5", "lei5")
    assert sound.syllable_cost("si3", "si6") < sound.syllable_cost("si1", "si4")


@needs_dictionary
def test_smoke_case_sounds_like():
    """Acceptance: the draft 食多都亂 plus both recognisers' hypotheses find 囉囉攣."""
    top = [m.term for m in sound.search("食多都亂", ["食攞攞攣", "食多多亂"], n=5)]
    assert "囉囉攣" in top


@needs_dictionary
def test_particle_lookup_by_reading():
    from ccp import dictionary
    gaa2 = dictionary.particle_senses("gaa2")
    assert gaa2["cantocaptions_form"] == "𠿪"
    assert any(s["words_hk_spelling"] == "㗎" for s in gaa2["senses"])
    assert dictionary.describe("囉囉攣")["senses"][0]["pos"] == "形容詞"


def test_content_key_folds_per_model():
    # particles and punctuation never count
    assert content_key("走喇，") == content_key("走啦。")
    # pure variants fold for every model
    assert content_key("你俾我", "ft") == content_key("你畀我", "ft")
    # 噉 gam2 / 咁 gam3 are different words: a difference for the fine-tuned model...
    assert content_key("係咪噉嘅意思", "ft") != content_key("係咪咁嘅意思", "ft")
    # ...but stock Qwen writes 咁 for both, so its 咁 is no evidence
    assert content_key("係咪噉嘅意思", "qw") == content_key("係咪咁嘅意思", "qw")
    # an audible difference stays a difference
    assert content_key("幾乎無咩皮膚", "qw") != content_key("幾乎冇咩皮膚", "qw")


@needs_dictionary
def test_dict_contains_text_and_jyutping():
    from ccp import dictionary
    assert "係噉意" in dictionary.terms_containing("係噉")
    assert "囉囉攣" in dictionary.terms_containing("lo1 lyun1")
