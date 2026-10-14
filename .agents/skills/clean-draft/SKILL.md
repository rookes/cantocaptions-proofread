---
name: clean-draft
description: Fast text-only cleanup of machine-made or very messy Cantonese subtitles (AI-generated files from cantocaptions-ai, ASR transcriptions, rough drafts) before any audio work. Reads the draft with its reference subtitle and lint hits and applies the confident fixes in bulk with `ccp clean`; optionally follows with a realign and a full proofread. Use whenever the subtitles to proofread are AI-generated or ASR output (`machine_draft: true` in `ccp status`), or the user calls a file messy or rough.
---

# Clean a machine-made draft

AI-generated subtitles and ASR drafts come from the same speech models that the evidence tools
use. Where the models were confidently wrong, the evidence tools are confidently wrong with
them: the recognisers agree with the draft and the aligner hears it fine. Building audio
evidence line by line therefore costs a lot and still lets those errors through. A reader with
the reference subtitle and a knowledge of Cantonese catches most of them from the text alone.

So for these drafts the work happens in this order:

1. **Cleanup pass, text only** (this skill): fix everything you can be sure of from the text,
   quickly and in bulk. No `ccp evidence`, `listen` or `score`.
2. **Only if the user asked for it** (a full or thorough proofread, a realign, finished
   quality): realign the cleaned draft, then do the normal full-effort proofread on it.

`ccp status <id>` shows `machine_draft: true` for AI-generated files, transcriptions and
realigns of either, and `cleanup` says whether this pass has been done.

## Steps

1. **Locate and settle the output** as in `proofread-subtitles` steps 1–2. Also settle where
   the result goes ("Where the result goes" in that skill): for a library file the user wants
   kept as it is, run `uv run ccp copy-draft <id>` now, before any edit.
2. **Reference.** `uv run ccp reference <id>` (ask before OCR, as always). With a reference this
   pass can fix far more, so get one if one exists. Note its `label`.
3. **Glossary.** Read `glossaries/<show_slug>.md` if it exists.
4. **Mechanical fixes.** `uv run ccp clean <id> --lint --dry-run` lists every mechanical lint
   fix (spelling variants, glossary forms, punctuation). Skim it; for a cue where a fix would
   be wrong (a variant inside a name, a quotation or a longer word), add `--skip-lint <cue>`.
   Then run it without `--dry-run`. Leave particle-character hits (`L compound_particle`,
   `L particle_variant`) alone in this pass (see "Particles" below).
5. **Read and fix.** Read the whole draft in windows of about 60 cues:
   `uv run ccp render <id> --from 1 --to 60`, and so on. Read each window's output in full;
   if your tool shortened it, render a smaller window rather than skipping cues. For each window, write the
   edits you are sure of to a UTF-8 file, one per line, and apply them with
   `uv run ccp clean <id> --edits <file>`:

   ```
   12|艾倫，快啲走|name: the reference writes 艾倫
   40|佢實囉囉攣|reference: 一定坐立不安
   41|你講咩呀？
   57|?|meaning unclear; reference: 他已經走了
   ```

   - `N|full new text|reason`. The reason is optional and may start with a category
     (`name:`, `standard:`, `punctuation:`, `missing:`, `extra:` …) and a source
     (`reference:`, `glossary:`, `context:` …). Without a category, the tool infers one.
   - `⏎` is a line break inside a cue.
   - `N|?|reason` records a query: the line is wrong but you cannot tell how.
   - Edits are applied at once and recorded as flags, so the next window sees the cleaned
     text and the user can undo any edit from the report. Cue numbers do not change.
   - A few edits can go straight on the command line: `uv run ccp clean <id> "12|艾倫，快啲走"`.
   - Read the output. `particles_kept` lists edits where the tool put the draft's
     sentence-final particle back (see "Particles"), and `particles_read_as_words` lists
     particle characters your edit replaced with words. Check each one of those is really a
     misheard word, not a particle choice.
6. **Check.** `uv run ccp lint <id>` once more; fix what is left with another `ccp clean`.
7. **Finish or continue** (below).

## What to fix in the cleanup pass

Fix only what you are sure of from the text, the reference and your knowledge of Cantonese.
Move quickly: a fix that needs a tool to be sure of belongs in the full pass, not here.

- **Names.** Copy them from the reference, as in every proofread (AGENTS.md hard rule 7): the
  glossary first, then the reference's written form verbatim, or a short form of it the
  speaker used. Make the same name consistent across the whole file.
- **Mishearings that the meaning gives away.** The line is nonsense or contradicts the
  reference, and a Cantonese phrase that sounds like the draft (see
  `investigate-line/references/sound-alikes.md`) says what the reference says. If no
  sound-alike comes to mind at once, record a query instead of investigating.
  `ccp sounds-like`, `ccp dict` and `ccp corpus` are text tools and quick, so use them when
  one lookup settles a doubt. Do not use them for a long investigation.
- **A written-Cantonese reference** (a human transcript, such as a video's own Cantonese
  captions): where it differs from the draft in content and is plausible, it is usually right.
  Take its words, written to the CantoCaptions conventions. Its particles, punctuation and
  variants are not evidence: keep the draft's particles.
- **Standard Written Chinese and convention slips**: 的/這/沒/他們 where the Cantonese word was
  clearly said; variants and punctuation that lint missed.
- **Obvious typos and duplications**: a doubled word, a dropped character in a set phrase.
- **Without a reference**, fix only typos, convention slips, names the glossary or the file
  itself settles, and mishearings whose correct form is unmistakable from the context.

Do not:
- change sentence-final particles at all (next section);
- rewrite a line that is plausible Cantonese, even if the reference words it differently;
- touch timing or split cues;
- run `ccp evidence`, `listen` or `score` in this pass.

## Particles

The cleanup pass never changes a sentence-final particle: not its character, not its tone,
not whether there is one. Particles are judged by ear and by the standard's fine
distinctions, and a text-only pass gets them wrong far more often than right. Leave every
particle exactly as the draft has it, including in a line whose words you do fix. `ccp clean`
enforces this: it puts the draft's particle back and applies the rest of the edit.

Most of these characters are **CantoCaptions standard particles, not variants or typos**.
Never "normalise" one to the character you would expect from written Cantonese elsewhere:
- 𠸏 ge2 (surprise, realisation, a soft question: `點解出面咁嘈𠸏？`) is not 嘅 ge3;
- 嘎 gaa4 (㗎 as a question: `乜你唔keep嘎？`) is not 㗎 gaa3;
- 𠿪 gaa2, 𠺢 gaa3 (+嘛), 𠺝, 𡁜 wo5, 𡅅, 𠻺 and 𠻹 are distinct particles too.
`cantocaptions-standards` → `references/conventions.md` lists them with their readings.

If a particle looks wrong for the line's meaning, record a query (`N|?|particle: ...`) for the
reviewer. If a particle character was really a misheard word (爛嘅 for 爛gag), the edit may
replace it with that word; the tool applies it and lists it for you to check.

## Finish or continue

**Cleanup only** (the default when the user asked for nothing more):
- the edits are already applied to the draft. Report, export or publish as the request says
  (`proofread-subtitles` → "Where the result goes"; for a link job, `subtitles-from-link`
  step 5). With a report, `ccp report <id>` lists the cleanup edits as compact rows, each with
  its audio clip, where the user can undo or reword any of them. Queries appear as normal
  cards. Cutting the clips takes a minute or two for a few hundred edits.
- In the summary, give the number of edits by category and the queries left open. Do not
  describe any edit as a particle or "dialect" correction: the cleanup makes none. Say that
  the cleanup used the text and reference only, and that a full pass (realign + proofread
  with audio evidence) is available.

**Full pass** (the user asked for a full or thorough proofread, a realign, or finished
quality):
1. `uv run ccp pipeline <id> realign --mode adjust --input draft`, run in the background.
   It re-places every cue of the cleaned draft against the audio and splits cues at clear
   pauses. The cleaned text is kept. The cleanup flags move to `previous/`, so the user can no
   longer undo them one by one after this point. If the user wants to review the cleanup
   first, build the report and wait for their decisions before realigning.
2. Continue with `proofread-subtitles` from step 4 (Evidence) on the new draft, at full
   effort. A cleaned draft should now be close to finished, so the "proportion" boundary of
   that skill applies again. Evidence still runs only the independent recogniser, because
   the text came from the fine-tuned one.
3. If the user asked for the full pass without a realign, skip step 1 and run
   `ccp evidence` on the cleaned draft directly.
