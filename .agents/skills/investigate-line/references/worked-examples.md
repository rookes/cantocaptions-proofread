# Worked examples

Four decisions: a fix, a keep, and two particle decisions. The tool output is abridged.

## 1. A fix: 食多都亂 → 實囉囉攣

From a single test clip (`tests/single-line-smoke/`).

```
1|阿媽食多都亂瞓唔着㗎
R 媽媽一定坐立不安睡不著的
≠ft 你阿媽食多多亂瞓唔着㗎，
≠qw 你阿媽食攞攞攣，瞓唔著嘅。
! 多 0.00  都 0.00  亂 0.03  媽 0.04
```

**Meaning.** `R` says "Mum will certainly be restless and unable to sleep". The draft says
"Mum eats a lot and is all chaotic, can't sleep": it does not mean what `R` means, so words
were misheard. 瞓唔着 matches 睡不著, so the doubtful span is 食多都亂.

**Candidates.** The meaning needed is "certainly" + "restless". `ccp sounds-like 食多都亂 --hyp
食攞攞攣 --hyp 食多多亂` ranks 囉囉攣 (lo1 lo1 lyun1, `ccp dict`: 坐立不安, "restless") near the
top: it is close to all three hypotheses, and closest to Qwen's 攞攞攣 (lo2 lo2 lyun1: the right
syllables, one tone off). For 一定, Cantonese 實 sat6 "certainly" sounds like the draft's 食
sik6 (same tone; ik/at is a common confusion). The tones line up: 6 1 1 1
against 6 1 1 1. The draft kept the tones even where the syllables were wrong, which is the
typical mishearing.

**Audio.** `ccp score` gives no verdict: the aligner barely hears this fast line. It is not needed anyway: meaning proposes the fix and sound confirms
it.

```
uv run ccp flag add smoke --cue 1 --category mishearing --grade fix \
  --proposed "阿媽實囉囉攣瞓唔着㗎" --alt "阿媽實囉攣瞓唔着㗎" \
  --reason "食多都亂 makes no sense; the reference 一定坐立不安 is 實 'certainly' + 囉囉攣 'restless' (sat6 lo1 lo1 lyun1), keeping the draft's tones" \
  --evidence "reference: 一定坐立不安 = 實囉囉攣" \
  --evidence "asr_qwen: 食攞攞攣 (lo2 lo2 lyun1), the right syllables" \
  --evidence "dict: 囉囉攣 坐立不安; 實 = 一定"
```

## 2. A keep against both recognisers: 唔抵可憐

Attack on Titan S1E06, cue 251.

`ccp cue`:

```
draft  你哋呢種人唔抵可憐啊
       nei5 dei2 ni1 zung2 jan4 m4 dai2 ho2 lin4 aa3
R      你們這種人不值得可憐
next   搞成噉樣，都係抵死㗎
ft ≠  你哋呢種人唔使可憐啊，   nei5 dei2 ni1 zung2 jan4 m4 sai2 ho2 lin4 aa3
qw ≠  你哋呢種人唔使可憐啊！   nei5 dei2 ni1 zung2 jan4 m4 sai2 ho2 lin4 aa3
```

**Meaning.** 唔抵可憐 (m4 dai2) is "not worth pitying": exactly `R` 不值得可憐. Both
recognisers hear 唔使可憐 (m4 sai2), "no need to pity", which is a different meaning. The next
cue (搞成噉樣，都係抵死㗎, "they deserve it") confirms the scene.

**Decision.** The draft means what `R` means and the recognisers' version does not, so the
recognisers share a mishearing. Keep. Re-listening, even with vocal isolation, only repeats
the same mishearing, and no audio result can overrule the meaning, so none is run.

```
uv run ccp flag keep <id> --cue 251 \
  --reason "唔抵可憐 m4 dai2 'not worth pitying' is exactly the reference 不值得可憐; both recognisers' 唔使 m4 sai2 'no need to' does not fit the reference or the next cue (抵死), so they misheard"
```

## 3. A particle query raised by meaning: 嘅呢？ → 㗎啦

Attack on Titan S1E06, cue 131.

`ccp cue`:

```
draft  人死咗就唔識講嘢嘅呢？
R      人死了就不會說話
ft =  人死咗就唔識講嘢㗎啦，
qw =  人死咗就唔識講嘢㗎啦。
```

The recognisers' lines are marked `=` because they say the same words: a difference in
particles alone is never marked `≠`, and is no evidence by itself. What raises the question is
**meaning**: the draft ends in 嘅呢？, making the line a question, while `R` states a fact
("dead men don't talk") and the scene is a taunt. A statement needs a statement particle; once
meaning has raised that, the recognisers' 㗎啦 is a reasonable candidate. Particles are judged
by ear and standard, so this is a query: the reviewer chooses.

```
uv run ccp flag add <id> --cue 131 --category particle --grade query \
  --alt "人死咗就唔識講嘢㗎啦" --alt "人死咗就唔識講嘢㗎喇" \
  --reason "嘅呢？ makes this a question, but the reference 人死了就不會說話 states it as a taunt; a statement particle fits, and both recognisers hear 㗎啦" \
  --evidence "reference: 人死了就不會說話 (a statement)"
```

## 4. A particle fix: 一定係佢啦 → 一定係佢喇

An illustration of the rule (AGENTS.md principle 4), not from a real episode.

`ccp particles scan <id> --from 88 --to 88`:

```
? 88[0] 啦 laa1  ·  一定係佢啦
    means: suggestion, urging, acceptance of a shared understanding, or obviousness …
    R: 一定是他做的！
    model: the fine-tuned recogniser clearly prefers 喇 over 啦
    recorded (confirmed): 一定 → 喇: 一定…喇 states a certain fact; 一定…啦 says the listener should already know it …
    strict: 一定 → 喇 67% of 159 (25 shows; 喇 107, 啦 35, 嘞 14, 囖 3)
    recognisers wrote (weak): ft 喇 · qw 啊
    ? the fine-tuned recogniser clearly prefers 喇 over 啦
    ? recorded collocation (confirmed): 一定 usually takes 喇
```

**Meaning.** The previous cues show the speaker working out who did it, and `R` ends with
"！": it is a discovery, announced as a certain fact. That is 喇 laa3 (`particle-usage.md`,
喇 laa3, Usage 4: 一定係佢喇 "it's certainly him"). 啦 laa1 would mean "obviously, as you
should know", which nothing in the scene sets up.

**Signals.** The fine-tuned recogniser clearly prefers 喇, and 一定… takes 喇 in most strict
subtitles. Both back the meaning, so this is a fix. (Had the scene been a sigh of "well, who
else would it be", 啦 would stand, whatever the signals: meaning first.)

```
uv run ccp flag add <id> --cue 88 --category particle --grade fix --proposed "一定係佢喇"   --reason "The speaker announces a discovery as a certain fact (R 一定是他做的！), which is 喇 laa3; 啦 laa1 would say the listener should already know it"   --evidence "guide: 喇 laa3, Usage 4: a certain fact (一定係佢喇)"   --evidence "particle_model: the fine-tuned recogniser clearly prefers 喇 here"   --evidence "colloc: 一定… takes 喇 in most strict subtitles"
```

## What the examples teach

- Meaning comes first and comes from `R`. Sound chooses among wordings with that meaning.
- Two recognisers agreeing is strong evidence of how a line *sounds*, never of what it means.
- Particles are raised and decided by meaning; the particles the recognisers write are no
  evidence. A particle change is a fix only when the fine-tuned recogniser's comparison or a
  collocation clearly backs the meaning; otherwise the reviewer settles it.
