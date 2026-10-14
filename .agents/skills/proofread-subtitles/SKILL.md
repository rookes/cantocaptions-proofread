---
name: proofread-subtitles
description: Proofread a CantoCaptions written-Cantonese subtitle file (an episode or movie) against its audio, a reference subtitle and the CantoCaptions conventions, then report flagged lines (HTML report with audio clips) and/or apply accepted corrections. Use when the user asks to proofread, check, review or correct an episode or .srt file.
---

# Proofread a subtitle file

You are proofreading one subtitle file end to end. The goal is a short, trustworthy list of
corrections: lines whose text does not match what was said, or does not follow the
CantoCaptions conventions. You find them by reading every cue alongside evidence that the
tools put next to it, and you investigate each suspect line before you propose a fix.

Read `references/workflow.md` for the detailed procedure and output formats,
`references/flag-taxonomy.md` for how to classify and grade findings, and
`references/report-and-apply.md` for the output step. Load the `investigate-line` skill
when you investigate a suspect, and `cantocaptions-standards` whenever a question is about
how something must be written.

## Procedure

1. **Locate.** Run `uv run ccp locate <the user's words>` (for example
   `uv run ccp locate Attack on Titan S1E03`). A unique match creates the workspace and prints
   the episode record: subtitle path, media path, audio track, quality tier, and `notes`
   (for example, media inferred from the show's other episodes, or a WIP file). If there are
   several candidates, show them and ask. For a file anywhere else use
   `uv run ccp locate --srt <path>`; if media is missing, ask the user for it and pass `--media`.
   Never search for files yourself.
   If the user also wants the timing fixed or the episode transcribed first, follow the
   `prepare-draft` skill now and come back here at step 3 (Reference).
   If the record says `ai_generated: true` (or `ccp status` shows `machine_draft: true`) and
   the draft has not been cleaned yet, stop here and follow the `clean-draft` skill instead.
   It does a text-only cleanup first and comes back to step 4 only for a full pass.
2. **Settle the output.** If the user has not said whether they want a report or edits to the
   file, ask now (see AGENTS.md).
3. **Reference.** Run `uv run ccp reference <id>`. If it answers `needs_decision`, tell the user
   what is available (an English text track, a Chinese image track that needs OCR) and ask
   which to use; then run it with `--stream N`, `--file PATH` or `--ocr`. Note the
   `agreement`: below 0.6 the reference is timed differently, so trust it for names and
   meaning only.
4. **Evidence.** Run `uv run ccp evidence <id>` (GPU, a few minutes per episode; add `--diarize`
   when speaker identity matters). Then `uv run ccp lint <id>`.
5. **Names and glossary.** Open `glossaries/<show_slug>.md` if it exists. For names, the order
   of authority is: the glossary, then the reference (copied verbatim, or a short form or
   nickname of it that the speaker said), then other strict episodes of the same show
   (`uv run ccp corpus "<name>" --show <show_slug>`) and the file's own majority spelling. A name
   the glossary or a Chinese reference settles needs no audio check, sound-alike search or
   corpus search: just fix it. Add names you learn to the glossary (format in
   `references/workflow.md`), so episodes without a reference can use them.
6. **Review pass.** Read the whole file in windows of about 60 cues:
   `uv run ccp render <id> --from 1 --to 60`, then 61–120, and so on, to the last cue. For every
   cue decide: *fine*, *convention problem*, or *suspect*. Write down suspects as you go (cue
   number and why). Do not investigate during this pass; finish reading first, because later
   cues often explain earlier ones (names, running jokes, who is speaking).
7. **Investigate.** Fetch all suspects in one call (`uv run ccp cue <id> 9 11 24 ...`), then
   triage them:
   - **Settled already:** both recognisers hear the same fix **and it means what the reference
     line means**, or it is a convention, name or obvious typo fix. Record it directly. No
     further tools. Recognisers agreeing on a wording whose meaning differs from the reference
     settle nothing: if the draft fits the reference, the draft is right and both recognisers
     misheard it.
   - **Needs work:** the meaning is wrong but no recogniser heard the answer, the candidates
     compete, or a word may be missing or extra. Follow the `investigate-line` skill.
   - **Not a suspect after all:** the recognisers differ, but the draft means what the
     reference means and their version does not. Record nothing and do not investigate it
     with audio: the reference has decided.
   Record outcomes with `uv run ccp flag add ...` (one flag per cue; for many flags at once, a
   JSON list with `--json-file`), including the evidence that decided each one. Record a cue you
   investigated and found correct as nothing at all.
8. **Output.** (When everything is finished, `references/report-and-apply.md` → Cleaning up.) Build the report (`uv run ccp report <id>`) and/or apply edits as the user asked
   (`references/report-and-apply.md`). Finish with a short summary: how many flags by severity,
   the most important corrections in one line each, and the report path.

## What makes a cue suspect

Mark a cue suspect when one or more of these holds. Each is a reason to *look*, not proof:

- Its meaning does not fit the reference line (`R`) or the surrounding conversation.
- An ASR line (`≠ft` fine-tuned recogniser, `≠qw` stock Qwen3-ASR) differs from it in *content*.
  The tools only show these lines when the content differs. Hidden on purpose: differences in
  clause-final particles, punctuation and pure spelling variants (説/說, 裏/裡), and for stock
  Qwen also 噉/咁, 邊/便 and 着/著, which it does not distinguish. When **both** recognisers agree with each other against
  the draft, take it seriously as a question about *wording*. When only one differs, it is
  weak evidence. Either way, first compare meanings: if the draft means what `R` means and
  the recognisers' version does not, the recognisers misheard and the cue is fine.
- A run of weak characters (`! 字 0.02`): the aligner could not hear those characters where the
  draft has them. Weak characters cluster on real errors, but also on fast or noisy speech.
- A lint line (`L …`): a convention violation or an inconsistent spelling.
- A name that is written differently from the glossary, the reference or elsewhere in the file
  (fix it to the glossary's or the reference's form; see step 5).
- Text that is grammatical Standard Chinese rather than spoken Cantonese.

## Boundaries

- Do not flag style preferences that the conventions do not require.
- Do not "improve" wording, add words for clarity, or normalise a speaker's grammar. The
  standard keeps intended speech, so only clear misspeaks that the style guide says to drop
  are fair game.
- Sentence-final particles: flag only with strong evidence, and always at severity `query`
  unless the particle is a convention error (wrong character for its reading). The tools hear
  particles poorly and past automated particle edits were wrong far more often than right.
  What can raise a particle query is **meaning**: the draft's particle gives the line a
  different force from the reference line, such as a question where the reference states,
  a statement where it asks, or an order or a surprise it lacks. Once meaning has raised the
  query, the recognisers' particles may support which alternative to offer. Example: the
  draft 人死咗就唔識講嘢嘅呢？ asks, R 人死了就不會說話 states, and both recognisers hear
  㗎啦, so record a `query` with 㗎啦 (and 㗎喇) as alternatives. A recogniser's particle on its
  own is no evidence: they insert, drop and swap particles freely, which is why `ccp render`
  hides particle-only differences. Never flag, investigate or score a cue only because an
  ASR line ends in a different particle, or has one where the draft has none.
- Cue timing and segmentation: propose retimes and splits only when the user asked for them
  (see "Timing and splitting" below). Otherwise report such problems as flags with no proposed
  fix.
- Proportion: in a file the episode record calls `strict`, almost every cue is already right.
  If your suspect list grows past a small fraction of the cues, you are probably flagging
  preferences or the recognisers' habits; re-read these boundaries before going on. Files of a
  lower tier can legitimately have many convention flags (lint will show them).

## Working draft vs source

`ccp status <id>` shows `srt` (the working draft) and `source_srt` (the user's file). They are
the same file unless `ccp pipeline` made a new draft (`draft_origin`). In that case every tool
reads `work/<id>/draft.srt`, `ccp apply` edits that copy, and the user's file changes only
when you run `ccp publish <id>` with their agreement. Say which one you edited in your summary.

## Timing and splitting (only when the user asks for it)

When the user allows retiming or splitting, look for:
- `T` lines in `ccp render` (cues a realign run could not place confidently);
- lint `short_duration` (three or more characters on screen for under 0.75 s) and `overlap`;
- a cue holding two sentences across a clear pause, or two speakers without the `-` lines.

Then let the tool compute the timing from the audio. Never invent timestamps.
- Split: `uv run ccp timing <id> <N> --split "<first piece>|<second piece>"`. The pieces must
  spell out the cue exactly. Use `⏎` inside a piece for a line break, and keep the `-` of a
  speaker line. Check `onset_gaps_s`: a pause of about 0.7 s or more between sentences is
  a natural cut, while under 0.4 s is usually one breath and better left whole.
- Retime: `uv run ccp timing <id> <N>`. It proposes start and end from where the speech
  is, following the style guide (start 0–50 ms before speech, about 350 ms trail, at least
  0.75 s, never overlapping neighbours).
- If the output says the aligner barely hears the cue, treat the times as rough and grade the
  flag `query`.
- Record it: `uv run ccp flag add <id> --cue N --category segmentation` (or `timing`)
  `--severity suggested --confidence medium --timing --evidence "..."`. `--timing` attaches
  the proposal you just computed. A flag can carry a timing proposal or a text fix, not both:
  fix the text first (apply it), then time the corrected cue.
- Retimes and splits are applied only from the reviewer's accepted decisions, or with
  `ccp apply <id> --structure --min-severity suggested --min-confidence medium` when the user
  asks for them directly.

## AI-generated subtitles and ASR drafts

`ccp locate` finds files in the `(AI-generated)` trees too (`ai_generated: true` in the
record; add "AI" to the request to prefer them). These and ASR transcriptions are machine
output from the same models the evidence tools use, so the evidence tools miss exactly the
errors the models were confident about. Clean them first with the `clean-draft` skill (text
only, fast, in bulk). This skill's evidence-based procedure is the optional second, full pass
on the cleaned (and usually realigned) draft:
- `ccp evidence` uses only the independent recogniser (stock Qwen3-ASR), because the
  fine-tuned model wrote the text;
- the reference is usually a bitmap track in the media that needs OCR. Ask before running it,
  as always. If the user wants no interaction, work without a reference and say so.
If the record notes that no audio track is tagged Cantonese, check the `≠qw` lines of the
first window. If they are another language, ask the user which track to use.

## Where the result goes

Decide this before applying anything, from the user's request:
- **Correct the file itself** (the default): `ccp apply` edits it in place.
- **"Put the edits in a new file"**, or any target other than the source: run
  `uv run ccp copy-draft <id>` *before* applying. Edits then go into a workspace copy. When
  finished, write it out:
  - `uv run ccp publish <id> --to-main` puts it in the show's folder in the main library area:
    the same category and tree without "(AI-generated)", an existing folder for the show if
    there is one (otherwise it creates one), and a library-style name (`[CCAI]` tag dropped,
    `.yue.cht.srt`);
  - or `uv run ccp publish <id> --to <file or folder>`.

  Run it with `--dry-run` first and report the target path. A request that already names the
  destination ("add it to a new X folder in the main area") is the user's go-ahead to publish
  there. Never overwrite an existing file unless the user says so (`--overwrite`).
- **No report wanted** ("no need for a report"): apply the confident and suggested
  corrections directly (`ccp apply <id> --min-severity suggested --min-confidence medium`),
  leave queries and particle questions unapplied, and list them in your summary instead.
- If `publish` returns a `warning` (an AI-generated file going into the main area, where the
  dataset would treat it as hand-made), pass it on to the user word for word.

