---
name: proofread-subtitles
description: Proofread a CantoCaptions written-Cantonese subtitle file (an episode or movie) against its audio, a reference subtitle and the CantoCaptions conventions, then report the findings (HTML report with audio clips) and/or apply the corrections. Use when the user asks to proofread, check, review or correct an episode or .srt file.
---

# Proofread a subtitle file

You read every cue of one file alongside the evidence the tools put next to it, pick out the
suspects, decide each one with the `investigate-line` procedure, and hand back a short,
trustworthy list of corrections. `references/reading.md` explains the review stream and the
glossary format; `references/report-and-apply.md` covers the output step.

If the subtitles are AI-generated or ASR output and not cleaned yet, use `clean-draft` instead
(AGENTS.md, "Which skill").

## Commands

- `uv run ccp locate <show> S1E03` · `--srt <path>` · `--select <id> --media <path>`: find the file and media; create the workspace
- `uv run ccp status <id>`: what the workspace holds
- `uv run ccp reference <id>` · `--stream N` · `--file <path>` · `--ocr` (ask first): the reference subtitle
- `uv run ccp evidence <id> [--diarize]`: the recognisers and the aligner over every cue (GPU, minutes)
- `uv run ccp render <id> --save` · `--from N --to M`: the review stream, saved to a file to read and search · a fresh window printed
- `uv run ccp cue <id> 9 11 24`: suspects in depth
- `uv run ccp flag add/keep <id> ...`: record decisions (`investigate-line` → Recording)
- `uv run ccp report <id>` · `uv run ccp apply <id> ...`: output (`references/report-and-apply.md`)

## Procedure

1. **Locate.** `uv run ccp locate <the user's words>`. A unique match creates the workspace
   and prints the record (subtitle, media, audio track, tier, notes). Several candidates: show
   them and ask. Never search for files yourself.
   - `media_candidates` (`needs_confirmation: true`): media found by name only, in the user's
     media folders. Show the best one and ask whether it is the right episode (AGENTS.md rule
     7). For the subtitle to proofread, offer the `subtitles_near` files that are written
     Cantonese, or ask for the path; the Chinese or English ones beside it are references.
     Then `uv run ccp locate --srt <subtitle> --media <media> --id <suggested_id>`.
   - No media at all: ask the user for the file (`ccp locate ... --media PATH`), or proofread
     without audio.
2. **Settle the output** (AGENTS.md, "When the request is unclear") and where it goes
   (`references/report-and-apply.md` → "Where the result goes"): run `ccp copy-draft` now if
   the edits must go into a new file.
3. **Reference.** `uv run ccp reference <id>`. If it answers `needs_decision`, tell the user
   what is available and ask which to use. Note `agreement`: below 0.6 some `R` lines sit
   next to the wrong cue, so check `prev` / `next` before relying on one.
4. **Evidence.** `uv run ccp evidence <id>`. Convention checks come with `ccp render` (`L` lines).
   If `ccp status` shows `tools.audio_evidence: false` (no cantocaptions-ai on this machine),
   skip this step and see "Without audio" below.
5. **Glossary.** Read `glossaries/<show_slug>.md` if it exists; add names you settle while
   reading (format in `references/reading.md`).
6. **Review pass.** Save the review stream (`ccp render <id> --save`) and read it with your
   file-reading tool, from the first cue to the last, a few hundred lines at a time. Search it
   whenever another cue matters (how a name is written elsewhere, an earlier mention). Note
   only the suspects, with a word on why: a cue that fits `R` and has no `≠`, `!`, `L` or `T`
   line needs no comment. Do not investigate yet: later cues often explain earlier ones.
7. **Decide.** `ccp cue` for the suspects (up to 20 per call), then for each, in this order:
   - **Settled already:** a convention, name or obvious typo fix; or both recognisers hear
     a fix that means what `R` means. Record it.
   - **Right after all:** the draft means what `R` means and is natural Cantonese, whatever
     the recognisers say (`investigate-line` step 2, "Yes"). Record a keep, without any audio
     check or lookup.
   - **Needs work:** the meaning is wrong and the right words are not obvious. Follow
     `investigate-line`.

   Every suspect ends with exactly one record (fix, suggest, query or keep), each with its
   reason. Record each decision as you make it (several at a time with `--json-file` is
   fine) and do not revisit it: the record holds it.
8. **Output.** Build the report and/or apply, as the user asked
   (`references/report-and-apply.md`). Summarise: records by grade, the most important
   corrections in one line each, and the report path.

## What makes a cue suspect

Each is a reason to *look*, not proof:
- its meaning does not fit `R` or the conversation;
- an ASR line (`≠ft`, `≠qw`) differs in content (particle, punctuation and spelling-variant
  differences are hidden on purpose); both recognisers differing together is stronger;
- a run of weak characters (`!`);
- a lint line (`L`);
- a name written differently from the glossary, `R` or elsewhere in the file;
- Standard Written Chinese rather than spoken Cantonese.

Not reasons by themselves: a recogniser's sentence-final particle differing from the draft's
(AGENTS.md principle 4), and a recogniser writing another spelling of the same word
(喐 for 郁, 說 for 説). A recogniser's spelling is no evidence, so the tools hide those
differences. The draft's own spelling is a separate matter: it must use the convention's
form (郁, 説), and an `L` line flags it when it does not.

## Boundaries

- Do not flag style preferences the conventions do not require, "improve" wording, or
  normalise a speaker's grammar. Only clear misspeaks the style guide says to drop are fair
  game.
- **Proportion:** in a `strict` file, almost every cue is right. If your suspect list grows
  past a small fraction of the cues, you are probably flagging preferences or the recognisers'
  habits: re-read AGENTS.md "How to decide a line". Lower tiers can have many convention
  flags (lint shows them).
- No media (`media_exists: false`) or no audio tools: see "Without audio". `ccp evidence`
  failed: report the error; never invent ASR output.

## Without audio

With no media, or no cantocaptions-ai (`tools.audio_evidence: false` in `ccp status`), the
review stream has `R` and `L` lines but no `≠` or `!` lines, and `listen`, `score` and
`timing` do not run. Proofread from the text:
- Suspects come from the meaning against `R` and the conversation, lint, names, and Standard
  Written Chinese, as above.
- Decide each one with `investigate-line` as usual, minus its audio steps. A fix the meaning
  and a convention or name make certain is still a `fix`. A sound-alike fix no recogniser
  could confirm is a `suggest` at most, and a choice between candidates that differ only in
  sound is a `query`.
- Timing and splitting are not possible.
- In the summary, say plainly that the audio was not checked.

## Working draft vs source

`ccp status` shows `srt` (the working draft every tool reads) and `source_srt` (the user's
file). They are the same file unless `ccp pipeline` or `ccp copy-draft` made a workspace copy;
then `ccp apply` edits the copy and the user's file changes only through `ccp publish`. Say
which one you edited.

## Timing and splitting (only when the user asks for it)

Look for `T` lines (cues realign could not place), lint `short_duration` and `overlap`, and cues
holding two sentences across a clear pause or two speakers without `-` lines. Let the tool
compute the times; never type timestamps.
- Split: `uv run ccp timing <id> <N> --split "<first piece>|<second piece>"` (the pieces must
  spell out the cue; `⏎` for a line break). An `onset_gaps_s` of about 0.7 s or more is a
  natural cut; under 0.4 s is one breath, better left whole.
- Retime: `uv run ccp timing <id> <N>`.
- Record: `uv run ccp flag add <id> --cue N --category segmentation` (or `timing`) `--grade
  suggest --timing --reason "..."`. `--timing` attaches the computed proposal. A record carries
  a text fix or a timing proposal, not both: fix the text first. If the output says the aligner
  barely hears the cue, grade it `query`.
- Retimes and splits are applied only from the reviewer's decisions, or with `ccp apply <id>
  --structure` when the user asked for them directly.
