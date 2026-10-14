# Classifying and grading flags

## Category: what kind of problem

| category | the cue… | typical evidence |
|---|---|---|
| `mishearing` | has words that were not said: sound-alikes of what was said | the reference's meaning (required), then both ASRs, sounds-like, dictionary |
| `standard` | was heard right but is written against the conventions (variant, required spelling, pronoun) | lint, cantocaptions-standards |
| `particle` | ends in the wrong sentence-final particle for what was said, or writes a particle with the wrong character for its reading | collocation, particle meaning, listen |
| `punctuation` | has punctuation that breaks the style guide or changes the reading (missing `？`, `。`, double `…`) | style guide, lint |
| `name` | spells a person, place or term inconsistently or differently from the reference/glossary | the glossary, else the reference (authoritative, copied verbatim); corpus `--show` only when neither has it |
| `missing` | lacks a word that was clearly said | both ASRs agree on it; `[edge]` characters; CTC score |
| `extra` | contains a word that was not said (often a repeated or merged word) | both ASRs lack it; CTC score |
| `segmentation` | should be two cues (two sentences across a pause, two speakers) or is split badly | `ccp timing --split` (onset gap), gap markers, ASR edge characters; proposal attached with `--timing` |
| `timing` | starts or ends well off the speech, is too short, or overlaps a neighbour | `T` lines from realign, lint `short_duration`/`overlap`, `ccp timing` (retime); proposal attached with `--timing` |
| `other` | anything else worth a human look | |

## Severity: how much it matters

| severity | use when | must have `proposed`? |
|---|---|---|
| `essential` | the meaning is wrong (a mishearing that changes what is said), a name is wrong, or a mandatory convention is broken, **and** you are confident of the fix | yes |
| `suggested` | the fix is likely right but the evidence is not conclusive, or the problem is minor (a missing `？`, an optional convention) | usually |
| `query` | something is off but you cannot determine the fix, or the evidence conflicts | no (give alternatives if you have them) |

## Confidence: how sure the proposed text is

- `high`: meaning and sound both support it and no evidence contradicts it. Typically: the
  reference's meaning matches the fix, it is a sound-alike of the draft, at least one recogniser
  heard it (or something tone-for-tone close), and the word exists (dictionary or strict corpus).

A fix whose meaning differs from the reference line is never `high` and never `essential`,
whatever the recognisers heard. Usually it is no fix at all: the recognisers share a
mishearing. `ccp flag add` asks for a `reference:` evidence line on every mishearing, missing,
extra or other fix where the cue has a reference line: state there how the fix's meaning
matches it (or why that reference line does not apply).
- `medium`: meaning and sound support it, but one piece of evidence is missing or weak (e.g.
  no recogniser heard it; the reference is English; the aligner is unreliable here).
- `low`: a plausible guess. Use `query` severity instead unless the user wants guesses.

`ccp apply` without a decisions file applies only `essential` + `high` flags, and never
particle flags. Grade accordingly: do not inflate a grade to get a fix applied.
