---
name: investigate-line
description: Work out what a suspect Cantonese subtitle line really says and propose the most likely correction, using the line's audio (two speech recognisers, re-listening, CTC candidate scoring), the reference subtitle, Jyutping sound-alike search over the words.hk dictionary, and usage evidence from the standardized CantoCaptions corpus. Use for any single doubtful cue, a mishearing, a name, a particle choice, or when the user asks what a line actually says.
---

# Investigate one suspect line

A subtitle line is wrong in one of a few ways: words were misheard (sound-alikes of what was
said), it breaks a convention, a particle or name is off, or words are missing or extra. Your
job is to find what was actually said and how CantoCaptions writes it, using evidence, and to
say how sure you are. You cannot hear the audio yourself; the tools give you several imperfect
witnesses. Combine them; never let a single one decide.

`references/tool-guide.md` has the decision table (which tool answers which question, and
each tool's known blind spots). `references/sound-alikes.md` lists how Cantonese is misheard.
`references/worked-example.md` walks through a complete investigation. Read the tool guide
before your first investigation in a session.

## Steps

1. **Gather.** `uv run ccp cue <id> <N>`. Read the cue, its neighbours, the reference line,
   both ASR hypotheses with their Jyutping, the per-character peaks, and lint hits. When you
   have several suspects, fetch them together: `uv run ccp cue <id> 9 11 24 40`.
2. **Understand the situation.** Who is speaking, to whom, about what? What does the reference
   say they mean? What do the neighbouring cues establish (names, topic, tone)?
3. **Locate the doubtful span.** Pin down the smallest span of characters that is probably
   wrong: where the meaning breaks, where the recognisers disagree, where peaks are weak.
4. **Generate candidates.** Ask: what Cantonese words sound like the doubtful span *and* mean
   what the situation needs?
   - Romanize the span and every hypothesis: `uv run ccp jp <text> --all` (all readings).
   - Search by sound across all hypotheses at once:
     `uv run ccp sounds-like <span> --hyp <ASR span> --hyp <other ASR span>`. Add
     `--source both` (or `--show <slug>`) to include names and set phrases from the strict
     corpus. Candidates that score well against *several* hypotheses are the strongest.
     `already_in_hyp` marks a candidate a recogniser literally wrote, which is an echo rather
     than independent support.
   - Use your own knowledge of Cantonese too. The search only knows words.hk and the corpus.
5. **Check candidates.**
   - Meaning and register: `uv run ccp dict <word>` (POS, labels such as [俚語], measure words,
     examples). For a sentence-final particle use `uv run ccp particle <particle or jyutping>`:
     words.hk spells some particles differently from CantoCaptions, so it is matched by reading.
   - Usage in standardized subtitles: `uv run ccp corpus "<regex>"` and
     `uv run ccp colloc <phrase> --final --among laa` (which particle follows it) or `--vs`
     to compare forms (`uv run ccp colloc 得㗎喇 --vs 得㗎啦`).
   - **If the reference already decides between the readings, stop here.** When the draft
     means what the reference means and the recognisers' version does not (唔抵可憐 vs
     唔使可憐, R 不值得可憐), the draft stands. Do not run `listen` or `score` to "check":
     re-listening only repeats the same shared mishearing, and no audio result can overrule
     the reference's meaning. Audio is for choosing among wordings that all fit the meaning.
   - Audio, **only if the evidence so far does not settle it**: `uv run ccp listen <id> --cue N`
     re-runs both recognisers with more context (`--pad 1.5` for more, `--isolate` to remove
     music first). `uv run ccp score <id> --cue N "<full candidate text>" ...` compares
     full-cue candidates acoustically. The tool guide's "When to run `ccp score`" lists when
     scoring adds nothing. Skip it then.
   - Many cues need no check at all. If both recognisers hear the fix and it means what the
     reference says, or it is a convention, name or obvious typo fix, go straight to step 6.
6. **Decide.** First, meaning: the candidate must mean what the reference line means (and
   fit the conversation). Then sound: among candidates with that meaning, choose the one the
   audio supports (tones especially). Then the conventions. A candidate the recognisers agree
   on but whose meaning differs from the reference is out, and if the draft already means
   what the reference means, keep the draft. If nothing fits clearly, record a query with the
   alternatives instead of guessing.
7. **Record.** `uv run ccp flag add ...` with category, severity, confidence, the full proposed
   cue text, and one evidence line per witness that mattered (see the proofread-subtitles
   skill's `references/flag-taxonomy.md` for grading). If the line turned out to be right,
   record nothing.

## Principles

- **A mishearing is a sound-alike.** The misheard text usually keeps the syllable count and
  most tones and differs in initials or finals (see `references/sound-alikes.md`). A proposed
  fix that does not sound like the draft needs strong independent support, such as both
  recognisers hearing it, and it must still mean what the reference means.
- **The reference decides the meaning; the audio decides the wording.** A correction must
  mean what the reference line means. The recognisers and the aligner tell you how the line
  was said: which words, which sound-alike, which expression. They cannot overrule the
  meaning, because both recognisers can mishear a line the same way. Example: the draft has
  你哋呢種人唔抵可憐啊 (m4 dai2, "not worth pitying"), the reference has 不值得可憐, and both
  recognisers, even after vocal isolation, hear 唔使可憐 (m4 sai2, "no need to pity"). The
  draft is right: it means what the reference means, and the shared hearing is a mishearing.
- **Meaning proposes, sound confirms.** Recognisers and the aligner mishear the same way the
  original transcriber did, so they rarely hand you the answer. Use meaning (reference,
  context) to propose candidates and sound to choose between them.
- **The reference is the authority on meaning, never on wording.** It is Standard Chinese or English.
  The Cantonese line will use different words for the same meaning (一定 → 實, 坐立不安 →
  囉囉攣, 沒有 → 冇).
- **Names are the exception: take them from the reference.** A name the reference writes is
  settled. Copy it verbatim (or a short form or nickname the speaker used) and do not check
  it with the audio, `sounds-like` or the corpus. Only the show's glossary overrides it.
- **Prefer real words.** A candidate that exists in words.hk or appears in strict-tier
  subtitles beats an invented string.
- **Intended speech is kept.** If the speaker really said something unusual, the line stays.
  Do not "correct" slang, dialect or code-switched English into standard words.
- **Particles are hard to hear.** No tool hears particles reliably. Change a particle only on
  strong evidence (a convention error, an unmistakable meaning, consistent collocation and
  context), and grade it `query` unless it is a convention error.
