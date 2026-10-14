# Output: report and/or edits

## Report

```
uv run ccp report <id>            # audio clips (cue ± 1 s)
uv run ccp report <id> --video    # 480p video clips instead (slower, larger)
```

This writes `work/<id>/report.html` with clips in `work/<id>/clips/`. It opens from disk with no
server. Flags are grouped as **Essential corrections**, **Suggested**, and **Queries**. Each card
shows the draft and proposed text with the changed characters marked, the reference line, both
ASR hypotheses, the neighbouring cues, your evidence and note, and a player for the clip.

The reviewer can accept (optionally editing the text), reject, or leave each flag, then press
**Export decisions** to download `decisions.json`. Tell the user the report path and that
they can hand the exported file back to you.

Re-run `ccp report` after changing flags; clips are reused.

## Applying edits

Only when the user asked for edits. Three ways, from most to least reviewed:

1. **From the reviewer's decisions** (preferred):
   `uv run ccp apply <id> --decisions <path to decisions.json>`
   applies exactly the accepted flags with the reviewer's text and marks rejected ones.
2. **High-confidence fixes directly** (when the user asked for that):
   `uv run ccp apply <id>` applies flags that are `essential` + `high` and have a proposed
   text, never particle flags. Widen with `--min-severity suggested --min-confidence medium`
   only if the user explicitly asks. Add a single flag with `--include <flag_id>`.
3. **Preview first:** add `--dry-run` to see what would change without writing.

`ccp apply` edits the working draft in place: the subtitle file in the CantoCaptions working
tree, or `work/<id>/draft.srt` for a pipeline draft (see below). It changes
only the text lines of the affected cues (timings, numbering, BOM and line endings stay
byte-identical) and skips any flag whose cue changed since you recorded it. It then runs the
CantoCaptions lint and reports any new warnings, plus a `git diff --stat`.

After applying, tell the user how many cues changed, list any skipped flags with the reason,
and remind them that nothing was committed (`git -C ../CantoCaptions diff` shows the change).
Never commit.

## Retimes and splits

Flags with a timing proposal show the current and proposed times in the report and can only be
accepted or rejected, not edited. `ccp apply --decisions` applies accepted ones. Without a
decisions file they are applied only with `--structure`. After a split, `apply` renumbers
the cues in the file's own style and moves the later flags along.

## Publishing a pipeline draft

When the working draft came from `ccp pipeline` (see `ccp status`), `ccp apply` edits
`work/<id>/draft.srt`, not the user's file. When the user is satisfied:
1. `uv run ccp publish <id> --dry-run` shows the target and cue counts;
2. ask the user, then `uv run ccp publish <id>` copies the draft over the source file in
   CantoCaptions (keeping its BOM and line endings), or `--to <path>` writes elsewhere.
It never renames or commits. `git -C ../CantoCaptions diff` shows the change.

## Cleaning up

A finished episode keeps 100–700 MB of regenerable files: the stored aligner output (used by
`score` and `timing`), the report's audio clips, and cantocaptions-ai debug files. When the job
is done (corrections applied, the draft published or exported, and the user is not reviewing
the report any more), run `uv run ccp prune <id>`. It keeps the draft, flags, evidence,
references, pipeline outputs, exported subtitles and `report.html` (without audio). Do not
prune while the user may still open the report or send back decisions. `apply`, `publish`
and `export` mention how much a prune would free. `ccp prune --finished --dry-run` lists
every finished workspace.

