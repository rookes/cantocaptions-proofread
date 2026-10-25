---
name: review-particles
description: Review only the sentence-final particles of a CantoCaptions subtitle file (喇/啦/囖, 啊/吖/呀, 㗎/嘎, 啫/唧, 喎/啝 …) and fix the ones that are clearly wrong for what the line does. Weighs the standards' usage notes, the fine-tuned recogniser's comparison of the alternatives, strict-corpus and recorded collocations, and words.hk examples, and records new collocations for future runs. Use when the user asks to check, review or fix the particles of an episode or file, or for a particle pass after a cleanup.
---

# Review the particles

A particle-only pass: every clause-final particle of the file is checked, and nothing else is
changed. Each decision still follows AGENTS.md ("How to decide a line") and records like
`investigate-line` ("Grades", "Recording").

## Commands

- `uv run ccp particles scan <id> --save` · `--only-suspects` · `--from N --to M`: every clause-final particle with what each source says; `?` marks a suspect and its reasons
- `uv run ccp particles model <id>` · `--cue N ...`: (GPU) the fine-tuned recogniser's comparison of each particle with its alternatives (`ccp evidence` also does this)
- `uv run ccp particles explain 喇` · `explain 㗎喇` · `explain laa3`: the standards' usage notes, words.hk senses with examples, the phrases that pull toward it in strict subtitles, recorded collocations
- `uv run ccp particles colloc "一定" --among laa` · `"(就得|就好)$" --among "喇|啦"` · `--top 啦 --vs 喇`: how strict subtitles and words.hk examples end clauses with a phrase; what most favours one particle over another
- `uv run ccp particles note add --trigger "..." --among ... --prefer ... --note "..." --example "<id>#<cue>  <text>" --id <id>` · `note list --proposed`: record a collocation for future runs
- `uv run ccp cue <id> 9 11 24`: a suspect in its scene (the reference, the neighbouring cues)
- `uv run ccp flag add/keep <id> ...`: record decisions (`investigate-line` → Recording)

## Steps

1. **Locate, output, reference:** `proofread-subtitles` steps 1–3 (confirm media found by
   name; settle report or edits, and where they go; get the reference).
2. **The recogniser's comparison.** `ccp status <id>`: with no `evidence` yet, `ccp evidence <id>`
   (it scores the particles too); with evidence but no `particle_scores`, `ccp particles model
   <id>`. Without audio (`tools.audio_evidence: false` or no media) skip this: the scan still
   works, without its model lines; say in the summary that the audio was not checked.
3. **The standards.** Read `cantocaptions-standards/references/particle-usage.md` whole, once:
   it explains how the problem particles are used, the near pairs (喇/啦, 啊/吖/呀, 啫/唧),
   question particles and set phrases. For a particle it does not cover, `ccp particles explain`
   gives the one-line meaning from the conventions and words.hk's senses.
4. **Scan.** `ccp particles scan <id> --save`, then read `work/<id>/particles.txt` with your
   file-reading tool from first slot to last. Note the `?` slots, and any slot your own reading
   of the scene doubts. Do not decide yet: a later cue often shows what an earlier line did.
5. **Decide each suspect,** meaning first:
   - **What does the line do?** States a new fact or a change, warns, decides, proposes,
     reminds the listener of what they should know, asks, lists… Read `R` and the neighbouring
     cues (`ccp cue`). Which usage in `particle-usage.md` fits that, and which particle has it?
   - **Is the draft's particle a natural way to say it?** Many lines take either of a near
     pair (你都係快啲走喇 / 啦, 好啦 / 好喇). If the draft's particle is a natural reading of
     the scene, it stands (AGENTS.md principle 3): record a keep.
   - **Only then the signals:** the fine-tuned recogniser's comparison (scan line `model:`),
     recorded collocations (`recorded`), strict-subtitle tendencies (`strict:`), and words.hk
     examples (`ccp particles colloc`). The recognisers' own particles (`recognisers wrote`) are
     no evidence (AGENTS.md principle 4).
   - **Grade:**
     - `fix`: the usage clearly fits the proposed particle and not the draft's, **and** an
       independent signal backs it, and nothing clearly points the other way. The strong
       signal is the recogniser *clearly* preferring the proposed particle. A collocation backs
       a fix only when it is a recorded one, or one the strict subtitles follow almost without
       exception, and only if the recogniser does not hear the draft's particle (a `model:` line
       agreeing with the draft outweighs a tendency). Evidence: a `guide:` line naming the
       usage, and `particle_model:`, `colloc:` or `corpus:`. `ccp flag add` refuses a particle
       fix without both.
     - `suggest`: the usage fits, but the support is only a lean or a tendency. A preference
       between 吖 and 啊, or 嘅 and 㗎, is never more than a lean: the recogniser tells those
       apart poorly.
     - `query`: the scene allows either, or the signals conflict; give the particles as `--alt`.
     - `keep`: a `?` slot you checked and found right.
   - On a machine-made draft (`machine_draft: true`) the fine-tuned recogniser wrote the draft:
     its comparison is not independent and never backs a fix there (the scan says so).
   - A particle written with the wrong character for its reading (an `L` line) is a convention
     fix with a `lint:` evidence line; it needs no other signal.
6. **Proportion.** In a `strict` file almost every particle is right. If your fixes pass a
   handful per episode, you are probably following tendencies rather than the scene: re-read
   step 5.
7. **Record collocations.** When a phrase decided a line, and generalises beyond this scene
   (一定…, 已經…, 咪…囖, a set phrase), check `ccp particles colloc "<phrase>" --among <set>`. If no
   recorded entry covers it and the strict subtitles or words.hk examples bear it out, record it:
   ```
   uv run ccp particles note add --id <id> --trigger "梗係" --among laa --prefer 啦 \
     --note "梗係… states the obvious, which is 啦 laa1 (particle-usage: 啦 laa1, Usage 2)" \
     --example "<id>#212  梗係唔係啦"
   ```
   The trigger is a regex over the clause before the particle (`$` = right before it); `among`
   is a set (`laa`, `aa`, `gaa`, `ze`, `wo`, `le`) or the competing particles separated by `|`;
   leave out `--prefer` when the choice depends on meaning, and say how in `--note`. Entries are
   `proposed` until the user confirms them; the scan uses them at once. Never edit
   `particles/collocations.toml` yourself.
8. **Output:** `proofread-subtitles` step 9 (`references/report-and-apply.md`). Summarise the
   particle records by grade, the most important fixes in one line each, the collocations you
   recorded, and anything else you noticed in passing (other errors are out of scope here:
   name them in one line each; the user can ask for a full proofread).

## Writing reasons

Name the usage and the sounds, in plain words: "喇 laa3 announces a change (返嚟 'I'm back');
啦 laa1 would propose coming back, which the scene does not do". Quote the signals the way the
scan words them: "the fine-tuned recogniser clearly prefers 喇 here", "strict subtitles end
已經… with 喇 almost always". No numbers, no tool names.
