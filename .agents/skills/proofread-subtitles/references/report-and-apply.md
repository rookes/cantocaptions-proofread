# Output: report, edits, and where the result goes

This is the one place for the output step; `clean-draft`, `prepare-draft` and
`subtitles-from-link` point here.

## Where the result goes

Decide before applying anything, from the user's request:
- **Correct the file itself** (the default): `ccp apply` edits the working draft in place.
- **"Put the edits in a new file"**, or any target other than the source: run
  `uv run ccp copy-draft <id>` *before* any edit. Edits then go into a workspace copy. When
  finished, write it out with `uv run ccp publish <id> --to-main` (the show's folder in the main
  library area, with a library-style name; needs the library) or `uv run ccp publish <id> --to <file or folder>`.
  Run it with `--dry-run` first and report the target. A request that names the destination is
  the user's go-ahead to publish there. Never overwrite an existing file unless the user says so
  (`--overwrite`). If `publish` returns a `warning`, pass it on word for word.
- A link job hands back a folder instead: `uv run ccp export <id>` (see `subtitles-from-link`).

## The report

`uv run ccp report <id>` writes `work/<id>/report.html`, with an audio clip (cue ± 1 s) for every
record (`--video` for 480p video clips). It opens from disk. Sections: Fixes, Suggestions,
Queries, Cleanup pass (compact rows), and a collapsed "Checked and kept". Each card shows the
draft and proposal with the changes marked, the **Reason**, the reference line, both ASR lines,
the neighbouring cues and the evidence. The reviewer accepts (optionally editing the text) or
rejects each one, then **Export decisions** downloads `decisions.json`. Tell the user the path
and that they can hand that file back to you. If the output reports failed clips, say so and
quote `first_error`.

## Applying

Only when the user asked for edits:
1. **From the reviewer's decisions** (preferred): `uv run ccp apply <id> --decisions <path>`.
   It applies exactly the accepted records with the reviewer's text, undoes rejected
   corrections that were already applied, and re-words those the reviewer edited.
2. **Directly**, when the user asked for that: `uv run ccp apply <id>` applies every `fix`;
   `--include-suggest` adds the `suggest` records (only if the user asked for everything you
   are fairly sure of). Queries, keeps and particle records are never applied this way.
   `--include <flag_id>` adds one record. `--dry-run` previews.
3. Retimes and splits: only from decisions, or with `--structure` when the user asked.

`ccp apply` changes only the text lines of the affected cues (timings, numbering, BOM and line
endings stay byte-identical) and skips any record whose cue changed since it was made. For a
file in the CantoCaptions library it runs the library's lint afterwards and shows a
`git diff --stat`. Tell the user how many cues
changed and any skipped records, and that nothing was committed.

**A pipeline draft or a copy** (`ccp status` → `draft_origin`): `apply` edits
`work/<id>/draft.srt`. When the user is satisfied, `uv run ccp publish <id> --dry-run`, ask, then
`uv run ccp publish <id>` copies it over the source file (keeping its BOM and line endings).

## Cleaning up

A finished job keeps 100–700 MB of files that can be regenerated. When it is done (corrections
applied, the draft published or exported, and the user no longer reviewing the report), run
`uv run ccp prune <id>`. It keeps the draft, records, references, exported subtitles and
`report.html` (without audio). Never prune while the user may still send back decisions.
