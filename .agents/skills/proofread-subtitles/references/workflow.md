# Proofreading workflow: details

## The review stream (`ccp render`)

`uv run ccp render <id> --from N --to M` prints one window of cues. Each cue is a line
`N|text  @m:ss.s`, followed by whatever evidence exists for it:

| line | meaning |
|---|---|
| `37\|阿媽食多都亂瞓唔着㗎  @3:21.5` | cue 37 (position in the file), its text (`⏎` = line break), start time |
| `{an8}` after the text | an overlapping background line placed at the top of the screen |
| `R …` | the reference subtitle line that overlaps this cue most (Standard Chinese or English) |
| `≠ft …` | the fine-tuned CantoCaptions recogniser heard different *content* here |
| `≠qw …` | stock Qwen3-ASR heard different content here |
| `[你]` inside an ASR line | characters heard in the padding just before/after the cue: a word the cue may be missing, or one belonging to the neighbouring cue |
| `! 多 0.00  都 0.00` | weak characters: the aligner hears little of these characters where the draft puts them (peak probability; final particles excluded) |
| `L kind found→suggestion` | a lint hit (convention or consistency) |
| `F#3 essential/mishearing/open → …` | a flag you already recorded |
| `--` / `==` | a pause of 1–3 s / 3 s or more before the next cue |
| `>> speaker change` | (with `--diarize`) the speaker changes from the previous cue |

`--groups` also prints, before each group of cues, the raw ASR text for the whole group the
recognisers heard in one pass (`G12 ft …`). Use it when a per-cue ASR line looks cut
oddly: the split between cues is computed by forced alignment and can be off by a character
at a cue boundary.

Absence of a `≠` line means the recognisers agree with the draft's content, apart from
clause-final particles, punctuation and spelling variants. For stock Qwen, 噉/咁, 邊/便 and
着/著 are also ignored, because it does not distinguish them. The fine-tuned model does, so a
`≠ft` line can be about 噉 vs 咁 alone. That is a mild reason for confidence, not proof: the fine-tuned recogniser was
trained on CantoCaptions text and can share its habits.

## One cue in depth (`ccp cue`)

`uv run ccp cue <id> N [N ...]` prints one compact block per cue:

```
── cue 127  @8:34.3–8:36.5
draft  好多人都係噉意就算數
       hou2 do1 jan4 dou1 hai6 gam2 ji3 zau6 syun3 sou3
       other readings: 意 ji3/ji2/ji5/ji1; …
prev   …              (neighbouring cues; --context N for more)
next   …
R      很多人都馬馬虎虎就算了
ft ≠  好多人都係噉以就算數，   hou2 do1 jan4 dou1 hai6 gam2 ji5 …
qw ≠  好多人都係咁以就算數。   …
weak   意 0.00
lint / flag lines if any
```

`=` means the recogniser's content matches the draft, and `≠` that it differs (with its Jyutping).
`weak` lists characters with a peak below 0.3. Ask for all your suspects in one call.
`--json` gives the full structure if you ever need it.

## Recording findings (`ccp flag`)

One flag per cue. `proposed` is the **complete** new text of the cue, not a fragment.

```
uv run ccp flag add <id> --cue 37 --category mishearing --severity essential --confidence high \
  --proposed "阿媽實囉囉攣瞓唔着㗎" \
  --evidence "reference: 媽媽一定坐立不安 — 'certainly restless'" \
  --evidence "asr_qwen: 食攞攞攣 (sik6 lo2 lo2 lyun1)" \
  --evidence "dict: 囉囉攣 lo1 lo1 lyun1 = 坐立不安" \
  --evidence "sounds_like: 囉囉攣 ranks 1st for 食多都亂 across draft+ASR" \
  --note "實 (sat6) for 食 (sik6): 一定 in the reference; tones of 多都亂 match 囉囉攣"
```

- Evidence entries are `source: detail`. Sources: `reference`, `asr_ft`, `asr_qwen`, `listen`,
  `sounds_like`, `dict`, `corpus`, `ctc`, `lint`, `glossary`, `context`.
- For a `mishearing`, `missing`, `extra` or `other` fix on a cue with a reference line, a
  `reference:` entry is required: say how the proposed text's meaning matches `R`. `ccp flag
  add` refuses the flag without one. If you cannot write that line honestly, the fix is wrong.
- A query (something is wrong but you cannot tell what) has no `--proposed`.
- Alternatives you could not rule out go in `--alt "full text"` (repeatable).
- To add many flags at once, write a JSON list of objects with the same keys (`cue`,
  `category`, `severity`, `confidence`, `proposed`, `evidence`, `note`, `alternatives`,
  `related`) and run `uv run ccp flag add <id> --json-file flags.json`.
- To change a flag: `uv run ccp flag update <id> <flag_id> --severity suggested ...`
  (evidence given here is appended). List them with `uv run ccp flag list <id>`.

## Glossary format (`glossaries/<show_slug>.md`)

The show slug is in the episode record (`show_slug`). Keep one table; `ccp lint` reads the
`Avoid` column and flags those spellings in later episodes.

```markdown
# Attack on Titan (2013) glossary

| Correct | Jyutping | Avoid | Notes / source |
|---|---|---|---|
| 艾倫 | ngaai6 leon4 | 艾連、愛倫 | main character; reference + 41 strict cues |
| 西甘希娜 | sai1 gam1 hei1 naa4 | | district; S1E01 episode title |
```

Add a name only with a source you can cite (the reference, a strict episode of the same show,
or a consistent majority in this file). Full names and nicknames are separate rows.

A glossary entry overrides the reference. Most rows simply record the reference's form for
episodes that have no reference. When a show's Cantonese version names a character differently
from its Chinese reference subtitles (the dub renames them), record the dub's name with the
reference's form under `Avoid` and a note saying so. That keeps later episodes from copying
the reference's name.

## When evidence is missing

- No media (`media_exists: false`): you can still lint and review text against the
  reference and conventions, but say in the summary that audio was not checked.
- No reference: mishearing detection relies on context and the recognisers. Be more
  conservative: propose a fix only when both the sound and the meaning make it clear.
- `ccp evidence` failed: report the error. Do not invent ASR output.
