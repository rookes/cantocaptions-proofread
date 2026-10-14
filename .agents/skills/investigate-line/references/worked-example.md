# Worked example: 食多都亂 → 實囉囉攣

This is the acceptance case in `tests/single-line-smoke/`. The tool outputs below are real
(abridged). Recreate the workspace with:

```
uv run ccp adhoc smoke --audio tests/single-line-smoke/single-line-smoke.mp3 \
  --text "阿媽食多都亂瞓唔着㗎" --reference "媽媽一定坐立不安睡不著的"
uv run ccp evidence smoke
```

## 1. Gather

`uv run ccp render smoke`:

```
1|阿媽食多都亂瞓唔着㗎  @0:00.0
R 媽媽一定坐立不安睡不著的
≠ft 你阿媽食多多亂瞓唔着㗎，
≠qw 你阿媽食攞攞攣，瞓唔著嘅。
! 多 0.00  都 0.00  亂 0.03  媽 0.04
```

## 2. Understand the situation

The reference says "Mum will certainly be restless and unable to sleep". The draft says
"Mum eats a lot and is all chaotic, can't sleep". 食多都亂 makes no sense, so the cue is wrong
in the middle. 瞓唔着 matches 睡不著, so the end is right.

## 3. Locate the doubtful span

The span is 食多都亂, where the meaning breaks. Corroborating evidence: weak peaks on 多都亂,
both recognisers disagree with the draft on exactly this span, and the reference has
一定坐立不安 in this position.

## 4. Generate candidates

The meaning needed is "certainly" (一定) + "restless" (坐立不安), in Cantonese.

`uv run ccp sounds-like 食多都亂 --hyp 食攞攞攣 --hyp 食多多亂`:

```
多多     do1 do1          already_in_hyp [2]   (an echo of one recogniser; meaningless here)
囉囉攣   lo1 lo1 lyun1    "坐立不安，唔自在 | adj. — anxious; restless or uneasy"
手多多 / 撈亂 / 石螺 / 搗亂 …
```

囉囉攣 means exactly 坐立不安. It ranks near the top because it is close to *all three*
hypotheses, and closest to stock Qwen's 攞攞攣 (lo2 lo2 lyun1), which has the right syllables
with tone 2 for tone 1.

For 一定, the Cantonese 實 (sat6) means "certainly". `uv run ccp dict 實` lists
"一定；必定；必然 | adv. — certainly". It sounds like the draft's 食 (sik6): same tone, and the
finals ik/at are a common confusion. Both recognisers also wrote 食, so 食 → 實 is a mishearing
the audio cannot settle, but the meaning settles it.

`uv run ccp jp 食多都亂 --vs 實囉囉攣 --all`:

```
食多都亂  sik6 do1 dou1 lyun6|lyun2
實囉囉攣  sat6 lo1 lo1 lyun1        sound_distance 0.20
```

The tones line up (6 1 1 against 6 1 1 1, with 亂 often heard as lyun1). The draft kept the
tones even where the syllables were wrong, which is the typical mishearing pattern.

## 5. Check

- `uv run ccp dict 囉囉攣`: an adjective, no register label (not slang-only or vulgar), with
  the example 「你見唔到佢，個心就囉囉攣」.
- `uv run ccp corpus 囉攣`: 0 strict-tier hits. A word can be rare in subtitles and still right.
  The dictionary entry and the meaning carry it.
- `uv run ccp score smoke --cue 1 "阿媽實囉囉攣瞓唔着㗎" "阿媽實囉攣瞓唔着㗎"`: `reliable: false`
  (median content peak 0.07). The aligner barely hears this fast line, so the deltas
  (−1.3, +6.4) are ignored. If it had been reliable, a modestly negative delta for the
  meaning-driven fix would still not count against it.
- Both recognisers hear a leading 你 (你阿媽…). On a one-cue clip there is no previous cue to
  blame, so this could be a real missing 你. It is a separate, weaker finding. Record it as a
  `missing` query, or mention it in the note.

## 6. Decide and record

Choose 阿媽實囉囉攣瞓唔着㗎. 實囉攣 is the alternative, with one syllable fewer. The audio
evidence (Qwen heard two lo-syllables) favours 囉囉攣.

```
uv run ccp flag add smoke --cue 1 --category mishearing --severity essential --confidence high \
  --proposed "阿媽實囉囉攣瞓唔着㗎" --alt "阿媽實囉攣瞓唔着㗎" \
  --evidence "reference: 一定坐立不安 = certainly restless" \
  --evidence "asr_qwen: 食攞攞攣 (sik6 lo2 lo2 lyun1), two lo-syllables" \
  --evidence "dict: 囉囉攣 lo1 lo1 lyun1 坐立不安; 實 sat6 = 一定" \
  --evidence "sounds_like: 囉囉攣 near all three hypotheses; tones of 多都亂 preserved" \
  --note "Both ASRs also hear a leading 你; not included."
```

## What the example teaches

- The recognisers did not hand over the answer, but the *independent* one (stock Qwen) heard
  the right syllables with slightly wrong tones. Its Jyutping mattered, not its characters.
- Meaning (the reference, read as meaning, not wording) proposed 實 and 囉囉攣. Sound confirmed
  囉囉攣 and was neutral on 實.
- The acoustic scorer was correctly ignored as unreliable.
