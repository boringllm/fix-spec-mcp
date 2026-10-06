"""
engine.py — builds and holds the three indexes over a fix-spec-docs corpus and exposes the
operations the MCP tools call.  Pure stdlib; safe to import and unit-test without the MCP SDK.

Load cost is paid once (ElementTree parse of the 8.6 MB Orchestra repo + a line scan + BM25 over
the prose volumes — a few seconds), then every query is in-memory.
"""
from __future__ import annotations

import os

from . import config
from .citations import Citations
from .corpus import Corpus
from .orchestra import Orchestra


class Engine:
    def __init__(self, root: str):
        self.root = root
        self.warnings: list[str] = []
        self.corpus = Corpus()
        self._load_prose()
        self._load_machine_readable()
        self.corpus.finalize()
        self.citations = Citations(self.corpus)

    # ---------- construction ----------
    def _load_prose(self):
        for name, rel in config.PROSE_DOCS.items():
            path = os.path.join(self.root, rel)
            if os.path.isfile(path):
                self.corpus.add_document(name, path, "prose", index_bm25=True)
            else:
                self.warnings.append(f"missing prose doc: {rel}")

    def _load_machine_readable(self):
        self.xml_path = os.path.join(self.root, config.ORCHESTRA_XML)
        self.xsd_path = os.path.join(self.root, config.DATATYPES_XSD)
        if os.path.isfile(self.xml_path):
            self.corpus.add_document("orchestra", self.xml_path, "orchestra", index_bm25=False)
        else:
            self.warnings.append(f"missing Orchestra XML: {config.ORCHESTRA_XML}")
        if os.path.isfile(self.xsd_path):
            self.corpus.add_document("datatypes-xsd", self.xsd_path, "xsd", index_bm25=False)
        else:
            self.warnings.append(f"missing datatype XSD: {config.DATATYPES_XSD}")
        self.orchestra = Orchestra(
            self.xml_path if os.path.isfile(self.xml_path) else _empty_xml(),
            self.xsd_path if os.path.isfile(self.xsd_path) else None,
        ) if os.path.isfile(self.xml_path) else None

    # ---------- doc-name normalization ----------
    def normalize_doc(self, token: str) -> str | None:
        """Map a user/citation document token to a Corpus key."""
        if not token:
            return None
        if token in self.corpus.docs:
            return token
        t = token.strip().lower()
        if t.endswith(".txt"):
            t = t[:-4]
        key = config.CITATION_ALIASES.get(t)
        if key and key in self.corpus.docs:
            return key
        # tolerate exact prose names without .txt, e.g. "Trade"
        for name in self.corpus.docs:
            if name.lower() == token.strip().lower() or name.lower() == token.strip().lower() + ".txt":
                return name
        return None

    # ---------- operations (return plain dicts/lists) ----------
    def documents(self) -> dict:
        docs = self.corpus.manifest()
        for d in docs:
            orig = config.ORIGINAL_OF.get(d["name"])
            if orig and os.path.isfile(os.path.join(self.root, orig)):
                d["original"] = orig
        return {"root": self.root, "warnings": self.warnings, "documents": docs}

    def original_of(self, doc_name: str) -> str | None:
        """The bundled original file for a (normalized) document, if present."""
        orig = config.ORIGINAL_OF.get(doc_name)
        if orig and os.path.isfile(os.path.join(self.root, orig)):
            return orig
        return None

    def search(self, query: str, limit: int = 10, document: str | None = None) -> dict:
        doc = self.normalize_doc(document) if document else None
        if document and not doc:
            return {"error": f"unknown document '{document}'",
                    "known": [d["name"] for d in self.corpus.manifest()]}
        hits = self.corpus.search(query, limit=min(max(limit, 1), 50), document=doc)
        return {"query": query, "scope": doc or "all prose volumes", "count": len(hits), "hits": hits}

    def grep(self, pattern: str, documents=None, regex: bool = True, ignore_case: bool = True,
             limit: int = 40, context: int = 0) -> dict:
        names = None
        if documents:
            names = []
            for d in documents:
                k = self.normalize_doc(d)
                if k:
                    names.append(k)
                else:
                    return {"error": f"unknown document '{d}'",
                            "known": [x["name"] for x in self.corpus.manifest()]}
        try:
            hits = self.corpus.grep(pattern, names, regex=regex, ignore_case=ignore_case,
                                    limit=min(max(limit, 1), 200), context=min(max(context, 0), 10))
        except Exception as e:  # bad regex
            return {"error": f"grep failed: {e}"}
        return {"pattern": pattern, "count": len(hits), "hits": hits}

    def read(self, document: str, start_line: int, end_line: int) -> dict:
        key = self.normalize_doc(document)
        if not key:
            return {"error": f"unknown document '{document}'",
                    "known": [d["name"] for d in self.corpus.manifest()]}
        return self.corpus.read(key, start_line, end_line)

    def resolve_citation(self, citation: str, context: int = 4) -> dict:
        return self.citations.resolve(citation, context=min(max(context, 0), 40))

    def lookup_field(self, ref: str) -> dict:
        if not self.orchestra:
            return {"error": "Orchestra repository not loaded"}
        return self.orchestra.lookup_field(ref)

    def lookup_message(self, ref: str, depth: int = 4) -> dict:
        if not self.orchestra:
            return {"error": "Orchestra repository not loaded"}
        return self.orchestra.lookup_message(ref, max_depth=min(max(depth, 1), 8))

    def lookup_codeset(self, ref: str) -> dict:
        if not self.orchestra:
            return {"error": "Orchestra repository not loaded"}
        return self.orchestra.lookup_codeset(ref)

    def lookup_datatype(self, name: str) -> dict:
        if not self.orchestra:
            return {"error": "Orchestra repository not loaded"}
        return self.orchestra.lookup_datatype(name)


def _empty_xml():  # pragma: no cover - only used when the repo is absent
    raise RuntimeError("Orchestra XML not available")
