"""SRT reading and writing that round-trips byte for byte.

Every line of the file is kept with its own line ending, so writing an unedited file
reproduces it exactly (BOM, CRLF, odd numbering and all), and an edit changes only the
text lines of the cues it touches. That keeps `git diff` in CantoCaptions minimal.

Cues are addressed by **position** (1-based, in file order), never by the SRT counter:
CantoCaptions is moving to start-time-derived IDs and many files still number 1, 2, 3...
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

_TS = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
RE_TIMING = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}")
RE_INVISIBLE = re.compile("[​-‏‪-‮⁦-⁩﻿]")
RE_TAG = re.compile(r"<[^>]+>|\{\\[^}]*\}")
_ENCODINGS = ("utf-8", "utf-16", "big5")
LINE_BREAK = "⏎"   # how a line break inside a cue is shown to (and accepted from) the agent


def _secs(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def fmt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def short_time(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


@dataclass
class Cue:
    pos: int                 # 1-based position in the file
    number: str              # the SRT counter line as written ("" if absent)
    start: float
    end: float
    text_line_idx: list[int] = field(default_factory=list)   # indexes into SrtFile.lines
    lines: list[str] = field(default_factory=list)           # raw text lines
    timing_idx: int = -1                                     # index of the timing line
    number_idx: int = -1                                     # index of the counter line, -1 if none

    @property
    def raw(self) -> str:
        return "\n".join(self.lines)

    @property
    def text(self) -> str:
        """Display text: entities unescaped, tags and invisible characters removed, lines
        joined with \\n."""
        return clean_text(self.raw)

    @property
    def an8(self) -> bool:
        return "{\\an8}" in self.raw

    @property
    def invisible(self) -> list[str]:
        """Invisible characters in the cue (zero-width spaces, direction marks, BOMs)."""
        return RE_INVISIBLE.findall(self.raw)

    @property
    def markup(self) -> list[str]:
        """Tags other than the {\\an8}-style override at the start: <font …>, <i>, …"""
        return [t for t in RE_TAG.findall(self.raw) if not t.startswith("{\\")]

    @property
    def shown(self) -> str | None:
        """The cue as written, with invisible characters spelled out (⟨U+200B⟩) and markup
        kept, or None when that is just the text. `text` hides both."""
        if not (self.invisible or self.markup):
            return None
        return to_display(spell_invisible(re.sub(r"^(\{\\[^}]*\})+", "", self.raw)))


def spell_invisible(s: str) -> str:
    return RE_INVISIBLE.sub(lambda m: f"⟨U+{ord(m.group()):04X}⟩", s)


def invisible_name(ch: str) -> str:
    import unicodedata
    return f"U+{ord(ch):04X} {unicodedata.name(ch, 'invisible character')}"


def clean_text(raw: str) -> str:
    return RE_INVISIBLE.sub("", RE_TAG.sub("", html.unescape(raw))).strip()


def clean_markup(raw: str) -> str:
    """The text with its markup removed but any invisible characters still in place."""
    return RE_TAG.sub("", html.unescape(raw)).strip()


def to_display(text: str) -> str:
    return text.replace("\n", LINE_BREAK)


def from_display(text: str) -> str:
    return text.replace(LINE_BREAK, "\n").replace("\\n", "\n")


class SrtFile:
    def __init__(self, path: Path):
        self.path = Path(path)
        data = self.path.read_bytes()
        self.bom = b""
        if data.startswith(b"\xef\xbb\xbf"):
            self.bom, data = b"\xef\xbb\xbf", data[3:]
        for enc in _ENCODINGS:
            try:
                text = data.decode(enc)
                self.encoding = enc
                break
            except UnicodeError:
                continue
        else:
            raise ValueError(f"{path}: cannot decode as {_ENCODINGS}")
        if self.encoding == "utf-16":
            raise ValueError(f"{path}: UTF-16 files are not supported for editing")
        # (content, ending) per line; the last line may have no ending.
        self.lines: list[list[str]] = []
        for line in text.splitlines(keepends=True):
            body = line.rstrip("\r\n")
            self.lines.append([body, line[len(body):]])
        crlf = sum(1 for _, e in self.lines if e == "\r\n")
        self.newline = "\r\n" if crlf * 2 >= len(self.lines) else "\n"
        self.cues: list[Cue] = []
        self._parse()

    def _parse(self) -> None:
        bodies = [b for b, _ in self.lines]
        i, n = 0, len(bodies)
        while i < n:
            if not RE_TIMING.match(bodies[i]):
                i += 1
                continue
            m = RE_TIMING.match(bodies[i])
            number = bodies[i - 1].strip() if i > 0 and bodies[i - 1].strip().isdigit() else ""
            j = i + 1
            idx = []
            while j < n and bodies[j].strip() != "":
                # A glued next cue: "<digits>" followed by a timing line.
                if RE_TIMING.match(bodies[j]) or (
                        bodies[j].strip().isdigit() and j + 1 < n and RE_TIMING.match(bodies[j + 1])):
                    break
                idx.append(j)
                j += 1
            self.cues.append(Cue(
                pos=len(self.cues) + 1, number=number,
                start=_secs(*m.groups()[:4]), end=_secs(*m.groups()[4:]),
                text_line_idx=idx, lines=[bodies[k] for k in idx],
                timing_idx=i, number_idx=i - 1 if number else -1))
            i = j

    def cue(self, pos: int) -> Cue:
        if not 1 <= pos <= len(self.cues):
            raise ValueError(f"cue {pos} out of range 1..{len(self.cues)}")
        return self.cues[pos - 1]

    def set_text(self, pos: int, new_text: str) -> None:
        """Replace a cue's text lines with *new_text* (\\n or ⏎ separates lines).

        A leading override tag such as {\\an8} is carried over when the new text lacks it, and
        so is a tag pair wrapping a whole line (`<font color="#ffff00">…</font>`, used for
        song lyrics), line by line.
        """
        cue = self.cue(pos)
        new_lines = from_display(new_text).split("\n")
        old_first = cue.lines[0] if cue.lines else ""
        lead = re.match(r"^(\{\\[^}]*\})+", old_first)
        for k, old in enumerate(cue.lines[:len(new_lines)]):
            body = old[lead.end():] if k == 0 and lead else old
            wrap = re.fullmatch(r"(<(\w+)[^>]*>)(.*)(</\2>)", body)
            if wrap and not RE_TAG.search(new_lines[k]):
                new_lines[k] = wrap.group(1) + new_lines[k] + wrap.group(4)
        if lead and not new_lines[0].startswith(lead.group(0)):
            new_lines[0] = lead.group(0) + new_lines[0]
        if not cue.text_line_idx:
            raise ValueError(f"cue {pos} has no text lines to replace")
        first, last = cue.text_line_idx[0], cue.text_line_idx[-1]
        ending = self.lines[last][1]          # "" when the file ends without a newline
        replacement = [[ln, self.newline] for ln in new_lines]
        replacement[-1][1] = ending
        self.lines[first:last + 1] = replacement
        delta = len(replacement) - (last - first + 1)
        cue.lines = new_lines
        cue.text_line_idx = list(range(first, first + len(replacement)))
        if delta:
            for later in self.cues[pos:]:
                later.text_line_idx = [k + delta for k in later.text_line_idx]

    def strip_invisible(self, pos: int) -> int:
        """Remove invisible characters from a cue's lines, leaving its text and markup alone.
        Returns how many were removed."""
        cue = self.cue(pos)
        n = 0
        for k, idx in enumerate(cue.text_line_idx):
            line, end = self.lines[idx]
            clean, removed = RE_INVISIBLE.subn("", line)
            if removed:
                self.lines[idx] = [clean, end]
                cue.lines[k] = clean
                n += removed
        return n

    def numbering(self) -> str:
        """'sequential' (1, 2, 3...), 'ms' (counter = start time in ms, the CantoCaptions
        canonical form) or 'other'."""
        nums = [c.number for c in self.cues]
        if nums and all(n == str(c.pos) for n, c in zip(nums, self.cues)):
            return "sequential"
        if nums and all(n.isdigit() and abs(int(n) - round(c.start * 1000)) <= 1 for n, c in zip(nums, self.cues)):
            return "ms"
        return "other"

    def replace_cue(self, pos: int, new_cues: list[tuple[float, float, str]]) -> None:
        """Replace cue *pos* by one or more cues (a retime or a split), each (start, end, text
        with a newline or ⏎ between lines). Counters are left as they are; call renumber() after
        all structural edits. A leading override tag such as {an8} is carried to every piece."""
        cue = self.cue(pos)
        first = cue.number_idx if cue.number_idx >= 0 else cue.timing_idx
        last = cue.text_line_idx[-1] if cue.text_line_idx else cue.timing_idx
        ending = self.lines[last][1]
        lead = re.match(r"^(\{\\[^}]*\})+", cue.lines[0]) if cue.lines else None
        block: list[list[str]] = []
        for k, (start, end, text) in enumerate(new_cues):
            if k:
                block.append(["", self.newline])
            block.append([cue.number or str(pos), self.newline])
            block.append([f"{fmt_time(start)} --> {fmt_time(end)}", self.newline])
            text_lines = from_display(text).split("\n")
            if lead and not text_lines[0].startswith(lead.group(0)):
                text_lines[0] = lead.group(0) + text_lines[0]
            block += [[ln, self.newline] for ln in text_lines]
        block[-1][1] = ending
        self.lines[first:last + 1] = block
        self.cues = []
        self._parse()

    def renumber(self, style: str) -> None:
        """Rewrite every counter line: sequential, or from the start time in ms."""
        for c in self.cues:
            want = str(c.pos) if style != "ms" else str(round(c.start * 1000))
            if c.number_idx >= 0:
                self.lines[c.number_idx][0] = want
        self.cues = []
        self._parse()

    def to_bytes(self) -> bytes:
        text = "".join(body + end for body, end in self.lines)
        return self.bom + text.encode(self.encoding)

    def save(self, path: Path | None = None) -> None:
        (Path(path) if path else self.path).write_bytes(self.to_bytes())


def read_cues(path: Path) -> list[Cue]:
    return SrtFile(path).cues
