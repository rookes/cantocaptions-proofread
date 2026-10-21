# Reading the review stream

## `ccp render`

`uv run ccp render <id> --from N --to M` prints a window of cues; with `--save` it writes the
stream (the whole episode unless `--from`/`--to`) to `work/<id>/review.txt` instead, as a
snapshot that later records do not change. Each cue is a line `N|text  @m:ss.s` (so `^37\|`
finds cue 37), followed by whatever evidence exists for it:

- `37|阿媽食多都亂瞓唔着㗎  @3:21.5`: cue 37 (its position in the file), its text (`⏎` = line break), start time
- `{an8}` after the text: an overlapping background line shown at the top of the screen
- `⟨markup: <font color=…>⟩` after the text: the cue holds markup the text above hides (colours on song lyrics, for instance); `ccp cue` shows where. Edits keep a colour that wraps a whole line.
- `R …`: the reference line that overlaps this cue most: what the line means
- `≠ft …`: the fine-tuned recogniser heard different *content*
- `≠qw …`: stock Qwen3-ASR heard different content
- `[你]` inside an ASR line: heard in the padding just outside the cue: a word the cue may be missing, or the neighbour's
- `! hard to hear: 多 都`: characters the aligner barely matches to the audio where the draft puts them (shown only beside a recogniser that differs)
- `L kind found→suggestion`: a lint hit (`L invisible U+200B …`: an invisible character; propose the cue's text as shown to remove it)
- `T …`: realign doubts this cue's timing
- `F#3 fix/mishearing/open → …`: a record you already made
- `--` / `==`: a pause of 1–3 s / 3 s or more before the next cue
- `>> speaker change`: (with `--diarize`) the speaker changes

No `≠` line means the recognisers say the same words as the draft. Differences in sentence-final
particles, punctuation and a recogniser's spelling variants (說 for 説, 喐 for 郁) are hidden
(the draft's own spelling is checked by the `L` lines), and for stock Qwen
also 噉/咁, 邊/便 and 着/著, which it does not distinguish. `--groups` adds the raw ASR text of
each group of cues (`G12 ft …`), for when a per-cue ASR line looks cut oddly at a boundary.

## `ccp cue`

One block per cue: the draft with its Jyutping (and other readings), `R`, the neighbouring cues
(`--context N` for more), then each recogniser marked `=` (same words) or `≠` (with its
Jyutping), a `check` line when they differ, characters that are hard to hear, lint and records.
A `raw` line under the draft shows the cue as written when it holds markup or invisible
characters (spelled out as `⟨U+200B⟩`).
Ask for all your suspects in one call. `--json` gives the full structure.

## Glossary format (`glossaries/<show_slug>.md`)

The show slug is in the record (`show_slug`). Keep one table; the convention checks and `ccp clean --lint`
read the `Avoid` column.

```markdown
# Attack on Titan (2013) glossary

| Correct | Jyutping | Avoid | Notes / source |
|---|---|---|---|
| 艾倫 | ngaai6 leon4 | 艾連、愛倫 | main character; reference + 41 strict cues |
| 西甘希娜 | sai1 gam1 hei1 naa4 | | district; S1E01 episode title |
```

Add a name only with a source you can cite (the reference, a strict episode of the same show,
or a clear majority in the file). Full names and nicknames are separate rows. A glossary entry
overrides the reference: when a show's Cantonese dub renames a character, record the dub's name
with the reference's form under `Avoid` and a note saying so.
