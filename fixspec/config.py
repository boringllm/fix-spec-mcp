"""
config.py — corpus layout + docs-root resolution for fixspec.

The project is SELF-CONTAINED: the documents it indexes are bundled under `<project>/docs/`.
Resolution order (the bundled copy is the default; the others only relocate it):
  1. an explicit path passed on the command line (server.py argv[1]),
  2. the FIX_SPEC_DOCS environment variable,
  3. the bundled corpus `<project>/docs/`  (default — no external dependency).
"""
from __future__ import annotations

import os

# Logical prose documents (text extracts of the EP284 PDFs), relative to the docs root.
PROSE_DOCS = {
    "Introduction.txt":       "text/Introduction.txt",
    "Infrastructure.txt":     "text/Infrastructure.txt",
    "Trade.txt":              "text/Trade.txt",
    "PreTrade.txt":           "text/PreTrade.txt",
    "PostTrade.txt":          "text/PostTrade.txt",
    "OrderStateChanges.txt":  "text/OrderStateChanges.txt",
    "TimePrecision.txt":      "text/TimePrecision.txt",
}

# Machine-readable documents.
ORCHESTRA_XML = "extracted/orchestra/FIXOrchestra_FIX.Latest_EP312.xml"
DATATYPES_XSD = "extracted/fixml/fixml-datatypes-Latest.xsd"

# Original source files bundled under the docs root (NOT read by the server — kept so a human can
# verify a hit manually afterward). A prose citation's page number is the page in these PDFs.
ORIGINAL_OF = {
    "Introduction.txt":      "FIX-Latest-as-of-EP284-Introduction.pdf",
    "Infrastructure.txt":    "FIX-Latest-as-of-EP284-Infrastructure.pdf",
    "Trade.txt":             "FIX-Latest-as-of-EP284-Trade.pdf",
    "PreTrade.txt":          "FIX-Latest-as-of-EP284-PreTrade.pdf",
    "PostTrade.txt":         "FIX-Latest-as-of-EP284-PostTrade.pdf",
    "OrderStateChanges.txt": "FIX-Latest-as-of-EP284-Order-State-Changes.pdf",
    "TimePrecision.txt":     "FIX-Technical-Addendum-Time-Precision.pdf",
    "orchestra":             "FIXOrchestra_FIX.Latest_EP312.zip",
    "datatypes-xsd":         "fixmlschema_FIX.Latest_EP312.zip",
}

# Citation-token aliases -> logical document id.  Case-insensitive; an optional ".txt" on a
# prose token is tolerated.  These are the exact tokens the attack-vector catalogue uses.
CITATION_ALIASES = {
    "orch": "orchestra",
    "xml": "orchestra",
    "orchestra": "orchestra",
    "xsd": "datatypes-xsd",
    "fixml-datatypes": "datatypes-xsd",
    "fixml-datatypes-latest.xsd": "datatypes-xsd",
    "datatypes": "datatypes-xsd",
    "prose": "Introduction.txt",          # "PROSE" in the catalogue = the Introduction datatype table
    "introduction": "Introduction.txt",
    "infrastructure": "Infrastructure.txt",
    "trade": "Trade.txt",
    "pretrade": "PreTrade.txt",
    "posttrade": "PostTrade.txt",
    "orderstatechanges": "OrderStateChanges.txt",
    "order-state-changes": "OrderStateChanges.txt",
    "time": "TimePrecision.txt",
    "timeprecision": "TimePrecision.txt",
}


def resolve_root(explicit: str | None = None, base_dir: str | None = None) -> str:
    """Return the absolute docs root. `base_dir` is the directory of server.py, used for the
    default sibling layout."""
    if explicit:
        return os.path.abspath(explicit)
    env = os.environ.get("FIX_SPEC_DOCS")
    if env:
        return os.path.abspath(env)
    base = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.abspath(os.path.join(base, "docs"))
