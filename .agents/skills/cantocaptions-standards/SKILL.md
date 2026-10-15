---
name: cantocaptions-standards
description: The CantoCaptions conventions for written Cantonese subtitles. Covers which character to use for each sentence-final particle (by syllable and tone) and what each particle means, compound particles, interjections, affixes (噉/咁, 下, 晒…), pronouns, required Hong Kong character variants and spellings (畀 not 俾, 而家 not 宜家…), punctuation and formatting rules, and optional recommended characters. Use whenever you need to know how something must be written in a CantoCaptions subtitle, or to judge whether a line breaks a convention.
---

# CantoCaptions conventions

CantoCaptions subtitles write spoken Cantonese the way a careful native writer would, with
a fixed set of conventions so learners can rely on them. The most distinctive rule: **each
sentence-final particle character stands for exactly one syllable and tone**, so the
character must match what the speaker said.

## Where to look

- `references/conventions.md`: Which particle character for a reading; what a particle means; compounds; interjections; affixes; pronouns; mandatory variants and spellings
- `references/style-guide.md`: Punctuation, formatting, line length, timing, multi-speaker lines, brackets, what is left untranscribed
- `references/optional-characters.md`: Recommended but optional characters (disambiguation, consistency, loanwords)

Each file is short (7–10k characters). Read the one you need whole with your file-reading
tool, once per pass; it stays in context, so look things up there afterwards. Never search
them with a shell command (`Select-String`, `grep`, `findstr`): each one needs the user's
approval. For one particle, `uv run ccp dict <particle>` is quicker.

These files are generated from the CantoCaptions README and the cantocaptions-ai language
pack by `scripts/build_standards.py`. If they look out of date, tell the user. Do not edit
them.

## Rules of thumb

1. **Order of authority:** the mandatory conventions (`conventions.md`, the style guide), then
   words.hk for any word they do not cover (`uv run ccp dict WORD`), then the majority usage in
   strict-tier subtitles (`uv run ccp corpus`). Optional characters are recommendations: do
   not flag a file for not following them.
2. **Particles by sound, not by habit.** When a particle is in question (AGENTS.md principle
   4 says when), establish its syllable and tone from meaning and context (see the notes in
   `conventions.md`), then take the character from the grid. `uv run ccp dict <particle>` shows words.hk's usage notes for that
   reading. words.hk often writes particles with other characters, so it is matched by
   Jyutping. Some pairs to keep apart: 啦 laa1 / 喇 laa3 / 嘞 laak3; 囖 lo1 / 咯 lo3 / 囉 lo4;
   㗎 gaa3 / 𠿪 gaa2 / 嘎 gaa4; 𠸏 ge2 / 嘅 ge3; 喎 wo3 / 𡁜 wo5; 吖 aa1 / 啊 aa3 / 呀 aa4.
3. **噉 vs 咁 are different words, and they sound different.** 噉 (gam2) is "like this / in
   this way / so (manner)" and appears in 噉樣, 係噉, 噉就; 咁 (gam3) is "so (degree)" and appears in
   咁多, 咁耐, 咁靚. The same goes for 邊 bin1 / 便 bin6 (裏邊 / 裏便) and 着 zoek / 著 zyu3. Decide by
   tone and meaning. The fine-tuned recogniser follows these conventions, so its 噉/咁 is
   evidence. Stock Qwen writes 咁, 邊 and 著 regardless of what was said, so its spelling of
   them is not evidence.
4. **Variants are 1:1.** For the characters in the variant table, the selected form is always
   used (説 not 說, 裏 not 裡, 牀 not 床, 揾 not 搵, 為 not 爲, 衞 not 衛 …).
5. **Punctuation:** no `。` anywhere and no full stop at the end of a cue; a single `…` (never
   `……` or `...`); `，` after every sentence-final particle unless 你 follows without a pause;
   `？` for questions (including both halves of a split 定係 question); `！` sparingly;
   two speakers in one cue as two lines, each starting with `-` and no space; `《》` for titles,
   `［］` for episode titles, `（）` for written or background information, `【】` for on-screen
   text and before foreign speech (`【日語】`), `「」` when written text is read aloud; no
   middle dot, no italics; `{\an8}` for overlapping background speech.
6. **Line length:** at most 17.5 display characters per line (a full-width character counts 1,
   a half-width character 0.5).
7. **Pronouns:** 佢, 你, 他 (as in 其他), and never 她, 妳, 您, 祢 or 姖.
8. **English** inside Cantonese keeps English spelling and casing: lower case mid-line
   (`開完meeting`), capitalised only at the start of a line.
