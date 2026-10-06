"""
fixspec — a self-contained search/index engine over the FIX.Latest specification corpus
(fix-spec-docs/), exposed as an MCP server by ../server.py.

The engine (engine.Engine) bundles three indexes:
  * corpus.Corpus         — the prose volumes (.txt extracts): BM25 search, grep, line/page read
  * orchestra.Orchestra   — the machine-readable Orchestra repository + FIXML datatype XSD:
                            structured lookups (field / message / codeSet / datatype) + line map
  * citations.Citations   — resolves the project's own citation tokens (ORCH:134, XSD:32,
                            Trade.txt:1216, Introduction §8.344, TIME p3, ...) to the text.

Stdlib only; no third-party dependency (the MCP SDK lives in server.py, not here), so the
engine can be imported and tested without installing anything.
"""
from .engine import Engine  # noqa: F401

__all__ = ["Engine"]
__version__ = "1.0.0"
