---
name: clean-draft
description: >-
  Cleanup of machine-made or messy Cantonese subtitles (AI-generated files from cantocaptions-ai, ASR transcriptions, hand-made WIP or rough files): standards, punctuation, wording and particles fixed line by line, stray interjections taken out, lines the draft is missing where the reference has one, cues re-cut, then an adjust realign that times everything, then quick exchanges joined. Optionally followed by a full proofread. Use whenever the subtitles are AI-generated or ASR output (`machine_draft: true` in `ccp status`), or the user calls a file messy, rough or WIP.
---

# Clean a messy or machine-made draft

In a messy file most lines need something: the conventions (variants, English case, commas
after particles), the particles themselves, stray interjections, the wording, missing lines,
the cutting into cues, and the timing. Expect to change most cues. This pass fixes them in this
order, and you never touch a timestamp: the realign times everything.

1. **Text** (steps 4-6): line by line, in small windows.
2. **Missing lines** (step 7): reference lines no cue covers.
3. **Splitting** (step 8): you decide which words go in which cue; one line per cue.
4. **Realign** (step 9): cantocaptions-ai times every cue against the audio, keeping your cuts.
5. **After the realign** (step 10): join quick exchanges into `-甲⏎-乙` cues, and, in a hand-made
   draft, fix the particles with the fine-tuned recogniser's help.

The report then holds only what the reviewer must look at: the text edits as compact rows they
can undo, added and removed lines, and the few queries you could not settle. Re-cuts are not in
it. A full proofread with audio evidence comes after, and only if the user asked ("Full pass").

`ccp status <id>` shows `machine_draft`, then `cleanup`, `segmentation` and `joins` as the pass goes.
A hand-made file is in the cleanup from your first `ccp clean` on it.

## Commands

- `uv run ccp locate <show> E01` · `uv run ccp status <id>`: find the file; what the workspace holds
- `uv run ccp copy-draft <id>`: edits go into a new file, not the source (before any edit)
- `uv run ccp reference <id>` (`--ocr`: ask first): the reference subtitle
- `uv run ccp clean <id> --lint --dry-run` · `--skip-lint <cue>`: mechanical lint fixes
- `uv run ccp render <id> --from 1 --to 25` · `--only missing` · `--only seg`: the draft with `R`, `L`, `+R`, `S` and `P` lines
- `uv run ccp clean <id> --edits <file>`: text edits, removals (`N|-|reason`), queries (`N|?|reason`)
- `uv run ccp missing <id>` · `uv run ccp listen <id> --missing 57` · `uv run ccp flag add <id> --missing 57 ...`: missing lines
- `uv run ccp segment <id> --edits <file>` · `--dry-run`: re-cut cues (before the realign), join quick exchanges (after it)
- `uv run ccp pipeline <id> realign --mode adjust --input draft`: time it all (GPU, minutes)
- `uv run ccp particles model <id>`: the fine-tuned recogniser's particle comparison (GPU, a minute)

## Steps

1. **Locate, settle the output and where it goes** (`proofread-subtitles` steps 1–2,
   including confirming media found by name). For a library file the user wants kept as it
   is, run `ccp copy-draft` now.
2. **Reference.** `ccp reference <id>`: with a reference this pass fixes far more, and missing
   lines can only be found with one. Note its `label`. If it answers `needs_decision`, ask the
   user its `ask_the_user` question as it is, recommend no option, and run the matching command
   from `answers`.
3. **Glossary.** `ccp status <id>` shows `glossary` (`path`, `exists`); read it with your
   file-reading tool if it exists, without checking for it in the shell. At the end you add to it
   (`proofread-subtitles` step 8): take the names from the reference and your fixes, never
   from the draft's own spellings.
4. **Mechanical fixes.** `ccp clean <id> --lint --dry-run` lists the spelling-variant, glossary
   and punctuation fixes. Add `--skip-lint <cue>` where one would be wrong (a variant inside a
   name, a quotation or a longer word), then run it without `--dry-run`.
5. **Line by line**, in windows of **about 25 cues** (`ccp render <id> --from N --to M`). Go
   through every cue with the checklist below ("Each cue"): in a messy file nearly every line
   needs something, and a large window hides it. Write the edits to a UTF-8 file and apply
   them with `ccp clean <id> --edits <file>`:

   ```
   12|艾倫，快啲走|name: the reference and the glossary write 艾倫; 愛倫 is a mishearing
   40|佢實囉囉攣|食多都亂 makes no sense; R 一定坐立不安 = 實 + 囉囉攣 (sat6 lo1 lo1 lyun1)
   44|得返一單sentence|standard: English mid-line is lower case
   45|係喇，擺返埋先啊，唔好唔見|punctuation: a comma after each particle before more words
   46|-|a lone 吖 with nothing to say: interjections are not subtitled on their own
   57|?|meaning unclear: R says 他已經走了 but nothing in the draft sounds like it
   ```

   - `N|complete new text|reason`; `N|-|reason` takes the cue out; `N|?|reason` records a query.
     The **reason is required**. It may start with a category (`name:`, `standard:`,
     `punctuation:`, `missing:`, `extra:`). `⏎` is a line break inside a cue.
   - Edits are applied at once and recorded, so the next window sees the cleaned text and the
     user can undo any of them from the report. A removal renumbers the cues after it: render
     the next window fresh.
   - Read the output: `held_back` (add reasons and resubmit), `particles_kept` (see
     "Particles"), `particles_read_as_words`.
   - Note the `+R` and `S` lines as you go, but leave them for steps 7 and 8.
6. **Check.** `ccp clean <id> --lint --dry-run` once more (its output also counts the convention
   problems left); fix what is left with another `ccp clean`.
7. **Missing lines** (below). Needs a reference and cantocaptions-ai (`tools.audio_evidence`);
   without either, skip it and say so in the summary.
8. **Splitting** (below), over the whole file.
9. **Realign.** `uv run ccp pipeline <id> realign --mode adjust --input draft`, run in the
   background. It times every cue against the audio and keeps your cuts (its output `notes`
   says so). Every record so far is carried onto the new draft (`records_carried`). Without
   cantocaptions-ai, skip steps 9 and 10 and say the timing was not checked.
10. **After the realign** (below): joins, then particles.
11. **Finish or continue** (below).

## Each cue (step 5)

Follow AGENTS.md "How to decide a line"; the reference decides the meaning. For every cue:

- **Wording.** Does it mean what `R` and the scene say? A mishearing the meaning gives away is
  a fix (a Cantonese phrase that sounds like the draft and says what `R` says:
  `investigate-line/references/sound-alikes.md`); if none comes to mind at once, a query. Word
  order and fixed expressions too: 兩日mandate咁就冇咗 → 兩日mandate就噉冇咗.
- **Standards** (`cantocaptions-standards`): Standard Written Chinese where Cantonese was said,
  variants lint missed, names per the glossary and the reference.
- **English**: lower case mid-line unless a name or a title (`L latin_case`: 得返一單Sentence →
  得返一單sentence); all capitals only for an acronym (COURT → Court).
- **Punctuation**: a comma after a particle before more words (`L particle_comma`: 係喇擺返埋先
  → 係喇，擺返埋先), except before 你; a comma after an opening 嗱 (`L lead_comma`: 嗱，你睇下);
  `？` on questions; no full stop at the end; one `…`.
- **Quotes**: a passage read aloud over many cues does not put every line in 「」
  (`L quoted_run`): take them off. Short quotations inside a line keep theirs.
- **Interjections**: a cue that is only 吖, 嗬, 哦, 啊… (`L lone_interjection`) is taken out
  (`N|-|reason`), unless it means something here (嗯 agreeing, 吓？ asking). One at the start or end
  of a longer line follows the style guide's rules for hesitations.
- **Particles: not yet.** Leave every sentence-final particle as it is in this step, even a
  wrong-looking one; they are decided after the realign, with the recogniser's help (step 10).

Decide what you can. Record a query only for a line you really cannot settle: the reviewer
should see as few as possible.

## Particles

Before the realign the cleanup changes no sentence-final particle; `ccp clean` puts the draft's
back and lists it in `particles_kept`. These are **standard particles, not variants or typos**;
never "normalise" them:
- 𠸏 ge2 (surprise, realisation, a soft question: `點解出面咁嘈𠸏？`) is not 嘅 ge3;
- 嘎 gaa4 (㗎 as a question: `乜你唔keep嘎？`) is not 㗎 gaa3;
- 𠿪 gaa2, 𠺢 gaa1 (in 𠺢嘛), 𠺝 gaak3, 𡁜 wo5, 𡅅 aak3, 𠻺 aa6 and 𠻹 tim1 are distinct particles too;
- 囖 lo1 and 囉 lo4 differ in tone and meaning: the standard writes 囖 for lo1 (咪係囖) even
  where messy files write 囉 (`cantocaptions-standards` → `references/conventions.md`).

After the realign, in a **hand-made** draft (`machine_draft: false`), the particles get their
own pass (step 10). In a machine-made draft they stay: the recogniser that would judge them
wrote them. A particle character that was really a misheard word (爛嘅 for 爛gag) may be replaced
by the word at any time; the tool applies it and lists it in `particles_read_as_words`.

## Missing lines (step 7)

`ccp missing <id>` lists every reference line no cue covers, as `+R#N` with the cues before and
after it (the same lines appear in `ccp render`). Measured over 14 episodes, only about a third
of the unbracketed ones are really missing lines; the rest are songs the subtitles leave out
(the commonest), and reference lines timed a little off whose words a neighbouring cue already
has. So, for each one, in this order:

1. **On-screen text** (`kind: on-screen text`, a line in brackets: a sign, a caption): add it
   only if the subtitles show on-screen text elsewhere, copied as the reference writes it, in
   （）. Record it with `--grade fix`; no listening needed. Otherwise leave it.
2. **Already there?** Read the neighbouring cues: if one of them says what the line means (the
   reference is mistimed, or merged two lines the draft has as one), it is not missing.
3. **A song, or nothing to subtitle?** A run of reference lines with no cues, at the opening or
   ending or over music, whose wording is lyrics, is a song the subtitles leave out: skip it,
   unless the file subtitles songs elsewhere. A grunt or a cry is not subtitled either.
4. **Listen.** For the rest, `ccp listen <id> --missing N` (several `--missing` in one call). It
   hears the span four ways: close, close with the voices isolated, wider (may include the
   neighbours), and with the reference as a hint (helps the recognisers find the words; it can
   also make them recite the reference, so it never confirms anything).
5. **Write the line.** From everything heard, the reference's meaning and the neighbours, write
   what was said: written Cantonese to the conventions, never the reference's wording, nothing
   that belongs to the neighbouring cues. Your line, written from all of them, is right more
   often than any single hearing (measured: about 6 times in 10, against a little under half for the best one).
6. **Record it**, with the reason and a `reference:` line:

   ```
   uv run ccp flag add <id> --missing 57 --category missing --grade fix \
     --proposed "你去邊度啊？" \
     --reason "the draft has no line here; both recognisers hear 你去邊度啊 in the pause, and the reference asks where he is going" \
     --evidence "reference: 你去哪裏 = 你去邊度" --evidence "listen: both recognisers, close: 你去邊度啊"
   ```

   The grade is checked against the close hearings (plain and isolated; extra words around
   your line, such as the start of the next one, do not count against it), as measured:
   **fix** when both recognisers heard your line (right 86% of the time), **suggest** when only
   the fine-tuned one did (67%), otherwise **query** with your line and any other candidate as
   `--alt` (about 30%: the reviewer listens). `ccp flag add` refuses a higher grade and says
   which it allows. A fix or suggest goes into the draft at once, at the reference line's place;
   the realign moves it onto the speech. A query adds nothing until the reviewer picks a
   candidate.

Several at once: a JSON list for `ccp flag add --json-file` with `"missing": N` instead of
`"cue"`. Do not record anything for the reference lines you skip.

## Splitting (step 8)

Before the realign, re-cut wherever a viewer would stumble. **One line per cue is much better
than two**, so the work is mostly splitting. Ignore how short a cue is here: in a messy file
cues look short because the transcriber padded them too tightly, and the realign fixes that.

```
30|佢話今晚會嚟， // 叫我哋唔使等|3.9 s holding two clauses with a pause at the comma
41-42|佢哋個學校好遠|學|校 was cut in two across 41 and 42
57|你去邊啊？ // 我去學校|two speakers in one cue: one cue each
63|噉但你哋唔使擔心 // 我哋已經準備好晒喇|too long for one line: two cues, not a line break
```

`N` or `N-M` is the range of cues replaced (numbers as `ccp render` shows them now), ` // `
separates the new cues, and the reason is required. Write them to a file and run
`ccp segment <id> --edits <file>` (`--dry-run` first).
- **The words stay exactly as they are**: only punctuation, line breaks and speaker dashes may
  change. Fix wording with `ccp clean` first. A comma left at the end of a cue is dropped for you.
- **Split** a cue holding two sentences or clauses with a pause between them, and every cue
  holding two speakers (`S two speakers in one cue`), even a short one: each speaker gets a cue
  here, and the quick exchanges are joined again after the realign.
- **Long lines become two cues, not two lines.** Split at a comma, a clause or a pause so each
  piece reads on its own. A line break is only for a single clause too long for one line with
  nowhere to split it; `ccp segment` refuses a break where the text fits on one line.
- **Never cut inside a word** (`S cut inside a word`): move the cut to the word's edge.
- **Do not join** two speakers into one cue here; `ccp segment` refuses it.
- Each line at most 17.5 characters wide (the tool checks).
- Cue numbers change after each `ccp segment` call: render the next window fresh.

## After the realign (step 10)

1. **Joins.** `ccp render <id> --only seg` lists the `S quick exchange` hints: two lines that
   start under 0.75 s apart (0.65 s when both are short), too quick to read one after the other.
   Where a different speaker says the second, join them: `ccp segment <id> --edits <file>` with
   lines like `88-89|-唔該晒⏎-Thank you|two speakers, the second answering at once`. The tool
   refuses any other re-cut after the realign, and any join that is not that quick. The joined
   cue keeps the realign's times.
2. **Particles** (hand-made drafts only). `ccp particles model <id>` (GPU, about a minute)
   scores every particle with the fine-tuned recogniser, which was trained on CantoCaptions
   and hears particles far better than a messy file was written. Then read the file again in
   windows of about 40 cues: `P` lines show where it clearly prefers, or leans to, another
   particle (`P the fine-tuned recogniser clearly prefers 吖 over 啊`). For each, ask what the
   line does in its scene (`cantocaptions-standards`, `particle-usage.md`); where the
   recogniser's particle fits it, fix it with `ccp clean` (`45|係喇，擺返埋先吖，唔好唔見|particle:
   a request to put it back: 吖 aa1`). `ccp clean` accepts a particle change only where the
   recogniser backs it (`particles_changed`); others are put back (`particles_kept`). A
   particle the scene clearly needs that the recogniser does not back: a query, at most a few.

## Finish or continue

Report, export or publish as the request says
(`proofread-subtitles/references/report-and-apply.md`). In the report the text edits are
compact rows the user can undo or reword; added and removed lines can be undone. Summarise:
text edits by category, particles changed, lines added (by grade) and removed, how many cues
were re-cut and joined, and the queries left open. Say what the pass used (text and reference;
audio for the missing lines and the particles; the realign for the timing), and that a full
proofread with audio evidence is available. Before the report, update the glossary
(`proofread-subtitles` step 8), and say in the summary how many names it gained. Pass on the
report's `about_this_proofread` lines as they are (`proofread-subtitles` step 9).

**Full pass** (the user asked for a full or thorough proofread, or finished quality). It needs
cantocaptions-ai: with `tools.audio_evidence: false` in `ccp status`, tell the user the cleanup
is as far as this machine goes, and offer a text-only proofread (`proofread-subtitles`, "Without
audio") instead. Continue with `proofread-subtitles` from step 4 (Evidence) on the realigned
draft, at full effort. Evidence runs only the independent recogniser on a machine-made draft,
because its text came from the fine-tuned one.
