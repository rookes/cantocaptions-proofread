---
name: prepare-draft
description: Run cantocaptions-ai on an episode through ccp to create or fix a subtitle draft before (or instead of) proofreading. Covers realigning a WIP subtitle or transcript onto the episode's audio (adjust, sync or transcript mode), transcribing an episode from scratch with ASR, reading the result, and publishing the finished draft into CantoCaptions. Use when the user asks to realign, retime, resync, fix the timing of, transcribe, or run cantocaptions-ai / ASR on an episode.
---

# Prepare a draft with cantocaptions-ai

cantocaptions-ai is the ASR and alignment pipeline in `../cantocaptions-ai`. You never run it
directly and never search the media drive yourself. `ccp pipeline` runs it on the episode's
media with the right audio track and the user's own settings (their `config/user.cfg` in that
repo: vocal isolation, diarization...). It writes everything into the episode workspace and
makes the result the workspace's **working draft**. The user's file in CantoCaptions is not
touched until you `ccp publish`, and only with their go-ahead.

## Steps

1. **Locate.** `uv run ccp locate <show> S1E03`. WIP and other excluded files are found like
   any other, and media is inferred from the show's other episodes when the dataset has not
   linked it (see `notes` in the output). If several files match, show them and ask. If
   locate reports no media, ask the user for the file and run
   `uv run ccp locate --select <episode_id> --media <path>`. For an episode with no subtitle
   at all: `uv run ccp locate --media <path> --id <name>`.
2. **Reference (optional but useful later).** `uv run ccp reference <id>`, as in proofreading.
3. **Choose the operation** (table below) and tell the user in one line what you will run.
4. **Run it** as a long-running (background) command. It takes roughly 3–10 minutes per
   episode, and progress lines stream as it goes:
   - `uv run ccp pipeline <id> realign --mode adjust`
   - `uv run ccp pipeline <id> transcribe`

   Extra cantocaptions-ai flags go after a bare `--`, for example
   `uv run ccp pipeline <id> realign --mode adjust -- --realign_pause_gap 0.4`. Use them only
   when the user asks for something specific.
5. **Read the result.** It reports cues in and out (adjust and transcript modes split cues at
   clear pauses, so the count usually grows), `timing_suspects` (cues whose placement realign
   does not trust, shown later as `T` lines), and the new draft's path. On failure, report the
   error and the log path. Do not retry with guessed flags.
6. **Continue.** After a realign of a human-made subtitle, run `uv run ccp evidence <id>` on the
   new draft and, if the user asked for a proofread, follow the `proofread-subtitles` skill.
   After a transcription (or a realign of an AI-generated file that was not cleaned yet), the
   draft is machine output: follow the `clean-draft` skill first, with no evidence. Corrections
   are applied to the working draft.
7. **Publish** when the work is done and the user agrees
   (`proofread-subtitles/references/report-and-apply.md`). The file name stays as it was;
   renaming a `[WIP]` file is the user's call.

## Which realign mode

- `adjust` (default): for a WIP or hand-timed subtitle whose timings are **roughly right but sloppy** (late starts, long tails, two sentences held in one cue). Each cue is re-placed against the audio, within a tolerance of where it was. Cues are split where the audio clearly pauses. Text is not cleaned.
- `sync`: for a subtitle with **good timing for a different release** (constant offset, speed difference, cuts). One fitted transform moves every cue. Durations scale, no forced alignment, no splitting. Text is not cleaned.
- `transcript`: for a **plain transcript**, or timings that are meaningless. Every line is placed from scratch. Text is cleaned with the language rules.
- `auto`: when unsure: `transcript` for untimed text, `sync` for a timed subtitle.

`--input draft` realigns the current working draft instead of the source (for example after
correcting its text). `--input <file>` realigns any other transcript.

## Transcribing from scratch

`ccp pipeline <id> transcribe` runs full ASR (VAD, the CantoCaptions model, alignment, cue
assembly and cleaning) and makes that the draft. An ASR draft is cleaned first with the `clean-draft` skill (text and
reference only). A full proofread against the audio comes after that, and only if the user
asked for one. Then the `≠qw` lines in `ccp render` compare it with the *other* recogniser.

## What not to do

- Do not run cantocaptions-ai or browse media folders yourself (AGENTS.md hard rule 1).
- Do not publish, rename or delete files in CantoCaptions without the user's explicit OK.
- A new pipeline run replaces the working draft. Realigning the draft itself (`--input draft`)
  keeps its corrections; any other run refuses while the draft has applied corrections, so
  publish first, or pass `--force` only if the user agrees.
