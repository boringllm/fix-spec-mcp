#!/usr/bin/env python3
"""
fix-spec-search — an MCP server over the FIX.Latest specification corpus (fix-spec-docs/).

Purpose: let an agent VERIFY a FIX attack vector against the normative source. The attack-vector
catalogue cites the spec with tokens like `ORCH:134`, `XSD:32`, `Trade.txt:1216`,
`Introduction §8.344`; this server resolves exactly those, searches the prose volumes, greps the
machine-readable files line-accurately, and answers structured questions about fields, codeSets,
messages and datatypes — each answer carrying the line to cite back in a report.

Run (stdio):
    FIX_SPEC_DOCS=/path/to/fix-spec-docs  python server.py
or pass the docs root as the first argument:
    python server.py /path/to/fix-spec-docs
With neither, it defaults to the sibling ../fix-spec-docs.

Requires the `mcp` package (see requirements.txt). The search/index engine (fixspec/) is pure
stdlib and can be used without MCP (see test_engine.py).
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from mcp.server.fastmcp import FastMCP  # noqa: E402
from fixspec import Engine, config      # noqa: E402

mcp = FastMCP("fix-spec-search")

_engine: Engine | None = None
_load_error: str | None = None


def engine() -> Engine:
    """Build the index on first use (a few seconds), then reuse it."""
    global _engine, _load_error
    if _engine is None and _load_error is None:
        explicit = None
        for a in sys.argv[1:]:
            if not a.startswith("-"):
                explicit = a
                break
        root = config.resolve_root(explicit=explicit, base_dir=_HERE)
        if not os.path.isdir(root):
            _load_error = (f"docs root not found: {root}\n"
                           "Set FIX_SPEC_DOCS or pass the fix-spec-docs path as argv[1].")
        else:
            _engine = Engine(root)
    if _load_error:
        raise RuntimeError(_load_error)
    return _engine


# ----------------------------- formatting helpers -----------------------------
def _err(d: dict) -> str | None:
    if isinstance(d, dict) and "error" in d:
        extra = ""
        for k in ("candidates", "known", "accepted_forms", "hint"):
            if d.get(k):
                extra += f"\n{k}: {d[k]}"
        return f"ERROR: {d['error']}{extra}"
    return None


def _fmt_search(r: dict) -> str:
    e = _err(r)
    if e:
        return e
    if not r["hits"]:
        return f"No matches for '{r['query']}' in {r['scope']}."
    out = [f"{r['count']} hit(s) for '{r['query']}' in {r['scope']} (ranked):"]
    for h in r["hits"]:
        pg = f", page {h['page']}" if h.get("page") else ""
        out.append(f"\n[{h['score']}] {h['citation']}  (lines {h['line']}-{h['end_line']}{pg})\n"
                   f"    {h['snippet']}")
    out.append("\nVerify/expand any hit with read(document, start, end) or resolve_citation(<citation>).")
    return "\n".join(out)


def _fmt_grep(r: dict) -> str:
    e = _err(r)
    if e:
        return e
    if not r["hits"]:
        return f"No lines matching /{r['pattern']}/."
    out = [f"{r['count']} line(s) matching /{r['pattern']}/:"]
    for h in r["hits"]:
        pg = f", page {h['page']}" if h.get("page") else ""
        out.append(f"  {h['citation']}{pg}: {h['text']}")
        if h.get("context"):
            out.append("    " + h["context"].replace("\n", "\n    "))
    return "\n".join(out)


def _manual_hint(document: str, page_start: int) -> str:
    """A one-line pointer to the bundled original so a human can verify by hand."""
    orig = engine().original_of(document)
    if not orig:
        return ""
    where = f" at page {page_start}" if page_start else ""
    return f"\n(verify by hand: open {orig}{where} under the docs root)"


def _fmt_read(r: dict) -> str:
    e = _err(r)
    if e:
        return e
    pg = ""
    if r.get("page_start"):
        pg = f" (page {r['page_start']}" + (f"-{r['page_end']}" if r.get("page_end") and r["page_end"] != r["page_start"] else "") + ")"
    return (f"{r['document']} lines {r['start_line']}-{r['end_line']}{pg}:\n{r['text']}"
            + _manual_hint(r["document"], r.get("page_start", 0)))


def _fmt_citation(r: dict) -> str:
    e = _err(r)
    if e:
        return e
    pg = f" (page {r['page_start']})" if r.get("page_start") else ""
    return (f"{r['citation']}  ->  {r['document']} {r.get('resolved','')}  "
            f"lines {r['start_line']}-{r['end_line']}{pg}:\n{r['text']}"
            + _manual_hint(r["document"], r.get("page_start", 0)))


def _fmt_field(r: dict) -> str:
    e = _err(r)
    if e:
        return e
    lines = [f"Field {r['tag']} — {r['name']}  (type={r['type']}, added {r.get('added','?')})  "
             f"[cite {r.get('cite')}]",
             f"  synopsis: {r.get('synopsis','')}"]
    if r.get("is_enum"):
        lines.append(f"  ENUM codeSet {r['codeSet']} (base {r['base_datatype']})  "
                     f"[cite {r.get('codeSet_cite')}] — {len(r.get('codes',[]))} codes:")
        lines.append("    " + ", ".join(f"{c['value']}={c['name']}" for c in r.get("codes", [])))
    else:
        lines.append(f"  datatype {r['base_datatype']}: {r.get('datatype_synopsis','')}  "
                     f"[cite {r.get('datatype_cite')}]")
        if r.get("xsd_pattern") is not None or r.get("xsd_base"):
            lines.append(f"  FIXML XSD: pattern={r.get('xsd_pattern')!r} base={r.get('xsd_base')}  "
                         f"[cite {r.get('xsd_cite')}]")
    return "\n".join(lines)


def _fmt_codeset(r: dict) -> str:
    e = _err(r)
    if e:
        return e
    out = [f"codeSet {r['codeSet']} (id {r['id']}, base {r['base_datatype']}, {r['count']} codes)  "
           f"[cite {r.get('cite')}]"]
    for c in r["codes"]:
        syn = f" — {c['synopsis']}" if c.get("synopsis") else ""
        out.append(f"  {c['value']} = {c['name']}{syn}")
    return "\n".join(out)


def _fmt_datatype(r: dict) -> str:
    e = _err(r)
    if e:
        return e
    out = [f"datatype {r['name']}"]
    if r.get("baseType"):
        out.append(f"  baseType: {r['baseType']}")
    if r.get("synopsis"):
        out.append(f"  synopsis: {r['synopsis']}  [cite {r.get('orchestra_cite')}]")
    if r.get("xsd_pattern") is not None or r.get("xsd_base"):
        out.append(f"  FIXML XSD: pattern={r.get('xsd_pattern')!r} base={r.get('xsd_base')}  "
                   f"[cite {r.get('xsd_cite')}]")
    return "\n".join(out)


def _fmt_message(r: dict) -> str:
    e = _err(r)
    if e:
        return e
    out = [f"Message {r['msgType']} — {r['name']}  (id {r['id']}, category {r['category']})  "
           f"[cite {r.get('cite')}]",
           f"  {r['field_count']} fields total (expanded), {r['required_count']} required, "
           f"{r['group_count']} repeating groups."]
    out.append("  REQUIRED fields (omitting any → SessionRejectReason=1/9):")
    out.append("    " + ", ".join(f"{f['name']}({f['tag']})" for f in r["required_fields"]))
    if r["groups"]:
        cap = 120
        shown = r["groups"][:cap]
        out.append(f"  REPEATING GROUPS (NoXxx count tag → first-member delimiter)"
                   f"{f' — showing {cap} of {len(r['groups'])}' if len(r['groups']) > cap else ''}:")
        for g in shown:
            d = g.get("delimiter") or {}
            dl = f"{d.get('name')}({d.get('tag')})" if d else "?"
            indent = "    " + "  " * g["depth"]
            out.append(f"{indent}{g['name']}({g.get('numInGroup_tag')}) "
                       f"[{g['presence']}] delimiter={dl}")
        if len(r["groups"]) > cap:
            out.append("    … (raise `depth` lower or read the raw structure at the cite for the rest)")
    out.append("  (Use read(orchestra, <line>, <line+N>) at the cite to see the raw structure.)")
    return "\n".join(out)


def _split_docs(s: str) -> list[str] | None:
    s = (s or "").strip()
    if not s:
        return None
    return [p.strip() for p in s.replace(",", " ").split() if p.strip()]


# ----------------------------------- tools ------------------------------------
@mcp.tool()
def list_documents() -> str:
    """List the FIX specification documents this server indexes (name, kind, line/page counts).
    Call this first to see what is available. Kinds: 'prose' (the EP284 volume text extracts,
    full-text searchable), 'orchestra' (the FIX Orchestra machine-readable repository), 'xsd' (the
    FIXML datatype schema). Document names are what you pass to the other tools."""
    return _dumps_docs(engine().documents())


@mcp.tool()
def search(query: str, limit: int = 10, document: str = "") -> str:
    """Full-text BM25 search over the FIX prose volumes (Introduction, Trade, PreTrade, PostTrade,
    OrderStateChanges, Infrastructure, TimePrecision). Use this to FIND the rule behind an attack
    vector when you do not already have a line number — e.g. search("stop order missing stop price")
    or search("sequence reset gap fill"). Returns ranked, citable hits (document:line, page, snippet).
    Optionally restrict to one document by name. For an exact string/tag/pattern, use grep instead."""
    return _fmt_search(engine().search(query, limit=limit, document=document or None))


@mcp.tool()
def grep(pattern: str, documents: str = "", regex: bool = True, ignore_case: bool = True,
         limit: int = 40, context: int = 0) -> str:
    """Line-accurate literal/regex search over ANY indexed document, including the Orchestra XML and
    the datatype XSD. Use this when you know the exact string, tag, field name, or XML construct and
    want its line(s) — e.g. grep('name="MonthYear"', documents='XSD') or grep('StopPx') . `documents`
    is an optional comma/space-separated list of names (default: all). `context` adds N neighbour
    lines. Returns citable matches (ORCH:<line> / XSD:<line> / <Volume>.txt:<line>)."""
    r = engine().grep(pattern, documents=_split_docs(documents), regex=regex,
                      ignore_case=ignore_case, limit=limit, context=context)
    return _fmt_grep(r)


@mcp.tool()
def read(document: str, start_line: int, end_line: int) -> str:
    """Read an exact line range from a document (line-numbered, with page markers preserved). Use
    this to read AROUND a hit or a citation — e.g. read('Trade.txt', 1200, 1230) or
    read('orchestra', 126734, 126760). Document names come from list_documents (aliases ORCH/XSD and
    the prose names with or without .txt are accepted). Capped at 400 lines per call."""
    return _fmt_read(engine().read(document, start_line, end_line))


@mcp.tool()
def resolve_citation(citation: str, context: int = 4) -> str:
    """Resolve a FIX attack-vector citation token directly to the source text — the fastest way to
    verify a vector. Accepts exactly the catalogue's forms: 'ORCH:134', 'XML lines 79264-79281',
    'XSD:32', 'PROSE:1702', 'Trade.txt:1216', 'Introduction §8.344', '§8.344', 'TimePrecision p3',
    'TIME page 3'. Returns the document, resolved line/section/page and the surrounding text (±context
    lines). Use this whenever a vector's Source field gives you a token to check."""
    return _fmt_citation(engine().resolve_citation(citation, context=context))


@mcp.tool()
def lookup_field(field: str) -> str:
    """Look up a FIX field by tag NUMBER or NAME in the Orchestra repository. Returns its datatype,
    synopsis, and — if it is an enumerated field — its codeSet with every legal code value, plus the
    FIXML XSD pattern/base and the ORCH/XSD lines to cite. Use to verify a datatype- or enum-level
    vector, e.g. lookup_field('38') (OrderQty=Qty) or lookup_field('Side') (its 17 codes)."""
    return _fmt_field(engine().lookup_field(field))


@mcp.tool()
def lookup_message(message: str, depth: int = 4) -> str:
    """Look up a FIX message by MsgType (e.g. 'D') or name (e.g. 'NewOrderSingle'). Returns its
    required fields, its repeating groups (NoXxx count tag + first-member delimiter) and the ORCH
    line to cite — the structural facts behind the SV-STRUCT vectors (required-field omission, group
    count/delimiter desync, tag-not-defined-for-this-type). `depth` controls how far nested
    components/groups are expanded (1-8, default 4); raise it to see deeply nested subgroups."""
    return _fmt_message(engine().lookup_message(message, depth=depth))


@mcp.tool()
def lookup_codeset(code_set: str) -> str:
    """List the exhaustive legal code values of a FIX codeSet. Accepts a codeSet name
    (e.g. 'SideCodeSet', 'SessionRejectReasonCodeSet'), a field name (e.g. 'Side') or a field tag
    (e.g. '54'). Use to verify an enum/out-of-range vector (SV-TYPE-35): the last defined code,
    gaps, and the kind (char/int/String) are all here, each citable to its ORCH line."""
    return _fmt_codeset(engine().lookup_codeset(code_set))


@mcp.tool()
def lookup_datatype(datatype: str) -> str:
    """Look up a FIX datatype's normative grammar: the FIXML XSD regex pattern and base type plus the
    Orchestra synopsis, with ORCH/XSD lines to cite. Use to verify a grammar-level vector — e.g.
    lookup_datatype('MonthYear') (pattern \\d{4}(0|1)\\d([0-3wW]\\d)? — admits month 00/13-19),
    lookup_datatype('Exchange') (pattern .* — accepts anything), lookup_datatype('UTCTimestamp')."""
    return _fmt_datatype(engine().lookup_datatype(datatype))


def _dumps_docs(d: dict) -> str:
    out = [f"docs root: {d['root']}"]
    if d["warnings"]:
        out.append("warnings: " + "; ".join(d["warnings"]))
    out.append(f"{len(d['documents'])} documents:")
    for doc in d["documents"]:
        pg = f", {doc['pages']} pages" if doc.get("pages") else ""
        orig = f"  ← original: {doc['original']}" if doc.get("original") else ""
        out.append(f"  {doc['name']:<22} [{doc['kind']}] {doc['lines']} lines{pg}{orig}")
    out.append("\nCitation tokens: ORCH:<n> (orchestra), XSD:<n> (datatypes-xsd), "
               "<Volume>.txt:<n>, 'Introduction §x.y', 'TimePrecision p<n>'.")
    out.append("The original PDFs/zips are bundled under the docs root for manual verification; a "
               "prose citation's page number is the page in that PDF.")
    return "\n".join(out)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
