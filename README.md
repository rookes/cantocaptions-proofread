# cantocaptions-proofread

A workspace where a code agent (Claude Code or Google Antigravity) proofreads CantoCaptions
written-Cantonese subtitles. Ask it, for example:

> Proofread Attack on Titan Season 1 Episode 3 and give me a report.

The agent finds the subtitle and its media, gets a reference subtitle, runs two speech
recognisers and a forced aligner over every cue, reviews the file, investigates each suspect
line with sound-alike search, the words.hk dictionary and the standardized CantoCaptions corpus,
and then writes an HTML report with audio clips. On request it also applies the accepted
corrections to the subtitle file in place. It never commits.

## Setup

Requirements: Windows, [uv](https://docs.astral.sh/uv/), ffmpeg on PATH, Node.js or deno (yt-dlp
needs a JavaScript runtime for YouTube; update yt-dlp with `uv lock --upgrade-package yt-dlp` when a
site changes), an NVIDIA GPU (≥ 8 GB)
for the audio tools, and the sibling repositories next to this one:

```
source/
  CantoCaptions/            subtitle library
  cantocaptions-dataset/    manifest (subtitle -> media) and quality tiers; run its `scan` and `stdcheck`
  cantocaptions-ai/         speech models (its own .venv, models downloaded)
  sub-convert/              OCR of image subtitles (optional)
  cantocaptions-proofread/  this repo
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Paths live in `config/paths.toml`. Put machine-specific overrides in `config/paths.local.toml`.
Defaults, relative to this directory:

| what | where |
|---|---|
| CantoCaptions subtitle library (a git repo) | `../CantoCaptions/Subtitles/` |
| cantocaptions-dataset (manifest linking subtitles to media, quality tiers) | `../cantocaptions-dataset/data/` |
| cantocaptions-ai (ASR, alignment, vocal isolation, diarization) | `../cantocaptions-ai/` |
| sub-convert (OCR of image subtitles) | `../sub-convert/` |
| media files | `E:/dataset_media/` |
| words.hk dictionary | `dictionaries/words-hk-full-bilingual.json` |
| per-show name glossaries (kept by the agent) | `glossaries/<show_slug>.md` |

### Windows console encoding

`ccp` prints UTF-8. Windows PowerShell decodes program output with the console's legacy code
page (437 on an English system) unless `[Console]::OutputEncoding` is set to UTF-8, which
garbles Chinese text for the user and for agents alike. Neither `chcp 65001` nor anything
`ccp` can do from inside fixes it once the session has read another program's output; the fix
is `[Console]::OutputEncoding = [Text.UTF8Encoding]::new()`, once per session (AGENTS.md tells
agents to do this). `scripts\setup.ps1 -FixConsole` adds it to your PowerShell
profile so every session (including an agent's, if its terminal loads the profile) gets it.

## Layout

| path | what |
|---|---|
| `AGENTS.md` | always-on instructions (Antigravity reads it; `CLAUDE.md` imports it) |
| `.agents/skills/` | the skills: `proofread-subtitles`, `clean-draft`, `prepare-draft`, `subtitles-from-link`, `investigate-line`, `cantocaptions-standards` (`.claude/skills` is a junction to it) |
| `src/ccp/` | the `ccp` tools (`uv run ccp -h`) |
| `src/ccp/gpu/` | scripts that run inside cantocaptions-ai's environment |
| `config/` | paths, Jyutping confusion costs, lint settings, particle readings |
| `dictionaries/` | words.hk |
| `glossaries/` | per-show names, kept by the agent |
| `work/<episode_id>/` | per-episode workspace: evidence, flags, report (gitignored) |
| `scripts/` | setup, `build_standards.py` (refresh the standards skill), `measure_confusions.py` (calibrate sound-alikes) |

## The tools at a glance

| command | does |
|---|---|
| `ccp locate "<show> S1E03"` | find subtitle + media (WIP files too; media inferred from sibling episodes when the dataset has none), create the workspace |
| `ccp pipeline <id> realign --mode adjust` / `transcribe` | (GPU) run cantocaptions-ai on the episode; its output becomes the working draft |
| `ccp publish <id>` | copy a pipeline draft back over the source file in CantoCaptions |
| `ccp fetch <url>` | download a video's audio and its subtitles (as references) with yt-dlp |
| `ccp export <id>` | one folder with the final subtitles, the original ASR, the references and the report |
| `ccp timing <id> N [--split "a\|b"]` | retime or split proposals from the stored audio alignment |
| `ccp reference <id>` | find/extract/OCR a reference subtitle and line up its timing |
| `ccp evidence <id>` | (GPU) both recognisers and aligner peaks for every cue |
| `ccp render <id> --from N --to M` | the review stream |
| `ccp cue <id> N` | everything about one cue |
| `ccp sounds-like <span> --hyp …` | words that sound like a suspect span (words.hk + strict corpus) |
| `ccp dict` | words.hk dictionary (particles are looked up by their reading) |
| `ccp corpus` | evidence from strict-tier subtitles only; `--final` counts the particles that end a phrase |
| `ccp listen`, `ccp score` | (GPU) re-run recognisers on a cue; CTC-score candidate texts (from stored emissions, no GPU) |
| `ccp clean <id> --lint` / `--edits FILE` | text-only cleanup of machine-made drafts: bulk edits, recorded as flags and applied at once |
| `ccp flag add/keep/update/list` | record each decision: grade fix / suggest / query / keep, with a required reason |
| `ccp report <id>` | HTML report with clips, exports `decisions.json` |
| `ccp apply <id> [--decisions …] [--include-suggest]` | apply corrections in place (text only, never commits) |

## Scoring from stored emissions

`ccp evidence` stores each cue group's aligner emission (fp16 log-probabilities) in
`work/<id>/emissions/`, roughly 100–200 MB per episode, together with a token table that the
pipeline's own `VocabRepair` resolves. `ccp score` then runs in the light environment
(`src/ccp/ctcscore.py`), with no torch, no GPU and no server. It uses the same text steps as the
GPU scorer (numeral readings, particle stripping, homophone canonicalisation) and a numpy CTC
forward pass. Each cue is scored on its frames sliced from the group's emission, so the model
has heard the surrounding speech.

Scoring never loads the aligner. An explicit `--pad`/`--start`/`--end` span is cut from the
stored emission of the group around it (stopping at the group's edges, which already include
its padding); a character outside the token table counts as unscorable; a workspace without
stored emissions needs `ccp evidence --force` once. `scripts/compare_score_paths.py` checks the
numpy scorer against the torch aligner (on identical input, and per-clip against group-slice
scoring) on the candidates in `tests/fixtures/score_cases.json`.

`listen` runs in a GPU server (`src/ccp/gpu/server.py`) that keeps the recognisers loaded
between calls: a pass loads each model once
instead of once per call (a re-listen drops from 20–40 s to a few seconds). Agent harnesses end
a command's whole process tree when the command returns, so `ccp` starts the server outside it,
through WMI on Windows, with a hidden window. When the two recognisers do not fit on the card
together, the server unloads the least recently used one to make room. It stops when a
pass ends (`report`, `apply`, `export`, `publish`, `prune`), before other GPU work (`evidence`,
`pipeline`, OCR), or after 15 minutes unused. `ccp status <id>` shows it (`gpu_server`); its log is
`cache/gpu_server.log`. `CCP_GPU_SERVER=0` turns it off (each call then loads its own models).

## Tests

```
uv run pytest
```

CPU only. Tests that need the dictionary, CantoCaptions or the dataset skip when those are
missing. The GPU tools are exercised by the smoke case in `tests/single-line-smoke` (see
`.agents/skills/investigate-line/references/worked-examples.md`).
