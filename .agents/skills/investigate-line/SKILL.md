---
name: investigate-line
description: Decide what a suspect Cantonese subtitle line really says and record the decision (fix, suggest, query or keep) with its reason. Uses the reference subtitle for meaning, the line's audio (two speech recognisers, re-listening, scoring candidates against the audio) for wording, Jyutping sound-alike search over the words.hk dictionary, and usage in the standardized CantoCaptions corpus. Use for every suspect line in a proofread, or when the user asks what a line actually says.
---

# Decide a suspect line

This is the one procedure for deciding a suspect cue, in every kind of proofread. It applies
the principles in AGENTS.md ("How to decide a line"). Before your first decision in a
session, read `references/worked-examples.md` (a fix, a keep against both recognisers, and
a particle query). Open `references/tool-guide.md` only when you are about to use audio
(`listen`, `score`) or a lookup you have not used yet, and `references/sound-alikes.md` when
you are hunting for what a misheard span really was.

**Most suspects are settled by reading `R` against the draft.** Audio and lookups are for the
few where the meaning is wrong and the right words are not obvious.

## Commands

- `uv run ccp cue <id> 9 11 24`: gather: draft with Jyutping, `R`, neighbours, ASR lines, weak characters, lint
- `uv run ccp sounds-like <span> --hyp <ASR span> --hyp <ASR span> [--source both]`: candidates that sound like the span
- `uv run ccp dict <word>` · `uv run ccp dict <text> --contains`: meaning, register, whether a word exists; a particle's usage (looked up by its reading)
- `uv run ccp corpus "<regex>" [--show <slug>] [-C 2]` · `--final [--among laa]`: usage in standardized subtitles; which particles end a phrase
- `uv run ccp listen <id> --cue N [--pad 1.5] [--isolate]` · `--json-file <file>` (a list of `{"cue": N}`): re-hear cues with more context (GPU)
- `uv run ccp score <id> --cue N "<full text A>" "<full text B>"` · `--json-file <file>` (a list of `{"cue": N, "candidates": ["<full text>", ...]}`): which candidates the audio favours over the draft (CPU)
- `uv run ccp flag add <id> ...` · `uv run ccp flag keep <id> ...`: record the decision (below)

## The procedure

1. **Gather.** `ccp cue` for your suspects in one call (up to 20; it refuses more, because a
   whole window is what `ccp render` is for).
2. **Meaning.** From `R` and the neighbouring cues, what must the line mean? Does the draft
   mean that?
   - **Yes.** The line is right unless a convention or a name is wrong (**fix**, no audio
     needed). Otherwise **keep**, without any audio check:
     - A recogniser's version means something else: it misheard. No audio result overrules
       the meaning.
     - A recogniser's version says the same thing in other words. Which way the difference
       goes decides it:
       - the draft has a word the recognisers leave out (走嚟呢度 heard as 嚟呢度), or they
         swap in a near-synonym (等如 heard as 等於): **keep**. Recognisers often drop small
         words and swap synonyms, and a favourable `score` does not change that;
       - **both** recognisers hear a word the draft lacks, and it fits (點會噉樣 heard as
         點解會噉樣, 太荒謬 heard as 太過荒謬): the transcriber missed it. **Fix**, category
         `missing`.
       A draft wording that is ungrammatical or makes no sense is also worth a fix.
   - **No.** Words were misheard. Find what was said:
     1. Pin down the smallest span where the meaning breaks.
     2. Find candidates that sound like the span **and** mean what `R` needs: `ccp
        sounds-like` with every ASR span as `--hyp` (the readings are in `ccp cue`), your own Cantonese.
        Tones usually survive a mishearing.
     3. Check each: `ccp dict` (a real word? register?) and `ccp corpus` (used in
        standardized subtitles?). If `ccp corpus` answers `unavailable`, `ccp dict` and your
        own Cantonese decide, and no record cites corpus evidence.
     4. Choose by meaning first, then by sound. If two candidates both fit the meaning and
        differ in sound, or a word may be missing or extra, `score` or `listen`. With no audio
        tools on this machine, that is a `query` with both as alternatives (proofread-subtitles,
        "Without audio").
     5. Nothing fits clearly: **query**, with the candidates as alternatives.
   - **`R` cannot decide.** No reference, an English one, a loose translation, or an `R` line
     that belongs to a neighbouring cue (low `agreement` in `ccp status`): judge the meaning
     from the conversation, and fix only when sound and context both make it clear.
3. **Particles** (AGENTS.md principle 4). Ask only whether the draft's particle gives the
   line the force `R` and the scene need. If not, record a **query** whose alternatives are
   the particles that would (the recognisers' particles may suggest which). A particle written
   with the wrong character for its reading (`cantocaptions-standards`) is a **fix**.
   Otherwise there is nothing to record.
4. **Record** exactly one entry for the cue (below) **as soon as you have decided it**, then
   move on: the record holds the decision, so do not reopen it later. A suspect you checked
   and found right is recorded too, as a keep.

## Grades

- `fix`: the meaning (`R`, context) and the sound both support it and nothing contradicts it; a convention or name error. Then: applied when the user asked for edits.
- `suggest`: likely right, but one piece is missing or weak (no recogniser heard anything like it; `R` is English; the aligner is unreliable). Then: the reviewer decides.
- `query`: something is wrong but no fix is confident, or the evidence conflicts. Then: candidates go in `--alt`.
- `keep`: you checked a suspect and the line is right. Then: nothing changes.

A fix whose meaning differs from `R` is never `fix` or `suggest`. Do not inflate a grade to get
a fix applied.

## Recording

```
uv run ccp flag add <id> --cue 37 --category mishearing --grade fix \
  --proposed "阿媽實囉囉攣瞓唔着㗎" \
  --reason "食多都亂 makes no sense; the reference 一定坐立不安 is 實 'certainly' + 囉囉攣 'restless' (sat6 lo1 lo1 lyun1), which keeps the draft's tones" \
  --evidence "reference: 一定坐立不安 = 實囉囉攣" --evidence "asr_qwen: 食攞攞攣 (lo2 lo2 lyun1)"

uv run ccp flag keep <id> --cue 251 \
  --reason "唔抵可憐 m4 dai2 'not worth pitying' is exactly the reference 不值得可憐; both recognisers' 唔使 'no need to' does not fit the reference, so they misheard"
```

- **`--reason` is required**: one or two sentences saying what is wrong (or why the line is
  right) and why the proposal is right, naming the sounds (Jyutping) and the meaning. The
  report shows it to the reviewer as "Reason:".
- **Write the reason and the evidence for the reviewer**: a Cantonese speaker who knows the
  subtitles, not the tools. Use plain words and no tool numbers or jargon: not "CTC", "nats",
  "+5.6", "peak 0.00", "delta", "score", "sound_distance", "ft"/"qw" or "R". Say instead "the
  audio fits 點解會 much better than the draft", "會 is hard to hear", "both speech recognisers
  heard 點解會", "the reference (為什麼團長會知道) asks why", "點會 and 點解會 sound almost the
  same". `ccp score` and `ccp sounds-like` print these phrases for you to quote.
- `--proposed` is the cue's **complete** new text (`⏎` for a line break), for fix and suggest
  only. A query has no `--proposed`; give candidates with `--alt "<full text>"` (repeatable).
- `--category`: `mishearing` (sound-alikes of what was said), `missing` / `extra` (a word
  said but not written, or written but not said), `name`, `standard` (heard right, written
  against the conventions), `particle`, `punctuation`, `segmentation` / `timing` (see the
  proofread skill), `other`.
- `--evidence "source: detail"` for each witness that mattered; sources: `reference`,
  `asr_ft`, `asr_qwen`, `listen`, `ctc` (the audio check: `score`), `sounds_like`, `dict`,
  `corpus`, `lint`, `glossary`, `context`. The detail is plain words too
  (`ctc: fits the audio much better than the draft`). A `mishearing`, `missing`, `extra` or `other` correction on a cue
  that has an `R` line must include a `reference:` entry saying how its meaning matches `R`;
  the tool refuses it otherwise. If you cannot write that line honestly, the fix is wrong.
- Many records at once: a JSON list of objects with the same keys (`cue`, `category`,
  `grade`, `proposed`, `reason`, `evidence`, `alternatives`) and
  `uv run ccp flag add <id> --json-file <file>`. Valid entries are recorded; the error lists
  the rest to fix and resubmit.
- To change a record: `uv run ccp flag update <id> <flag_id> --grade suggest ...`. List them:
  `uv run ccp flag list <id>`.
