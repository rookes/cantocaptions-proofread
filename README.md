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

On Windows, from this folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

It installs what is missing (uv, ffmpeg, the Python packages), builds the dictionary caches
and ends with a short summary of what this machine has. Then open the folder in Claude Code or
Antigravity and ask for a proofread. The agent runs the same check at the start of each
session, runs the script itself if something is missing, and on first use asks where any
optional repositories below are.

Also useful: Node.js or deno, which `ccp fetch` needs to download from YouTube (update yt-dlp
with `uv lock --upgrade-package yt-dlp` when a site changes), and, for the audio tools, an
NVIDIA GPU (8 GB or more) with cantocaptions-ai.

### Reviewing a report

At the end of a proofread the agent opens the report in your browser. It is served from your
own machine (`http://127.0.0.1:8765/r/<episode>/`), and your accept/reject choices save
straight into the workspace as you go. Press **Done reviewing** and tell the agent. To view it
inside the IDE instead, open the link in the IDE's browser panel (in VS Code-based editors:
Command Palette → "Simple Browser: Show", then paste the link). `http://127.0.0.1:8765/` lists
every report. Without the server (it stops by itself about ten minutes after the last report tab closes, or with `ccp report --stop`; `ccp report <id>` starts it
again), `work/<id>/report.html` still opens as a plain file, and **Export decisions** downloads
a `decisions.json` to give the agent.

### Optional sibling repositories

The agent works with whichever of these the machine has, next to this repo by default:

```
source/
  CantoCaptions/            subtitle library
  cantocaptions-dataset/    manifest (subtitle -> media) and quality tiers; run its `scan` and `stdcheck`
  cantocaptions-ai/         speech models and OCR (its own .venv, models downloaded)
  cantocaptions-proofread/  this repo
```

| repository | enables | without it |
|---|---|---|
| CantoCaptions | finding a subtitle by show and episode; the strict corpus (with the dataset); `publish` into the library | give the subtitle's path, or pick one beside the media; no corpus; `publish --to PATH` |
| cantocaptions-dataset | subtitle-to-media links, quality tiers, the strict corpus, current variant rules | media is searched for by name in your media folders (always confirmed with you); no tiers or corpus; lint uses `config/standardization.snapshot.toml` |
| cantocaptions-ai | audio evidence (`evidence`, `listen`, `score`, `timing`), missing lines (`listen --missing`), `pipeline`, OCR of image subtitle tracks (with its `ocr` extra) | a text-only proofread against the reference and the conventions |

`uv run ccp setup` reports which are present. On first use the agent asks where the missing
ones are (or records that you do not have them) and writes the answers to
`config/paths.local.toml`; `ccp setup --set KEY=PATH`, `--add-media-dir PATH`,
`--decline KEY` and `--done` do the same by hand.

**Media folders.** Without the dataset, `ccp locate "Show S1E03"` searches your own media
folders (`media_dirs`, any layout) by show name and episode number: release names, initials
(AoT) and either half of a bilingual folder name all match. A match is only a candidate; the
agent shows it to you and asks before using it. Subtitle files beside the media are offered as
the draft or as references.

Paths live in `config/paths.toml`. Machine-specific overrides go in `config/paths.local.toml`.
Defaults, relative to this directory:

| what | where |
|---|---|
| CantoCaptions subtitle library (a git repo) | `../CantoCaptions/Subtitles/` |
| cantocaptions-dataset (manifest linking subtitles to media, quality tiers) | `../cantocaptions-dataset/data/` |
| cantocaptions-ai (ASR, alignment, vocal isolation, diarization, OCR) | `../cantocaptions-ai/` |
| media files the dataset links to | `E:/dataset_media/` |
| your own media folders | `media_dirs` (none by default) |
| words.hk dictionary (its CSV export; every words.hk lookup reads this one file) | `dictionaries/words.hk-ordered.csv` |
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
| `ccp setup` | which optional repos and media folders this machine has; record first-use answers |
| `ccp glossaries` | every show glossary on this machine, with how many names each has (`ccp status` names the episode's own) |
| `ccp locate "<show> S1E03"` | find subtitle + media (WIP files too; media inferred from sibling episodes when the dataset has none, or searched for by name in your media folders), create the workspace |
| `ccp pipeline <id> realign --mode adjust` / `transcribe` | (GPU) run cantocaptions-ai on the episode; its output becomes the working draft |
| `ccp publish <id>` | copy a pipeline draft back over the source file in CantoCaptions |
| `ccp fetch <url>` | download a video's audio and its subtitles (as references) with yt-dlp |
| `ccp export <id>` | one folder with the final subtitles, the original ASR, the references and the report |
| `ccp segment <id> --edits FILE` | cleanup pass only: re-cut cues without changing a word before the realign, join quick exchanges after it |
| `ccp missing <id>` | reference lines no cue covers (`+R#N`): where the draft may be missing a line |
| `ccp reference <id>` | find/extract/OCR a reference subtitle and line up its timing |
| `ccp evidence <id>` | (GPU) both recognisers and aligner peaks for every cue |
| `ccp render <id> --from N --to M` / `--save` / `--only lint` | the review stream, printed or saved to `work/<id>/review.txt`; `--only` keeps just the cues with lint (or `asr`, `weak`, `timing`, `seg`, `missing`) lines |
| `ccp cue <id> N` | everything about one cue |
| `ccp sounds-like <span> --hyp …` | words that sound like a suspect span (words.hk + strict corpus) |
| `ccp dict` | words.hk dictionary (particles are looked up by their reading) |
| `ccp corpus` | evidence from strict-tier subtitles only; `--final` counts the particles that end a phrase |
| `ccp particles scan <id>` / `explain 喇` / `colloc <phrase>` / `model <id>` / `note add` | sentence-final particles: every particle of a draft with what the standards, the fine-tuned recogniser (GPU `model`) and the strict-corpus and recorded collocations say; one particle's usage; which phrases pull which particle; record a collocation (`particles/collocations.toml`) |
| `ccp listen`, `ccp score` | (GPU) re-run recognisers on a cue (`--missing N`: a reference line no cue covers, heard four ways); CTC-score candidate texts (from stored emissions, no GPU). Both take many cues from `--json-file` |
| `ccp clean <id> --lint` / `--edits FILE` | text cleanup of machine-made drafts: bulk edits, recorded as flags and applied at once |
| `ccp flag add/keep/update/list` | record each decision: grade fix / suggest / query / keep, with a required reason |
| `ccp report <id>` | HTML report with clips, opened in the browser from a local server; decisions save into the workspace |
| `ccp apply <id> [--reviewed \| --decisions …] [--include-suggest]` | apply corrections in place (text only, never commits) |

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

## Updating the conventions

Mechanical checks (the `L` lines, `ccp clean --lint`, and which recogniser spellings the
review stream hides) all come from **`config/lint.toml`**, applied on top of
cantocaptions-dataset's `rules/standardization.toml`, which is read at run time (or, on a machine
without the dataset, its bundled copy `config/standardization.snapshot.toml`, which
`scripts/build_standards.py` refreshes). Edit
`lint.toml`; nothing needs rebuilding.

| to … | in `config/lint.toml` |
|---|---|
| require a spelling (X is always wrong, Y right) | an `[[extra_variants]]` entry: `nonstandard`, `standard`, optional `note` |
| question a spelling that is only sometimes wrong | the same entry with `confidence = "heuristic"`, or the form in `query_variants` |
| stop a rule firing inside a word (如果啲, 小姐係) | add the word to `protect` |
| drop a dataset rule | its `nonstandard` form in `skip_variants` |
| flag a Standard Written Chinese word | an `[[swc]]` entry with its `exceptions` |
| hide a recogniser spelling that is not a rule | `[asr_fold]` (every firm one-character variant is hidden already) |
| change the line width | `[limits]` |

A show's names go in `glossaries/<show>.md` (`Avoid` column) instead.

Check a change with `scripts/lint_rules.py`:
- `--list` prints every rule in effect and its source;
- `"<line>"` lints a sample line;
- `--survey <form>` runs the rule over the strict corpus and shows which lines it flags and
  which a protected word saves. A firm rule should fire on almost no strict-tier lines.

The other places conventions live serve other readers:
- **The agent's prose:** CantoCaptions `README.md` and `Optional Characters.md`, and
  cantocaptions-ai's `languages/yue/proofread/cantocaptions.md`. Refresh the skill's copies
  with `scripts/build_standards.py`.
- **The dataset's tier scoring:** the dataset's `standardization.toml`. Edit it there only
  when the dataset should count the rule too.
- **The transcription pipeline:** cantocaptions-ai's `languages/yue/rules/*.toml` rewrite
  machine output. Lint catches anything they miss.

## Tests

```
uv run pytest
```

CPU only. Tests that need the dictionary, CantoCaptions or the dataset skip when those are
missing. The GPU tools are exercised by the smoke case in `tests/single-line-smoke` (see
`.agents/skills/investigate-line/references/worked-examples.md`).
