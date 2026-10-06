#!/usr/bin/env python3
"""Offline smoke test of the fixspec engine (no MCP needed). Run: python test_engine.py"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixspec import Engine  # noqa: E402
from fixspec import config  # noqa: E402

root = config.resolve_root(base_dir=os.path.dirname(os.path.abspath(__file__)))
print(f"docs root: {root}")
t0 = time.time()
eng = Engine(root)
print(f"loaded in {time.time()-t0:.2f}s; warnings={eng.warnings}\n")


def show(title, obj, trim=900):
    s = json.dumps(obj, indent=2, ensure_ascii=False)
    if len(s) > trim:
        s = s[:trim] + "\n…(trimmed)"
    print(f"===== {title} =====\n{s}\n")


show("documents", eng.documents())
show("search: stop order missing stop price", eng.search("stop order missing stop price", limit=3))
show("search: billion laughs entity expansion", eng.search("external entity DOCTYPE", limit=2))
show("grep XSD MonthYear pattern", eng.grep(r'name="MonthYear"', documents=["XSD"], context=2, limit=3))
show("resolve ORCH:134", eng.resolve_citation("ORCH:134"))
show("resolve XSD:32", eng.resolve_citation("XSD:32"))
show("resolve Trade.txt:1216", eng.resolve_citation("Trade.txt:1216"))
show("resolve Introduction §8.344", eng.resolve_citation("Introduction §8.344"))
show("resolve XML lines 79264-79281", eng.resolve_citation("XML lines 79264-79281"))
show("resolve TimePrecision p3", eng.resolve_citation("TimePrecision p3"))
show("lookup_field 38 (OrderQty)", eng.lookup_field("38"))
show("lookup_field Side", eng.lookup_field("Side"))
show("lookup_codeset Side", eng.lookup_codeset("Side"))
show("lookup_datatype MonthYear", eng.lookup_datatype("MonthYear"))
show("lookup_datatype Exchange", eng.lookup_datatype("Exchange"))
m = eng.lookup_message("D")
m_small = {k: v for k, v in m.items() if k != "structure"}
m_small["structure_head"] = m.get("structure", [])[:8]
show("lookup_message D (NewOrderSingle) [head]", m_small)
print("OK")
