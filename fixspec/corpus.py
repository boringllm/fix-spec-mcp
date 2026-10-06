"""
corpus.py — the prose layer: loads the .txt volume extracts, maps every line to its PDF page,
provides line-accurate `read`, regex/substring `grep` over ANY text document (prose, the
Orchestra XML, the datatype XSD), and a pure-Python BM25 search over the prose volumes.

Design choices
--------------
* **Line- and page-accurate.** Each extract keeps `===== PAGE n/total =====` markers, so every
  line resolves to a page and every hit is citable as `Trade.txt:1216` (and "page 42").
* **BM25 over passages, not whole files.** A "passage" is a run of non-blank lines (a paragraph
  or a table block), sub-chunked to <= MAX_PASSAGE_LINES so hits stay tightly citable. BM25
  (Okapi, k1=1.5, b=0.75) ranks passages for a natural-language query; an exact-substring bonus
  rewards phrase matches. This is the "clever" prose search an agent uses to find the rule behind
  a vector when it does not already have a line number.
* **grep is separate** (literal/regex, any document) for when the agent already knows the exact
  string/tag and wants its line — the right tool for the structured XML/XSD.

Stdlib only.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field as dc_field

MAX_PASSAGE_LINES = 12          # cap passage size so BM25 hits stay citable
_PAGE_RE = re.compile(r"^=====\s*PAGE\s+(\d+)\s*/\s*(\d+)\s*=====")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")

_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    """Lowercased alphanumeric tokens, plus CamelCase sub-tokens so a field name like
    `OrderQty` also matches a query for `order` / `qty` / `quantity`-adjacent wording."""
    toks: list[str] = []
    for w in _WORD_RE.findall(text):
        wl = w.lower()
        toks.append(wl)
        parts = _CAMEL_RE.findall(w)
        if len(parts) > 1:
            toks.extend(p.lower() for p in parts)
    return toks


@dataclass
class Passage:
    doc: str
    start: int           # 1-based line number of the first line
    end: int             # 1-based line number of the last line
    page: int
    text: str
    tf: Counter = dc_field(default_factory=Counter)
    length: int = 0


@dataclass
class Document:
    name: str
    path: str
    kind: str            # "prose" | "orchestra" | "xsd"
    lines: list[str]     # 1-based access via lines[n-1]
    page_of: list[int]   # page_of[n-1] = page number for line n (0 if unknown)
    pages: int


class Corpus:
    def __init__(self):
        self.docs: dict[str, Document] = {}
        self.passages: list[Passage] = []
        self._df: Counter = Counter()          # document (passage) frequency per term
        self._avg_len: float = 0.0
        self._n_passages: int = 0

    # ---------- loading ----------
    def add_document(self, name: str, path: str, kind: str, index_bm25: bool):
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        lines = raw.split("\n")
        page_of = [0] * len(lines)
        pages = 0
        cur = 0
        for i, ln in enumerate(lines):
            m = _PAGE_RE.match(ln)
            if m:
                cur = int(m.group(1))
                pages = max(pages, int(m.group(2)), cur)
            page_of[i] = cur
        doc = Document(name=name, path=path, kind=kind, lines=lines, page_of=page_of, pages=pages)
        self.docs[name] = doc
        if index_bm25:
            self._index_passages(doc)

    def finalize(self):
        self._n_passages = len(self.passages)
        total = 0
        for p in self.passages:
            total += p.length
            for term in p.tf:
                self._df[term] += 1
        self._avg_len = (total / self._n_passages) if self._n_passages else 0.0

    def _index_passages(self, doc: Document):
        block: list[int] = []  # line indices (0-based) of the current block

        def flush():
            if not block:
                return
            # sub-chunk long blocks so citations stay tight
            for s in range(0, len(block), MAX_PASSAGE_LINES):
                chunk = block[s:s + MAX_PASSAGE_LINES]
                start_idx, end_idx = chunk[0], chunk[-1]
                text = "\n".join(doc.lines[i] for i in chunk)
                tf = Counter(tokenize(text))
                self.passages.append(Passage(
                    doc=doc.name, start=start_idx + 1, end=end_idx + 1,
                    page=doc.page_of[start_idx], text=text, tf=tf, length=sum(tf.values())))
            block.clear()

        for i, ln in enumerate(doc.lines):
            if _PAGE_RE.match(ln) or not ln.strip():
                flush()
            else:
                block.append(i)
        flush()

    # ---------- BM25 search (prose) ----------
    def search(self, query: str, limit: int = 10, document: str | None = None) -> list[dict]:
        q_terms = tokenize(query)
        if not q_terms:
            return []
        q_set = list(dict.fromkeys(q_terms))
        idf = {}
        for t in q_set:
            n = self._df.get(t, 0)
            # Okapi BM25 idf with +1 smoothing (never negative)
            idf[t] = math.log(1 + (self._n_passages - n + 0.5) / (n + 0.5))
        phrase = query.strip().lower()
        scored = []
        for p in self.passages:
            if document and p.doc != document:
                continue
            if not any(t in p.tf for t in q_set):
                continue
            score = 0.0
            for t in q_set:
                f = p.tf.get(t, 0)
                if not f:
                    continue
                denom = f + _K1 * (1 - _B + _B * (p.length / (self._avg_len or 1)))
                score += idf[t] * (f * (_K1 + 1)) / denom
            if len(phrase) >= 4 and phrase in p.text.lower():
                score *= 1.35  # exact-phrase bonus
            scored.append((score, p))
        scored.sort(key=lambda sp: (-sp[0], sp[1].doc, sp[1].start))
        out = []
        for score, p in scored[:limit]:
            out.append({
                "document": p.doc,
                "line": p.start,
                "end_line": p.end,
                "page": p.page,
                "score": round(score, 3),
                "citation": f"{p.doc}:{p.start}",
                "snippet": _trim(p.text, 600),
            })
        return out

    # ---------- grep (any document) ----------
    def grep(self, pattern: str, documents: list[str] | None, regex: bool = True,
             ignore_case: bool = True, limit: int = 40, context: int = 0) -> list[dict]:
        flags = re.IGNORECASE if ignore_case else 0
        rx = re.compile(pattern if regex else re.escape(pattern), flags)
        names = documents or list(self.docs.keys())
        out: list[dict] = []
        for name in names:
            doc = self.docs.get(name)
            if not doc:
                continue
            for i, ln in enumerate(doc.lines):
                if rx.search(ln):
                    n = i + 1
                    item = {
                        "document": name,
                        "line": n,
                        "page": doc.page_of[i],
                        "citation": f"{_cite_prefix(name)}:{n}",
                        "text": ln.rstrip(),
                    }
                    if context:
                        lo = max(0, i - context)
                        hi = min(len(doc.lines), i + context + 1)
                        item["context"] = "\n".join(
                            f"{j+1}: {doc.lines[j].rstrip()}" for j in range(lo, hi))
                    out.append(item)
                    if len(out) >= limit:
                        return out
        return out

    # ---------- read ----------
    def read(self, document: str, start: int, end: int, max_lines: int = 400) -> dict:
        doc = self.docs.get(document)
        if not doc:
            raise KeyError(document)
        start = max(1, start)
        end = min(len(doc.lines), max(start, end))
        if end - start + 1 > max_lines:
            end = start + max_lines - 1
        body = "\n".join(f"{n}: {doc.lines[n-1].rstrip()}" for n in range(start, end + 1))
        return {
            "document": document,
            "start_line": start,
            "end_line": end,
            "page_start": doc.page_of[start - 1],
            "page_end": doc.page_of[end - 1],
            "text": body,
        }

    # ---------- manifest ----------
    def manifest(self) -> list[dict]:
        out = []
        for name, doc in self.docs.items():
            out.append({
                "name": name,
                "kind": doc.kind,
                "lines": len(doc.lines),
                "pages": doc.pages if doc.kind == "prose" else None,
                "path": doc.path,
            })
        return out

    def page_region(self, document: str, page: int) -> tuple[int, int]:
        """1-based [start,end] line range of a given page in a prose doc."""
        doc = self.docs.get(document)
        if not doc:
            raise KeyError(document)
        start = end = None
        for i, pg in enumerate(doc.page_of):
            if pg == page:
                if start is None:
                    start = i + 1
                end = i + 1
        if start is None:
            raise ValueError(f"page {page} not found in {document}")
        return start, end


def _cite_prefix(name: str) -> str:
    if name == "orchestra":
        return "ORCH"
    if name == "datatypes-xsd":
        return "XSD"
    return name


def _trim(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"
