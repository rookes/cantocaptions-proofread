# How Cantonese gets misheard

Jyutping describes Cantonese sound precisely, so it is the best tool for finding what a
misheard span really was. A syllable has an **initial** (b, p, m, f, d, t, n, l, g, k, ng, h,
gw, kw, w, z, c, s, j, or none), a **final** (aa, aai, aau, aam, aan, aang, aap, aat, aak, a, ai,
au, am, an, ang, ap, at, ak, e, ei, eng, ek, i, iu, im, in, ing, ip, it, ik, o, oi, ou, on, ong, ot,
ok, u, ui, un, ung, ut, uk, oe, eoi, eon, oeng, eot, oek, yu, yun, yut, and syllabic m / ng), and a
**tone** (1–6).

## The most important pattern: tones survive

**A misheard span usually keeps its tones even when initials and finals are wrong.** In the worked
example, 食多都亂 (sik6 do1 dou1 lyun1) was really 實囉囉攣 (sat6 lo1 lo1 lyun1): every tone matched.
So when you generate candidates, try tone-preserving ones first, and remember that a character
can have several readings (亂 lyun6/lyun2, and in speech lyun1). `ccp jp --all` lists them.

## Common confusions (maintainer's list)

**Initials**
- `n` ↔ `l`, nearly interchangeable (擰 ning6 sounds like 令 ling6). Many speakers merge them.
- `ng` ↔ no initial (我 ngo5 / o5; 愛 oi3 / ngoi3).
- `c` ↔ `z` ↔ `s` can be misheard for one another.
- `d` ↔ `t`
- `m` ↔ `n`
- Also common in fast or lazy speech: `gw` → `g` (廣 gwong2 → 講 gong2), `kw` → `k`.

**Finals**
- `a` ↔ `aa` (often interchanged: am/aam, ak/aak, an/aan).
- `ok` ↔ `o` ↔ `ou`
- `yu` ↔ `yun`
- `ik` ↔ `ek` ↔ `ak` ↔ `at` ↔ `eot`
- `ip` ↔ `it`
- `ak` ↔ `ap` ↔ `at`, and `aak` ↔ `aap` ↔ `aat` (the stop codas p/t/k blur).
- `n` ↔ `ng` codas merge in many speakers (an/ang, on/ong: 趕 gon2 / 講 gong2).

**Tones**
- Tone 1 (high level) is usually clear. It is occasionally mistaken for tone 3.
- Tone 3 ↔ tone 6 are very often mixed up.
- Tone 2 is distinctive but may be mistaken for 4 or 5.
- Tone 5 may be mistaken for 2 or 6.
- Tone 4 may be mistaken for 2 or 6.

These are encoded as costs in `config/confusions.toml`, which `ccp sounds-like` and
`ccp jp --vs` use.

## Measured: how the recognisers mishear

`scripts/measure_confusions.py` aligns each recogniser's text with strict-tier subtitles and
tallies one-syllable substitutions (see the table below for the episodes used). This is how
*machines* mishear, which overlaps with, but is not the same as, how human transcribers mishear.
Use it as a second opinion on which confusions are common.

Measured 2026-10-11 on three strict-tier episodes (Attack on Titan S1E03, Re:Zero S1E01, The Greed
of Man E01): 30,192 matched characters, 1,092 one-syllable substitutions by the two recognisers,
and 436 homophone swaps (same sound, different character). Counts include both recognisers
and some alignment noise, so read them as a ranking, not as rates.

What agrees with the maintainer's list: n/l is by far the commonest initial confusion; c/z/s
and ng/∅ are common; o/ou and a/aa (aau/au) top the finals; tone 3/6 is the commonest tone
confusion. What it adds: tone 1/3 is nearly as common as 3/6; 5/6, 2/5, 2/6 and 4/6 all occur
often; dropped h (h/∅) and k/ng codas (ik/ing) are common.

**Initials** (523 changes)

| pair | count |
|---|---|
| l ↔ n | 51 |
| d ↔ z | 33 |
| s ↔ z | 21 |
| h ↔ ∅ | 20 |
| j ↔ z | 15 |
| c ↔ z | 13 |
| h ↔ l | 12 |
| b ↔ f | 12 |
| ng ↔ w | 11 |
| d ↔ n | 9 |
| g ↔ ng | 9 |
| d ↔ t | 9 |

**Finals** (732 changes)

| pair | count |
|---|---|
| o ↔ ou | 30 |
| aau ↔ au | 20 |
| ik ↔ ing | 13 |
| au ↔ ou | 12 |
| ou ↔ ung | 12 |
| i ↔ in | 12 |
| ei ↔ eoi | 11 |
| ai ↔ ei | 10 |
| i ↔ ik | 10 |
| aai ↔ ai | 10 |
| an ↔ ang | 9 |
| ai ↔ eoi | 9 |

**Tones** (647 changes)

| pair | count |
|---|---|
| 3 ↔ 6 | 93 |
| 1 ↔ 3 | 83 |
| 5 ↔ 6 | 68 |
| 2 ↔ 5 | 60 |
| 2 ↔ 6 | 56 |
| 4 ↔ 6 | 56 |
| 4 ↔ 5 | 35 |
| 1 ↔ 6 | 35 |
| 2 ↔ 3 | 35 |
| 1 ↔ 2 | 33 |
| 1 ↔ 5 | 25 |
| 3 ↔ 5 | 22 |

**Most common syllable mishearings (truth, heard)** (1092 changes)

| pair | count |
|---|---|
| 昴 maau5 ↔ 茂 mau6 | 12 |
| 係 hai6 ↔ 喺 hai2 | 11 |
| 嚟 lei4 ↔ 你 nei5 | 10 |
| 就 zau6 ↔ 走 zau2 | 8 |
| 上 soeng6 ↔ 相 soeng3 | 8 |
| 嗰 go2 ↔ 我 ngo5 | 7 |
| 𡃁 leng1 ↔ 靚 leng3 | 6 |
| 你 nei5 ↔ 嚟 lei4 | 6 |
| 去 heoi3 ↔ 佢 heoi5 | 6 |
| 係 hai6 ↔ 哎 ai1 | 5 |
| 只 zi2 ↔ 隻 zek3 | 5 |
| 玲 ling4 ↔ 力 lik6 | 5 |

**Homophone swaps (spelling, not hearing)** (436 changes)

| pair | count |
|---|---|
| 返 ↔ 翻 | 62 |
| 晒 ↔ 曬 | 32 |
| 緹 ↔ 提 | 13 |
| 竇 ↔ 豆 | 13 |
| 菲 ↔ 飛 | 11 |
| 魯 ↔ 老 | 8 |
| 莎 ↔ 沙 | 8 |
| 郁 ↔ 喐 | 8 |
| 賊 ↔ 拆 | 8 |
| 佬 ↔ 路 | 8 |
| 贓 ↔ 裝 | 7 |
| 帕 ↔ 柏 | 6 |
| 復 ↔ 服 | 6 |
| 牲 ↔ 生 | 5 |
| 過 ↔ 個 | 5 |

## Using this

1. Romanize the doubtful span and every hypothesis (`ccp jp TEXT --all`).
2. For each syllable, ask which nearby sounds it could have been, using the lists above.
   Keep the tone first, then vary the initial, then the final.
3. Let `ccp sounds-like` do the dictionary search, and judge its candidates by meaning.
4. A fix that sounds nothing like the draft (a different syllable count, all tones changed)
   needs strong independent support, such as both recognisers hearing it, and must still
   mean what the reference means. Recognisers hearing a sound-alike whose meaning differs
   from the reference is a shared mishearing, not a correction.
