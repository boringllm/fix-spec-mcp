"""
citations.py — resolve a citation token (exactly the forms the attack-vector catalogue uses) to
the text it points at, so an agent can verify a vector against the normative source in one call.

Accepted forms (case-insensitive; a trailing `.txt` on a prose token is tolerated):
    ORCH:134                 Orchestra XML line 134
    XML lines 79264-79281    Orchestra XML line range
    XSD:32                   FIXML datatype schema line 32
    PROSE:1702               Introduction (the §5 datatype table) line 1702
    Trade.txt:1216           a prose volume line
    Introduction:3932        a prose volume line
    Introduction §8.344      a prose section (searched by heading)
    §8.344                   section in the Introduction (default prose volume)
    TimePrecision p3         / TIME page 3   a prose page
Ranges (`N-M`) and a context radius are supported.

Stdlib only.
"""
from __future__ import annotations

import re

from . import config

# TOKEN : N            or TOKEN : N - M      or TOKEN  N
_LINE_RE = re.compile(r'^\s*([A-Za-z0-9_.\-]+?)\s*(?::|lines?|line|\s)\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$')
# TOKEN § x.y.z   or  § x.y
_SECTION_RE = re.compile(r'^\s*(?:([A-Za-z0-9_.\-]+)\s+)?§?\s*(\d+(?:\.\d+)+)\s*$')
# TOKEN p N  /  TOKEN page N
_PAGE_RE = re.compile(r'^\s*([A-Za-z0-9_.\-]+)\s*(?:p|pg|page)\.?\s*(\d+)\s*$', re.IGNORECASE)

_ACCEPTED = [
    "ORCH:134", "XML lines 79264-79281", "XSD:32", "PROSE:1702",
    "Trade.txt:1216", "Introduction:3932", "Introduction §8.344", "§8.344",
    "TimePrecision p3", "TIME page 3",
]


class Citations:
    def __init__(self, corpus):
        self.corpus = corpus

    def _doc_for(self, token: str) -> str | None:
        t = token.strip().lower()
        if t.endswith(".txt"):
            t = t[:-4]
        return config.CITATION_ALIASES.get(t)

    def resolve(self, citation: str, context: int = 4) -> dict:
        citation = (citation or "").strip()
        if not citation:
            return self._fail("empty citation")

        # 1) page form (check before line form, since 'p' is not a digit)
        m = _PAGE_RE.match(citation)
        if m:
            doc = self._doc_for(m.group(1))
            if not doc:
                return self._fail(f"unknown document token '{m.group(1)}'")
            try:
                start, end = self.corpus.page_region(doc, int(m.group(2)))
            except (KeyError, ValueError) as e:
                return self._fail(str(e))
            return self._emit(citation, doc, start, end, note=f"page {m.group(2)}")

        # 2) section form (contains a dotted number, optionally a § / doc)
        m = _SECTION_RE.match(citation)
        if m and ("§" in citation or "." in m.group(2)):
            token = m.group(1)
            doc = self._doc_for(token) if token else "Introduction.txt"
            if not doc:
                return self._fail(f"unknown document token '{token}'")
            loc = self._find_section(doc, m.group(2))
            if loc is None:
                return self._fail(f"section {m.group(2)} not found in {doc}",
                                  hint="try `search` for the section title, or a line citation")
            start = max(1, loc)
            end = loc + max(context, 8)
            return self._emit(citation, doc, start, end, note=f"§{m.group(2)}")

        # 3) line / line-range form
        m = _LINE_RE.match(citation)
        if m:
            doc = self._doc_for(m.group(1))
            if not doc:
                return self._fail(f"unknown document token '{m.group(1)}'")
            a = int(m.group(2))
            b = int(m.group(3)) if m.group(3) else a
            start = max(1, min(a, b) - context)
            end = max(a, b) + context
            return self._emit(citation, doc, start, end,
                              note=f"lines {a}" + (f"-{b}" if b != a else ""))

        return self._fail(f"could not parse citation '{citation}'")

    def _find_section(self, doc: str, number: str):
        d = self.corpus.docs.get(doc)
        if not d:
            return None
        pat = re.compile(r'^\s*§?\s*' + re.escape(number) + r'(?:\s|\)|\.|$)')
        heading = re.compile(r'^\s*§?\s*' + re.escape(number) + r'\s+\S')
        toc = re.compile(r'\.{3,}\s*\d+\s*$')   # dot-leader + trailing page no. = Table of Contents
        fallback = None
        for i, ln in enumerate(d.lines, 1):
            if not pat.match(ln):
                continue
            if fallback is None:
                fallback = i
            # a real section heading: number then a title, and NOT a TOC dot-leader line
            if heading.match(ln) and not toc.search(ln):
                return i
        return fallback

    def _emit(self, citation, doc, start, end, note=None) -> dict:
        r = self.corpus.read(doc, start, end)
        return {
            "citation": citation,
            "document": doc,
            "resolved": note,
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "page_start": r["page_start"],
            "page_end": r["page_end"],
            "text": r["text"],
        }

    def _fail(self, msg: str, hint: str | None = None) -> dict:
        out = {"error": msg, "accepted_forms": _ACCEPTED}
        if hint:
            out["hint"] = hint
        return out
