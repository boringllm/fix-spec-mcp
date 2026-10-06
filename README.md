# fix-spec-mcp — a FIX specification search server (MCP)

A **standalone, self-contained MCP server** that lets an agent search and read the official
FIX.Latest specification corpus — **bundled inside this project** under `docs/` — so it can
**verify an attack vector against the normative source** and then analyze further. Copy the
`fix-spec-mcp/` folder anywhere and it runs with no external files.

The attack-vector catalogue cites the spec with tokens like `ORCH:134`, `XSD:32`,
`Trade.txt:1216`, `Introduction §8.344`. This server is built to resolve **exactly those** — and
to answer the structural questions behind the vectors (a field's datatype, a codeSet's legal
values, a message's required fields and repeating groups) — each answer carrying the line to cite
back in the report.

```
agent has a vector:  "SV-APP-3: StopPx(99) required for OrdType=Stop  (Trade.txt:1216)"
        │
        ├─ resolve_citation("Trade.txt:1216")   → the exact rule text, page 45
        ├─ lookup_field("99")                    → StopPx, datatype Price, cite ORCH:…
        └─ lookup_message("D")                   → is StopPx required? which groups? cite ORCH:…
        → vector confirmed, with sources, ready for the report.
```

## What it indexes

The corpus is bundled under `docs/` (≈35 MB). What the **server reads**:

| Kind | Document (under `docs/`) | Used for |
|------|--------------------------|----------|
| **prose** | `text/*.txt` — Introduction, Infrastructure, Trade, PreTrade, PostTrade, OrderStateChanges, TimePrecision (the EP284 volume text extracts, with `===== PAGE n =====` markers) | BM25 full-text `search`, `grep`, line/page `read`, `§`/page citations |
| **orchestra** | `extracted/orchestra/FIXOrchestra_FIX.Latest_EP312.xml` (the machine-readable repository, 154k lines) | structured `lookup_field` / `lookup_message` / `lookup_codeset` / `lookup_datatype`, `grep`, `ORCH:<line>` citations |
| **xsd** | `extracted/fixml/fixml-datatypes-Latest.xsd` (FIXML datatype schema — the normative regex patterns) | datatype patterns in `lookup_datatype`/`lookup_field`, `grep`, `XSD:<line>` citations |

### Originals for manual verification
The **original source documents are bundled too** (at the `docs/` root) so a human can check a
finding by hand afterward — the server does **not** read them:
the seven EP284 PDFs (`FIX-Latest-as-of-EP284-*.pdf`, the Time-Precision addendum) and the three
EP312 packages (`FIXOrchestra_*.zip`, `FIXUnifiedRepository_*.zip`, `fixmlschema_*.zip`).
A prose citation's **page number is the page in the matching PDF**, so `Trade.txt:1216` (page 45)
means *open `FIX-Latest-as-of-EP284-Trade.pdf` at page 45*. `list_documents` names each document's
original, and `read`/`resolve_citation` append a "verify by hand" pointer to the right file+page.

## Install & run

Python 3.9+. One dependency (the MCP SDK); the search engine itself is pure standard library.

```bash
cd fix-spec-mcp
python -m pip install -r requirements.txt
python server.py          # uses the bundled docs/ — no path needed
```

The docs root is resolved in this order: first CLI arg → `FIX_SPEC_DOCS` env var → the **bundled
`docs/`** (the default). You only set a path to point it at a *different* corpus. The server talks
MCP over **stdio**.

### Configure it in an MCP client

**Claude Desktop** — add to `claude_desktop_config.json` (see `mcp-config.example.json`):

```json
{
  "mcpServers": {
    "fix-spec-search": {
      "command": "python",
      "args": ["C:\\temp\\LLM\\fix\\fix-spec-mcp\\server.py"]
    }
  }
}
```

**Claude Code** (CLI):

```bash
claude mcp add fix-spec-search -- python C:\temp\LLM\fix\fix-spec-mcp\server.py
```

No docs path is required — the corpus is bundled. (To use a different corpus, add
`--env FIX_SPEC_DOCS=<path>`.)

## Tools

| Tool | Use it to… | Example |
|------|-----------|---------|
| `list_documents` | see the corpus (names, kinds, line/page counts) | — |
| `search` | **find** the rule behind a vector by concept (BM25 over the prose volumes) | `search("stop order missing stop price")` |
| `grep` | find an **exact** string / tag / XML construct, line-accurate, in any document | `grep('name="MonthYear"', documents="XSD")` |
| `read` | read an exact line range (page markers preserved) | `read("Trade.txt", 1210, 1230)` |
| `resolve_citation` | turn a **citation token into its source text** (the fast verify path) | `resolve_citation("Introduction §8.344")` |
| `lookup_field` | a field's datatype, codeSet + codes, XSD pattern, cites | `lookup_field("Side")` |
| `lookup_message` | a message's required fields + repeating groups (count tag → delimiter), cite | `lookup_message("D")` |
| `lookup_codeset` | the exhaustive legal code values of a codeSet | `lookup_codeset("SessionRejectReason")` |
| `lookup_datatype` | a datatype's FIXML regex/base + Orchestra synopsis, cites | `lookup_datatype("Exchange")` |

Every result includes the **citation to use in the report** (`ORCH:<line>`, `XSD:<line>`,
`<Volume>.txt:<line>`), so the agent can carry provenance straight through to its finding.

### Citation tokens `resolve_citation` understands
`ORCH:134` · `XML lines 79264-79281` · `XSD:32` · `PROSE:1702` · `Trade.txt:1216` ·
`Introduction:3932` · `Introduction §8.344` · `§8.344` · `TimePrecision p3` · `TIME page 3`
(case-insensitive; a trailing `.txt` is tolerated; `N-M` ranges and a `context` radius are supported).

## Worked examples (verifying a vector)

- **SV-TYPE-21 (MonthYear regex over-permissive).** `lookup_datatype("MonthYear")` returns pattern
  `\d{4}(0|1)\d([0-3wW]\d)?` (cite `XSD:146`) and the prose "MM = 01-12" (cite `ORCH:324`). The
  agent sees the regex admits month `00`/`13-19` while the prose says `01-12` — vector confirmed with
  two sources.
- **SV-STRUCT-3 (group delimiter).** `lookup_message("D")` shows `NoPartyIDs(453)` with
  `delimiter=PartyID(448)` — exactly the first-member-delimiter rule the vector attacks (cite the
  message's `ORCH:` line).
- **SV-TYPE-35 (enum out-of-range).** `lookup_codeset("Side")` lists all 17 codes `1..9,A..H`; the
  agent confirms the last code is `H`, so `54=I` is out of range.

## How the search works (design notes)

- **Line- and page-accurate.** Every prose line maps to its PDF page via the `===== PAGE n =====`
  markers, so every hit is citable as `Trade.txt:1216` *and* "page 45".
- **BM25 over passages.** `search` ranks paragraph/table-block passages (Okapi BM25, k1=1.5, b=0.75)
  with CamelCase-aware tokenization (so `OrderQty` also matches `order`/`qty`) and an exact-phrase
  bonus. It covers the natural-language volumes; structured XML/XSD is served by `grep` + the
  structured lookups instead (more precise than ranking XML as text).
- **Structured Orchestra/XSD index.** The repository is parsed once (ElementTree) into
  field/codeSet/message/datatype maps; a parallel regex line-scan records each element's declaration
  line so structured answers stay citable (ElementTree does not expose line numbers).
- **Fast & self-contained.** Loads in well under a second; the engine (`fixspec/`) is pure stdlib and
  importable/testable without MCP.

## Project layout

```
fix-spec-mcp/
  server.py              MCP server (FastMCP): the 9 tools + formatting. Entry point.
  fixspec/               the search/index engine (pure stdlib — no MCP, independently testable)
    config.py            corpus layout + docs-root resolution + citation aliases
    corpus.py            prose loader, page/line maps, BM25 search, grep, read
    orchestra.py         Orchestra XML + FIXML XSD structured index + line map
    citations.py         citation-token parser/resolver
    engine.py            wires the three indexes; the operations the tools call
  docs/                  the BUNDLED corpus (self-contained)
    text/*.txt           the EP284 prose volume extracts        } read by the server
    extracted/orchestra/FIXOrchestra_FIX.Latest_EP312.xml       }
    extracted/fixml/fixml-datatypes-Latest.xsd                  }
    FIX-Latest-as-of-EP284-*.pdf                                } original PDFs — for humans,
    *_FIX.Latest_EP312.zip                                      }   not read by the server
  test_engine.py         offline smoke test (no MCP needed):  python test_engine.py
  requirements.txt       the one dependency (mcp)
  pyproject.toml         packaging metadata
  mcp-config.example.json  ready-to-paste client config
```

## Testing

```bash
python test_engine.py          # exercises every operation against the real corpus, no MCP needed
```

## Notes
- Read-only: the server never writes to the corpus.
- If a document is missing, the server still starts; `list_documents` reports it under `warnings`
  and the affected tools return a clear error.
- SBE/FAST/JSON/GPB specifications are not in this corpus; add their files under `docs/` and
  extend `fixspec/config.py` to index them.
