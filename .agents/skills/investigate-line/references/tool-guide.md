# What each tool can and cannot tell you

## Which tool for which question

- What must this line mean? Use `R` and the neighbouring cues in `ccp cue`. Do not copy `R`'s wording.
- What else could these sounds be? Use `ccp sounds-like SPAN --hyp ASR1 --hyp ASR2` (readings in `ccp cue`), your own knowledge. Do not trust a candidate only because it ranks first.
- Is this a real word; what register? Use `ccp dict WORD`, then `ccp corpus WORD`. Do not assume a word exists because it looks plausible.
- What does this particle mean; which tone is it? Use `ccp particles explain 喇` (the standards' usage notes, words.hk senses and examples), `cantocaptions-standards`. Do not look particles up by character in words.hk.
- Which particle usually ends a clause with this phrase? Use `ccp particles colloc PHRASE --among laa` (strict subtitles, words.hk examples, recorded collocations), `ccp particles colloc --top 啦 --vs 喇`. Do not treat a tendency as proof for one line.
- Does the audio favour one particle over another? Use the `model:` line of `ccp particles scan` (or `ccp particles model ID --cue N`). Do not read a lean as proof, nor use it on a draft the fine-tuned recogniser wrote.
- How does the standard write this word? Use `cantocaptions-standards`, then `ccp dict`, then `ccp corpus`. Do not follow files outside the strict tier.
- How is this name written in this show? Use AGENTS.md principle 2. Do not invent a new transliteration.
- What do the recognisers hear with more context? Use `ccp listen ID --cue N` (`--pad 1.5`, `--isolate` for music). Do not read a padded transcript as belonging only to this cue.
- Which of two candidates that sound different fits the audio? Was a word said at all? Use `ccp score ID --cue N "full text A" "full text B"`. Do not read a verdict as the meaning.
- Is the cue missing a word at its edge? Use `[edge]` characters in ASR lines, `ccp render --groups`, `ccp listen --pad 1.5`. Do not move words between cues with a text fix: re-cut them with `ccp segment` (or flag it).
- Is a whole line missing where the reference has one (`+R#N`)? Use `ccp listen ID --missing N`, then write the line yourself. Do not take any single hearing as the line, and do not let the hinted hearing (the reference given to the recognisers) count as confirmation.

## When to use audio

Audio (`listen`, `score`) answers **how** a line was said, among wordings that all fit the
meaning. It never decides **what** was meant. (On a machine without cantocaptions-ai there is
no audio at all; `ccp status` shows `tools.audio_evidence: false`.) So:

- **Use it** when two candidates both fit the meaning and differ in sound; when a word may be
  missing or extra and the recognisers disagree; or before grading `fix` a correction that
  no recogniser heard anything like (check that the verdict is not `against`).
- **Skip it** when both recognisers already hear a fix that means what `R` says; when the
  change is spelling, convention, punctuation or a name; when the candidates are homophones
  or differ only in particles (the scorer abstains); when the meaning alone makes the fix
  certain (a dropped 人 in 巨入侵); and when the draft already means what `R` means (keep).

For `score`, `--pad` (or `"pad"` in the file) widens the span within the stored audio of the
cue's group; the result says when it had to stop at the group's edge.

### Reading a score

Each candidate gets a verdict against the draft, and the same in plain words: `favours` (fits
the audio better, or much better, than the draft), `against` (fits the audio worse), `undecided`
(the audio cannot tell them apart), or `abstains` (punctuation, particles or homophones only:
the audio cannot judge). A cue the audio barely matches at all gets no verdict. Characters that
"cannot be checked" or were "checked as" another character weaken a verdict. `undecided`, and
even `against` by a little, never veto a fix the meaning demands: the aligner mishears the same
way the transcriber did. Quote the plain words in your records, never a number.

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

**The fine-tuned recogniser's particle comparison (`ccp particles`, `particle_model`).** Not
its transcript: for each clause-final particle it is asked how likely the draft's particle is,
against each alternative, given the audio and the rest of the line. It hears the tone and knows
the usage, so a *clear* preference is strong evidence, and agrees with the particle the
standard writers chose far more often than not; a *lean* is weak. It can still prefer a
particle the scene rules out, so meaning decides first. On a draft it wrote itself it only
repeats its own choice: not independent there.

**Stock Qwen3-ASR (`≠qw`, `asr_qwen`).** The more independent witness. It writes 咁, 邊, 著
and 呀 whatever was said, so its spelling of those is no evidence (the render hides those
differences). It often hears the right syllables but picks the wrong characters (攞攞攣 for
囉囉攣): read its Jyutping, not its characters.

**Both recognisers agreeing against the draft** is the strongest *audio* signal: it says how
the line most likely sounds, not what it means. They share mishearings, so their agreement
settles a fix only when the fix also means what `R` says. One recogniser alone is weak.
The particles they write in their transcripts are no evidence (the comparison above is).

**Hard to hear (`! hard to hear`).** Draft characters the aligner barely matches to the audio
where it placed them. They catch about half of real character errors, at about one real error
per five characters shown: a place to look, not a verdict. It is near-deaf on
fast speech, shouting, singing and music, and barely hears particles (never shown).

**Hearing a missing line (`ccp listen --missing N`).** Four hearings of a span no cue covers:
close, close with the voices isolated, wider (into the neighbours), and with the reference as a
hint. Measured on 105 lines machine drafts lacked: the best single hearing is right a little
under half the time, a line the agent writes from all of them about 6 times in 10; when both recognisers'
close hearings contain that line it is right 86 times in 100; when neither does, about 3 times in 10.

**Re-listening (`ccp listen`).** Both recognisers again with wider padding (1 s by default),
optionally after vocal isolation. It often fixes a recogniser's error at a cue boundary. The
output covers the whole padded span: match the part that belongs to this cue.

**words.hk (`ccp dict`, `ccp sounds-like`).** The authority for Cantonese
words, spellings, readings and measure words. It mostly omits Standard Chinese vocabulary and
proper names, and writes some particles with other characters (so particles are matched by
reading). `ccp cue` lists every reading it records for the draft's characters; the first is the
most common.

**Strict corpus (`ccp corpus`).** About 110k hand-standardized subtitle lines, on machines
that have the CantoCaptions library and the dataset's tiers; elsewhere `ccp corpus` answers
`unavailable` and there is no corpus evidence.
Counts show what the standard writes and which particles habitually follow a phrase
(一定…喇 far more than 一定…啦). A tendency, not a rule. A comma ends the clause, so the next
clause's particles are never counted.

## Known traps

- Feeding a candidate to a recogniser as context does not confirm it (it recites or ignores
  the hint). The one place the tools use a hint is a missing line (`listen --missing`), where
  the reference helps the recognisers find words in a span no cue covers; even there it only
  suggests words, and the grade rests on the close hearings without it.
- Whisper models hallucinate on Cantonese and are not used.
- A recogniser's extra leading word (`[你]`) may be the end of the previous cue.
- Standard Written Chinese in a cue (的, 這, 沒, 們) is usually a slip, unless the speaker is
  reading text aloud or quoting.
