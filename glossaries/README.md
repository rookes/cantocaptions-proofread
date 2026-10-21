# Show glossaries

One file per show, named `<show_slug>.md` (the slug is in the episode record). The agent
creates and maintains these while proofreading; the format is described in
`.agents/skills/proofread-subtitles/references/reading.md`. The convention checks (`L` lines,
`ccp clean --lint`) flag the spellings listed in a glossary's `Avoid` column.

Glossaries are kept on this machine only: everything here except this README is gitignored.
