# What each tool can and cannot tell you

## Which tool for which question

- What must this line mean? Use `R` and the neighbouring cues in `ccp cue`. Do not copy `R`'s wording.
- What else could these sounds be? Use `ccp sounds-like SPAN --hyp ASR1 --hyp ASR2` (readings in `ccp cue`), your own knowledge. Do not trust a candidate only because it ranks first.
- Is this a real word; what register? Use `ccp dict WORD`, then `ccp corpus WORD`. Do not assume a word exists because it looks plausible.
- What does this particle mean; which tone is it? Use `ccp dict 喇`, `cantocaptions-standards`. Do not look particles up by character in words.hk.
- Which particle usually ends a clause with this phrase? Use `ccp corpus PHRASE --final --among laa`, `ccp corpus A --vs B`. Do not treat a tendency as proof for one line.
- How does the standard write this word? Use `cantocaptions-standards`, then `ccp dict`, then `ccp corpus`. Do not follow files outside the strict tier.
- How is this name written in this show? Use AGENTS.md principle 2. Do not invent a new transliteration.
- What do the recognisers hear with more context? Use `ccp listen ID --cue N` (`--pad 1.5`, `--isolate` for music). Do not read a padded transcript as belonging only to this cue.
- Which of two candidates that sound different fits the audio? Was a word said at all? Use `ccp score ID --cue N "full text A" "full text B"`. Do not score homophones or particles.
- Is the cue missing a word at its edge? Use `[edge]` characters in ASR lines, `ccp render --groups`, `ccp listen --pad 1.5`. Do not move words between cues (flag it instead).

## When to use audio

Audio (`listen`, `score`) answers **how** a line was said, among wordings that all fit the
meaning. It never decides **what** was meant. So:

- **Use it** when two candidates both fit the meaning and differ in sound; when a word may be
  missing or extra and the recognisers disagree; or before grading `fix` a correction that
  no recogniser heard anything like (check that the score is not strongly against it).
- **Skip it** when both recognisers already hear a fix that means what `R` says; when the
  change is spelling, convention, punctuation or a name; when the candidates are homophones
  or differ only in particles (the scorer abstains); when the meaning alone makes the fix
  certain (a dropped 人 in 巨入侵); and when the draft already means what `R` means (keep).

`score` reads the aligner output that `ccp evidence` stored, so it takes about a second. Several
cues at once: `--batch FILE` (a JSON list of `{"cue": N, "candidates": ["full text", ...]}`).
`--pad`, an unusual character, or a workspace without stored output forces a GPU run
(20–40 s, `scored_on: gpu`). `listen` always uses the GPU.

### Reading a score

- `delta` is the candidate's log-likelihood minus the draft's, in nats. Above **+3**: the audio
  clearly fits the candidate better. Below **−6** for a candidate that adds or drops a word:
  the audio does not support the change. In between, the audio does not decide.
- A moderately negative delta never vetoes a fix the meaning demands: the aligner mishears
  the same way the transcriber did.
- `abstain` (punctuation, particles or homophones only): the audio cannot judge.
  `reliable: false`: the aligner barely hears the span; ignore every delta for that cue.
- `substituted` / `unscorable` list characters the aligner has no token for. Both weaken the
  score.

## The witnesses

**Reference subtitle (`R`).** A human translation of the line: usually Standard Chinese,
sometimes English, sometimes OCR'd (expect OCR typos). It is the authority on what the line
means and on how names are written (AGENTS.md principles 1 and 2). It never shows Cantonese
wording, particles or tone, and it often paraphrases, merges or splits lines. It is timed to
its own release and shifted by one constant offset, so with low `agreement` (`ccp status`) an
`R` line can belong to the neighbouring cue: check `prev` / `next`. A reference whose `label`
is *written Cantonese* (a video's own Cantonese captions) is a transcript: there its wording
is evidence too, though not its particles or conventions.

**Fine-tuned recogniser (`≠ft`, `asr_ft`).** Trained on CantoCaptions subtitles, so it writes
CantoCaptions style and keeps its sound distinctions (噉 gam2 / 咁 gam3, 邊 / 便, 着 / 著): a
`≠ft` line differing only in those is weak evidence about the tone. It shares the corpus's
habits, so where it agrees with the draft both may be wrong the same way. It sometimes drops
short words. It is not run on drafts it wrote itself (AI-generated and ASR drafts).

**Stock Qwen3-ASR (`≠qw`, `asr_qwen`).** The more independent witness. It writes 咁, 邊, 著
and 呀 whatever was said, so its spelling of those is no evidence (the render hides those
differences). It often hears the right syllables but picks the wrong characters (攞攞攣 for
囉囉攣): read its Jyutping, not its characters.

**Both recognisers agreeing against the draft** is the strongest *audio* signal: it says how
the line most likely sounds, not what it means. They share mishearings, so their agreement
settles a fix only when the fix also means what `R` says. One recogniser alone is weak.
Neither is evidence about particles.

**Aligner peaks (`!`, `weak`).** How well each draft character matches the audio where the
aligner placed it. Low peaks (< 0.05) catch about half of real character errors, at about one
real error per five flagged characters: a place to look, not a verdict. It is near-deaf on
fast speech, shouting, singing and music, and barely hears particles (never shown).

**Re-listening (`ccp listen`).** Both recognisers again with wider padding (1 s by default),
optionally after vocal isolation. It often fixes a recogniser's error at a cue boundary. The
output covers the whole padded span: match the part that belongs to this cue.

**words.hk (`ccp dict`, `ccp sounds-like`).** The authority for Cantonese
words, spellings, readings and measure words. It mostly omits Standard Chinese vocabulary and
proper names, and writes some particles with other characters (so particles are matched by
reading). `ccp cue` lists every reading it records for the draft's characters; the first is the
most common.

**Strict corpus (`ccp corpus`).** About 110k hand-standardized subtitle lines.
Counts show what the standard writes and which particles habitually follow a phrase
(一定…喇 far more than 一定…啦). A tendency, not a rule. A comma ends the clause, so the next
clause's particles are never counted.

## Known traps

- Feeding a candidate to a recogniser as context does not confirm it (it recites or ignores
  the hint). The tools do not offer it; do not emulate it.
- Whisper models hallucinate on Cantonese and are not used.
- A recogniser's extra leading word (`[你]`) may be the end of the previous cue.
- Standard Written Chinese in a cue (的, 這, 沒, 們) is usually a slip, unless the speaker is
  reading text aloud or quoting.
