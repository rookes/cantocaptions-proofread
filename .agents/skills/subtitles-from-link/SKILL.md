---
name: subtitles-from-link
description: Make proofread written-Cantonese subtitles for a video given by link (YouTube or any site yt-dlp supports). Downloads the audio and any existing subtitles as references, transcribes with cantocaptions-ai, cleans the ASR draft against the references (and, on request, realigns it and proofreads it against the audio), and returns the final subtitles together with the original ASR, the references and a review report. Use when the user gives a video URL and asks for subtitles, a transcript or captions.
---

# Subtitles from a link

The user gives a link and wants finished written-Cantonese subtitles back. You download what
is needed, transcribe it, clean the ASR draft, and hand back a folder that keeps every
stage: the original ASR, the reference subtitles, the final subtitles, and a report the user
can review.

## Steps

1. **Fetch.** `uv run ccp fetch <url>`. This downloads the audio only (never the video) into
   the workspace `yt-<video id>`, plus the video's own subtitles as references, best first:
   - manual written Cantonese (yue);
   - Traditional or HK Chinese;
   - other Chinese;
   - English;
   - the site's automatic captions in the video's own language, only as a last resort.

   Machine translations are never downloaded. Tell the user the title, the length and which
   reference was chosen (or that there is none). If yt-dlp fails (private, region-locked or
   age-restricted video, a site change), report its message. Do not try other download tools.
2. **Transcribe.** `uv run ccp pipeline <id> transcribe`, run as a long-running (background)
   command. It uses the user's cantocaptions-ai settings and takes a few minutes for a short
   video. The ASR output becomes the working draft, and the untouched original is kept.
3. **Clean.** The ASR draft is machine output: follow the `clean-draft` skill (text only, no
   evidence). Read `ccp status <id>` → `reference.label` first:
   - A *written Cantonese* reference (the video's own Cantonese captions) is a human
     transcript. Where it differs from the draft in content, it is usually right: take its
     words, written to the CantoCaptions standard, but keep the draft's particles.
   - A *Standard Chinese* or *English* reference is evidence for meaning, and the Chinese one
     is authoritative for names, as usual.
   - Automatic captions are weak and machine-made: use them only as a hint, never as the
     source of an edit.
4. **Full pass, only if the user asked** for a thorough or full proofread, or finished
   quality: realign the cleaned draft and proofread it with audio evidence, as described in
   `clean-draft` → "Full pass". Particle flags and queries stay unapplied for the user to judge.
   After the full pass, apply your corrections with
   `uv run ccp apply <id> --min-severity suggested --min-confidence medium`. The draft is a
   workspace copy and the original ASR is kept, so this is safe without asking. Retimes and
   splits only if the user asked (see the proofread skill). Queries stay unapplied either way.
5. **Report and export.** `uv run ccp report <id>`, then `uv run ccp export <id>`. Give the user:
   - the path of the final subtitles (`<title>.yue.srt`);
   - the folder, which also holds `<title>.asr.yue.srt` (the original ASR),
     `<title>.reference.<lang>.srt` for each reference, `report.html` and `summary.json`;
   - a short summary: cue count, corrections applied by kind (cleanup and, if run, the full
     pass), and what is left open for them to judge. If you did only the cleanup, say that a
     full pass (realign + proofread against the audio) is available.

   If the user did not ask to review the report, finish with `uv run ccp prune <id>`. It frees
   the stored aligner output and debug files, and the report's audio clips; the subtitles,
   references and summary stay. If they may review, prune after their decisions are applied
   and exported. `--downloads` also deletes the downloaded audio, so only use it when the user
   is completely done with the video.

## If the user wants to review

The report (`report.html` in the export folder or the workspace) lists the cleanup edits as
compact rows (**Undo**, or **Use my text** after editing the box) and every other flag as a
card with an audio clip. On a card for a correction you already applied, **Reject** undoes it
and **Accept** with edited text replaces it with the user's wording. Open flags can be accepted
or rejected as usual. When the user gives you the exported `decisions.json`:
1. `uv run ccp apply <id> --decisions <path>`
2. `uv run ccp report <id>`, then `uv run ccp export <id>` again (it overwrites the folder with the
   current state)
3. tell them what changed.

## Boundaries

- Download only what the user linked. Do not fetch playlists, channels or related videos.
- Keep everything in the workspace and the export folder. Do not copy downloads elsewhere
  unless asked (`ccp export <id> --to <folder>` writes the bundle to a folder of the user's
  choosing).
- Nothing here goes into CantoCaptions. If the user wants the result added to the library,
  ask where it should go first.
