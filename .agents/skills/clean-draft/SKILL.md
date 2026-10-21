---
name: clean-draft
description: >-
  Fast text-only cleanup of machine-made or very messy Cantonese subtitles (AI-generated files from cantocaptions-ai, ASR transcriptions, rough drafts) before any audio work. Reads the draft with its reference subtitle and lint hits and applies the confident fixes in bulk with `ccp clean`; optionally follows with a realign and a full proofread. Use whenever the subtitles to proofread are AI-generated or ASR output (`machine_draft: true` in `ccp status`), or the user calls a file messy or rough.
---

# Clean a machine-made draft

AI-generated subtitles and ASR drafts come from the same speech models the evidence tools use,
so where the models were confidently wrong, the evidence tools agree with them. Building audio
evidence line by line costs a lot and still lets those errors through. A reader with the
reference and a knowledge of Cantonese catches most of them from the text alone. So:

1. **Cleanup pass, text only** (this skill): fix what you can be sure of, quickly and in bulk.
   No `ccp evidence`, `listen` or `score`.
2. **Only if the user asked** (a full or thorough proofread, a realign, finished quality):
   realign the cleaned draft, then proofread it at full effort ("Full pass" below).

`ccp status <id>` shows `machine_draft: true` for these drafts and `cleanup` once this pass is done.

## Commands

- `uv run ccp locate <show> E01 AI` · `uv run ccp status <id>`: find the file; what the workspace holds
- `uv run ccp copy-draft <id>`: edits go into a new file, not the source (before any edit)
- `uv run ccp reference <id>` (`--ocr`: ask first): the reference subtitle
- `uv run ccp clean <id> --lint --dry-run` · `--skip-lint <cue>`: mechanical lint fixes
- `uv run ccp render <id> --from 1 --to 60`: read the draft with `R` and lint lines
- `uv run ccp clean <id> --edits <file>` · `uv run ccp clean <id> "12|text|reason"`: apply your edits

## Steps

1. **Locate, settle the output and where it goes** (`proofread-subtitles` steps 1–2,
   including confirming media found by name). For a library file the user wants kept as it
   is, run `ccp copy-draft` now.
2. **Reference.** `ccp reference <id>`: with a reference this pass fixes far more. Note its
   `label`.
3. **Glossary.** Read `glossaries/<show_slug>.md` if it exists.
4. **Mechanical fixes.** `ccp clean <id> --lint --dry-run` lists the spelling-variant, glossary
   and punctuation fixes. Add `--skip-lint <cue>` where one would be wrong (a variant inside a
   name, a quotation or a longer word), then run it without `--dry-run`.
5. **Read and fix**, in windows of about 60 cues (`ccp render`). Read each window's output in
   full; if your tool shortened it, render a smaller window. For each window, write the edits
   you are sure of to a UTF-8 file and apply them with `ccp clean <id> --edits <file>`:

   ```
   12|艾倫，快啲走|name: the reference and the glossary write 艾倫; 愛倫 is a mishearing
   40|佢實囉囉攣|食多都亂 makes no sense; R 一定坐立不安 = 實 + 囉囉攣 (sat6 lo1 lo1 lyun1)
   57|?|meaning unclear: R says 他已經走了 but nothing in the draft sounds like it
   ```

   - `N|complete new text|reason`. The **reason is required**: why the line is wrong and why
     the new text is right. It may start with a category (`name:`, `standard:`,
     `punctuation:`, `missing:`, `extra:`). Lines without one are held back, not applied.
   - `N|?|reason` records a query. `⏎` is a line break inside a cue.
   - Edits are applied at once and recorded, so the next window sees the cleaned text and the
     user can undo any of them from the report. Cue numbers do not change.
   - Read the output: `held_back` (add reasons and resubmit), `particles_kept` and
     `particles_read_as_words` (see "Particles").
6. **Check.** `ccp clean <id> --lint --dry-run` once more (its output also counts the convention
   problems left); fix what is left with another `ccp clean`.
7. **Finish or continue** (below).

## What to fix

Fix only what you are sure of from the text, the reference and your knowledge of Cantonese,
following AGENTS.md "How to decide a line". A fix that needs a tool to be sure of belongs in the
full pass.
- **Names** (principle 2), consistent across the whole file.
- **Mishearings the meaning gives away:** the line is nonsense or contradicts `R`, and a
  Cantonese phrase that sounds like the draft (`investigate-line/references/sound-alikes.md`)
  says what `R` says. If none comes to mind at once, record a query. A quick `ccp sounds-like`,
  `ccp dict` or `ccp corpus` lookup is fine; a long investigation is not.
- **A written-Cantonese reference** (a human transcript, such as a video's own Cantonese
  captions): where it differs from the draft in content and is plausible, it is usually right.
  Take its words, written to the conventions, but keep the draft's particles.
- **Standard Written Chinese and convention slips** (的/這/沒/他們 where the Cantonese word was
  clearly said), variants and punctuation lint missed, obvious typos and duplications.
- **Without a reference:** only typos, convention slips, names the glossary or the file settles,
  and mishearings whose correct form is unmistakable from the context.

Do not rewrite a plausible line, touch timing, split cues, or run `evidence`, `listen` or `score`.

## Particles

The cleanup pass never changes a sentence-final particle: not its character, its tone, or
whether there is one, even in a line whose words you do fix. `ccp clean` enforces this: it puts
the draft's particle back, applies the rest of the edit and lists it in `particles_kept`.
These are **standard particles, not variants or typos**; never "normalise" them:
- 𠸏 ge2 (surprise, realisation, a soft question: `點解出面咁嘈𠸏？`) is not 嘅 ge3;
- 嘎 gaa4 (㗎 as a question: `乜你唔keep嘎？`) is not 㗎 gaa3;
- 𠿪 gaa2, 𠺢 gaa1 (in 𠺢嘛), 𠺝 gaak3, 𡁜 wo5, 𡅅 aak3, 𠻺 aa6 and 𠻹 tim1 are distinct particles too
  (`cantocaptions-standards` → `references/conventions.md`).

If a particle looks wrong for the line's meaning, record a query (`N|?|particle: ...`). If a
particle character was really a misheard word (爛嘅 for 爛gag), the edit may replace it with the
word; the tool applies it and lists it in `particles_read_as_words` for you to check.

## Finish or continue

**Cleanup only** (the default): the edits are already applied. Report, export or publish as the
request says (`proofread-subtitles/references/report-and-apply.md`). In the report the cleanup
edits are compact rows with their reason and audio clip; the user can undo or reword any of them.
Summarise the edits by category and the queries left open; say the cleanup used the text and the
reference only, and that a full pass (realign + proofread with audio evidence) is available.
Pass on the report's `about_this_proofread` lines as they are (`proofread-subtitles` step 8).
Never describe an edit as a particle or "dialect" correction: the cleanup makes none.

**Full pass** (the user asked for a full or thorough proofread, a realign, or finished quality).
It needs cantocaptions-ai: with `tools.audio_evidence: false` in `ccp status`, tell the user the
cleanup is as far as this machine goes, and offer a text-only proofread
(`proofread-subtitles`, "Without audio") instead.
1. `uv run ccp pipeline <id> realign --mode adjust --input draft`, run in the background. It
   re-places every cue of the cleaned draft against the audio and splits cues at clear pauses,
   keeping the cleaned text. The cleanup records move to `previous/`, so if the user wants to
   review the cleanup, build the report and wait for their decisions first.
2. Continue with `proofread-subtitles` from step 4 (Evidence) on the new draft, at full effort.
   Evidence runs only the independent recogniser, because the text came from the fine-tuned one.
3. A full pass without a realign: skip step 1 and run `ccp evidence` on the cleaned draft.
