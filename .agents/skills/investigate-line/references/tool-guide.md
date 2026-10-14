# Which tool answers which question

## Decision table

| the question | first tool | then | do not |
|---|---|---|---|
| Does this line mean what the scene needs? | `ccp cue` (reference, neighbours) | your own reading of the situation | copy the reference's wording |
| Both recognisers write something else: are they right? | compare the meaning of their version and of the draft with `R` | `ccp dict` on both words | adopt a version whose meaning differs from `R` because the recognisers agree on it |
| What else could these sounds be? | `ccp sounds-like SPAN --hyp ASR1 --hyp ASR2` | `ccp jp --all`, your own knowledge | trust a candidate only because it ranks first |
| Is this a real word / what register / what measure word? | `ccp dict WORD` | `ccp corpus WORD` | assume a word exists because it looks plausible |
| What does this particle mean / which tone is it? | `ccp particle 喇` (or `ccp particle laa3`) | `cantocaptions-standards` conventions | look particles up by character in words.hk |
| Which particle usually ends a clause with this phrase? | `ccp colloc PHRASE --final --among laa` | `ccp colloc A --vs B` | treat a collocation as proof for one line |
| How does the standard write this word? | `cantocaptions-standards`; `ccp corpus` | `ccp dict` (words.hk is the authority for words not in the conventions) | follow non-strict files |
| How is this name written in this show? | `glossaries/<show>.md`, then the reference: copy its form verbatim (or a short form the speaker used) | only when neither has the name: `ccp corpus NAME --show SLUG`, `ccp sounds-like NAME --show SLUG --source corpus` | check a name the reference gives against the audio or the corpus; invent a new transliteration |
| What do the recognisers hear with more context? | `ccp listen ID --cue N` | `--pad 1.5`, `--isolate` (music/noise) | read a padded transcript as belonging only to this cue; re-listen to overrule a draft that already means what `R` means |
| Was a word said at all? / Which of two sound-different candidates fits the audio? | `ccp score ID --cue N "full text A" "full text B"` | `ccp listen` | use it on homophones, particles, or to reject a meaning-driven fix |
| Where does the speech in this cue start and end; where would a split fall? | `ccp timing ID N` / `ccp timing ID N --split "a\|b"` | `ccp listen --pad 1.5` | type timestamps by hand |
| Is the cue missing words at its edges? | `[edge]` characters in ASR lines; `ccp render --groups` | `ccp listen --pad 1.5` | move words between cues (you can only flag it) |

## When to run `ccp score`, and when not to

Scoring is a tie-breaker, not a ritual. Most fixes are settled before it would add anything.
**Do not score** when any of these holds:

- **Both recognisers already hear your fix** on the changed span (e.g. both `≠ft` and `≠qw`
  write 講起 where the draft has 講係) **and the fix means what the reference says**. That is
  independent acoustic evidence already. If the fix's meaning differs from the reference,
  scoring will not rescue it: drop it.
- **The change is spelling or convention only**: a variant (說→説), a required spelling (俾→畀),
  Standard Written Chinese where the recognisers show the Cantonese word (無→冇, 那→嗰),
  punctuation. The scorer would only abstain or measure a homophone.
- **The change is a name** taken from the reference or the glossary.
- **The change touches only sentence-final particles, or the candidates are homophones.** The
  scorer always abstains on these.
- **The meaning makes the fix unambiguous** and nothing sounds wrong (a dropped 人 in 巨入侵,
  a doubled 有).

**Do score** when:

- two or more candidates fit the meaning and differ in **sound**, and the recognisers disagree
  with each other or heard neither candidate;
- you suspect a **missing or extra word** that the recognisers do not settle;
- a fix is driven by meaning alone (no recogniser heard anything like it) and you are about to
  grade it `essential`/`high`. In that case, check that the delta is not grossly negative.

When several cues need scoring, you may send them in one call with `--batch FILE` (a JSON list
of `{"cue": N, "candidates": ["full text", ...]}`), but separate calls are fine. `score` reads the
aligner output that `ccp evidence` stored, so it takes about a second and needs no GPU. Do not
pass `--pad` unless you need a wider span: it forces a slow GPU run (20–40 s). `listen` always
uses the GPU (20–40 s), so use it only when re-hearing a cue would change your decision.

### Reading a score

- `delta` is the candidate's log-likelihood minus the draft's, in nats. A delta above **+3**
  means the audio clearly fits the candidate better. A delta below **−6** for a candidate that
  adds or drops a word usually means the audio does not support the change. Between those, the
  audio does not decide.
- A moderately negative delta never vetoes a fix that the meaning demands: the aligner mishears
  the same way the transcriber did.
- `abstain` (punctuation, particles or homophones only) means the audio cannot judge.
  `reliable: false` means the aligner barely hears the span, so ignore every delta for that cue.
- `substituted` lists characters the aligner has no token for, scored as a same-syllable
  stand-in. `unscorable` lists characters it could not score at all. Both make a score weaker.

## The witnesses and their blind spots

**Reference subtitle (`R`).** A human translation, usually Standard Chinese, sometimes English,
sometimes OCR'd (expect OCR typos). **It is the authority on what each line means.** A
correction must agree with its meaning, however confidently the recognisers hear something
else. Two exceptions: the reference line belongs to a neighbouring cue (check `prev`/`next`
and the reference `agreement` from `ccp status`), or it is a loose translation that leaves the
detail in question open. Say which in your evidence. `ccp status <id>` shows its `label`. A reference marked
*written Cantonese* (for example, a video's own manual Cantonese captions) is the exception:
there, its wording is real evidence for what was said, though it may not follow CantoCaptions
conventions. It shows *meaning*, and it is the authority for how *names* are written:
copy a name from it verbatim (or a short form or nickname the speaker used) unless the show's
glossary says otherwise. Only an English or OCR'd reference needs a second source for a
name (the glossary, `ccp corpus --show`), because it cannot show the characters or may have an
OCR typo in them. It often
paraphrases, merges or splits lines, and is timed to its own release (the tools shift it by the
best constant offset). It cannot tell you Cantonese wording, particles or sentence-final tone.

**Fine-tuned recogniser (`≠ft`, `asr_ft`).** Trained on CantoCaptions subtitles, so it writes in
CantoCaptions style and knows common Cantonese well. It shares the corpus's habits: where it
agrees with the draft, both may be wrong the same way. It sometimes drops short words.

**Stock Qwen3-ASR (`≠qw`, `asr_qwen`).** Not trained on CantoCaptions, so it is the more
independent witness. It ignores several CantoCaptions sound distinctions in its spelling: it
writes 咁 for both 噉 gam2 and 咁 gam3, 邊 for both 邊 bin1 and 便 bin6, 著 for 着, and 呀 for
吖/啊/呀. Its spelling of those is no evidence either way (the render hides those
differences). It often hears the right *syllables* but picks the wrong characters (攞攞攣 for
囉囉攣), so read its Jyutping rather than its characters. It inserts or drops particles freely.

The fine-tuned recogniser *does* follow those distinctions, so when `≠ft` differs from the draft
only in 噉/咁, 邊/便 or 着/著, that is a real, if weak, piece of evidence about the tone.

**Both recognisers agreeing against the draft** is the strongest *audio* signal you have: it
tells you how the line most likely sounds. It says nothing about what the line means, and the
two models can share a mishearing (both hear 唔使可憐 "no need to pity" for 唔抵可憐 "not worth
pitying", where the reference says 不值得可憐). Their agreement settles a fix only when the fix
also means what the reference says. One recogniser alone is weak evidence, especially stock
Qwen on particles.

**How the witnesses rank.** For *what the line means*: the reference first, then the
conversation around it. For *how it was said*, among wordings with that meaning: the
recognisers (both agreeing beats one), re-listening, then the aligner. A recogniser never
overrules the reference's meaning; the reference never dictates the Cantonese wording.

**Aligner peaks (`!`).** Per-character probability from a CTC acoustic model forced to place the
draft on the audio. Low peaks (< 0.05) mark characters that do not sound like the audio there.
This catches about half of real character errors at roughly one real error per five flagged
characters: a place to look, not a verdict. It is near-deaf on fast speech, shouting, singing
and music, and it barely hears sentence-final particles (those are never shown).

**CTC candidate scoring (`ccp score`).** The aligner's log-likelihood of each full candidate text
against the cue's audio, relative to the draft. It is good for choosing between candidates
that *sound different* and for detecting an inserted or dropped word. It cannot tell
homophones or particles apart, cannot veto a mishearing fix, and is meaningless where the audio
is unclear. See "When to run `ccp score`" and "Reading a score" above.

**Re-listening (`ccp listen`).** Both recognisers again, with wider padding (1 s by default,
clamped to the neighbouring cues), optionally after vocal isolation. More context often fixes
a recogniser's error at a cue boundary. The output covers the whole padded span, so match the
part that belongs to this cue.

**words.hk (`ccp dict`, `ccp particle`, `ccp sounds-like`).** The authority for Cantonese words,
spellings, readings and measure words. It mostly omits Standard Chinese vocabulary and proper
names. It does not use CantoCaptions' particle characters, which is why particles are looked up
by reading. `ccp jp --all` shows every reading words.hk records for a character; the first is
the most common.

**Strict corpus (`ccp corpus`, `ccp colloc`).** Only subtitle files the dataset tiers `strict`
(hand-standardized), about 110k lines. Counts show what the standard writes and which particles
habitually follow a phrase (一定…喇 far more than 一定…啦; 得㗎喇 far more than 得㗎啦).
Collocation is a tendency, not a rule: the specific line can still be the exception. A
comma ends the clause, so particles of the next clause are never counted.

## Known traps

- ASR context biasing (feeding a candidate word to the recogniser) was tested and does **not**
  confirm candidates: the recogniser sometimes recites the hint and sometimes ignores the right
  one. The tools do not offer it; do not try to emulate it.
- Whisper models hallucinate on Cantonese clips and are not used.
- A recogniser hearing an extra leading word (`[你]`) may be picking up the end of the
  previous cue. Check the neighbour before flagging a missing word.
- Standard Written Chinese in a cue (的, 這, 沒, 們 …) is usually a transcription slip, but the
  speaker may really be reading text aloud or quoting; check the scene.
