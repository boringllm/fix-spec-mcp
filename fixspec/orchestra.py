"""
orchestra.py — the machine-readable layer: structured lookups over the FIX Orchestra repository
(FIXOrchestra_FIX.Latest_EP312.xml) and the FIXML datatype XML Schema (fixml-datatypes-Latest.xsd).

Answers the questions an agent asks to VERIFY a vector against the normative source:
  * lookup_field(tag|name)    -> datatype, codeSet + codes, synopsis, and the ORCH line to cite.
  * lookup_message(msgType|name) -> required/optional fields and groups (resolved through
                                  components), with the ORCH line — for SV-STRUCT checks.
  * lookup_codeset(name|field) -> the exhaustive legal code values (SV-TYPE-35 enum checks).
  * lookup_datatype(name)     -> the FIXML XSD regex/base + the Orchestra synopsis (SV-TYPE
                                  grammar claims: MonthYear pattern, Exchange=.*, char no facet …).

Every structured answer carries the citeable line (ORCH:<n> / XSD:<n>), so a finding can quote the
exact source.  The tree is parsed with ElementTree; a parallel regex line-scan maps each element to
its declaration line (ElementTree does not expose line numbers in the stdlib).

Stdlib only.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(line: str, name: str) -> str | None:
    m = re.search(r'\b' + re.escape(name) + r'="([^"]*)"', line)
    return m.group(1) if m else None


class Orchestra:
    def __init__(self, xml_path: str, xsd_path: str | None = None):
        self.xml_path = xml_path
        self.xsd_path = xsd_path
        # structured maps
        self.fields: dict[int, dict] = {}
        self.name2tag: dict[str, int] = {}
        self.field_type: dict[int, str] = {}         # tag -> type attr (datatype or codeSet name)
        self.codesets: dict[str, dict] = {}          # name -> {id, base, codes[], line}
        self.codeset_lower: dict[str, str] = {}      # lowercased name -> name
        self.messages: dict[str, dict] = {}          # msgType -> {...}
        self.msg_name2type: dict[str, str] = {}      # lowercased name -> msgType
        self.datatypes: dict[str, dict] = {}         # name -> {baseType, synopsis, line}
        self.xsd: dict[str, dict] = {}               # name -> {pattern, base, line}
        # line maps (declaration line of each element)
        self._field_line: dict[int, int] = {}
        self._codeset_line: dict[str, int] = {}
        self._message_line: dict[str, int] = {}
        self._datatype_line: dict[str, int] = {}
        self._component_line: dict[int, int] = {}
        self._group_line: dict[int, int] = {}
        # raw structure elements for message resolution
        self._components: dict[int, list] = {}
        self._component_name: dict[int, str] = {}
        self._groups: dict[int, dict] = {}

        self._scan_lines(xml_path)
        self._parse(xml_path)
        if xsd_path:
            self._load_xsd(xsd_path)

    # ---------- regex line-map ----------
    def _scan_lines(self, path: str):
        field_re = re.compile(r'<fixr:field\b')
        cs_re = re.compile(r'<fixr:codeSet\b')
        msg_re = re.compile(r'<fixr:message\b')
        dt_re = re.compile(r'<fixr:datatype\b')
        comp_re = re.compile(r'<fixr:component\b')
        grp_re = re.compile(r'<fixr:group\b')
        with open(path, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if field_re.search(line):
                    fid = _attr(line, "id")
                    if fid and fid.isdigit():
                        self._field_line[int(fid)] = n
                elif cs_re.search(line):
                    nm = _attr(line, "name")
                    if nm:
                        self._codeset_line[nm] = n
                elif msg_re.search(line):
                    mt = _attr(line, "msgType")
                    if mt is not None:
                        self._message_line[mt] = n
                elif dt_re.search(line):
                    nm = _attr(line, "name")
                    if nm:
                        self._datatype_line[nm] = n
                elif comp_re.search(line):
                    cid = _attr(line, "id")
                    if cid and cid.isdigit():
                        self._component_line[int(cid)] = n
                elif grp_re.search(line):
                    gid = _attr(line, "id")
                    if gid and gid.isdigit():
                        self._group_line[int(gid)] = n

    # ---------- ElementTree parse ----------
    def _parse(self, path: str):
        root = ET.parse(path).getroot()
        kids = {_local(c.tag): c for c in root}

        # datatypes
        for dt in kids.get("datatypes", []):
            if _local(dt.tag) != "datatype":
                continue
            nm = dt.attrib.get("name", "")
            self.datatypes[nm] = {
                "name": nm,
                "baseType": dt.attrib.get("baseType", nm),
                "synopsis": _synopsis(dt),
                "line": self._datatype_line.get(nm),
            }

        # codeSets
        for c in kids.get("codeSets", []):
            if _local(c.tag) != "codeSet":
                continue
            nm = c.attrib["name"]
            codes = []
            for code in c:
                if _local(code.tag) == "code":
                    codes.append({
                        "value": code.attrib.get("value", ""),
                        "name": code.attrib.get("name", ""),
                        "added": code.attrib.get("added", ""),
                        "synopsis": _synopsis(code),
                    })
            self.codesets[nm] = {
                "name": nm,
                "id": c.attrib.get("id"),
                "base": c.attrib.get("type", "String"),
                "codes": codes,
                "line": self._codeset_line.get(nm),
            }
            self.codeset_lower[nm.lower()] = nm

        # fields
        for fe in kids.get("fields", []):
            if _local(fe.tag) != "field":
                continue
            try:
                tag = int(fe.attrib["id"])
            except (KeyError, ValueError):
                continue
            name = fe.attrib.get("name", f"Field{tag}")
            ftype = fe.attrib.get("type", "String")
            self.field_type[tag] = ftype
            self.fields[tag] = {
                "tag": tag,
                "name": name,
                "type": ftype,
                "added": fe.attrib.get("added", ""),
                "synopsis": _synopsis(fe),
                "line": self._field_line.get(tag),
            }
            self.name2tag[name.lower()] = tag

        # components / groups (kept as elements for message resolution)
        for comp in kids.get("components", []):
            if _local(comp.tag) != "component":
                continue
            cid = int(comp.attrib["id"])
            self._components[cid] = list(comp)
            self._component_name[cid] = comp.attrib.get("name", f"Component{cid}")
        for g in kids.get("groups", []):
            if _local(g.tag) != "group":
                continue
            gid = int(g.attrib["id"])
            num_tag = None
            members = []
            for ch in g:
                lt = _local(ch.tag)
                if lt == "numInGroup":
                    try:
                        num_tag = int(ch.attrib["id"])
                    except (KeyError, ValueError):
                        pass
                elif lt in ("fieldRef", "groupRef", "componentRef"):
                    members.append(ch)
            self._groups[gid] = {"name": g.attrib.get("name", f"Group{gid}"),
                                 "num_tag": num_tag, "members": members}

        # messages
        for m in kids.get("messages", []):
            if _local(m.tag) != "message":
                continue
            mt = m.attrib.get("msgType", "")
            name = m.attrib.get("name", "")
            struct = None
            for ch in m:
                if _local(ch.tag) == "structure":
                    struct = ch
                    break
            self.messages[mt] = {
                "name": name,
                "msgType": mt,
                "id": m.attrib.get("id"),
                "category": m.attrib.get("category", ""),
                "line": self._message_line.get(mt),
                "_structure": struct,
            }
            self.msg_name2type[name.lower()] = mt

    # ---------- XSD datatype patterns ----------
    def _load_xsd(self, xsd_path: str):
        try:
            text = open(xsd_path, encoding="utf-8", errors="replace").read()
        except OSError:
            return
        lines = text.split("\n")
        line_of = {}
        for i, ln in enumerate(lines, 1):
            m = re.search(r'<xs:simpleType name="([^"]+)"', ln)
            if m:
                line_of[m.group(1)] = i
        for m in re.finditer(r'<xs:simpleType name="([^"]+)">(.*?)</xs:simpleType>', text, re.S):
            name, body = m.group(1), m.group(2)
            pat = re.search(r'<xs:pattern value="([^"]*)"', body)
            base = re.search(r'<xs:restriction base="([^"]+)"', body)
            self.xsd[name] = {
                "name": name,
                "pattern": pat.group(1) if pat else None,
                "base": base.group(1) if base else None,
                "line": line_of.get(name),
            }

    # ---------- public lookups ----------
    def lookup_field(self, ref: str) -> dict:
        tag = self._as_tag(ref)
        if tag is None or tag not in self.fields:
            return {"error": f"field '{ref}' not found", "candidates": self._field_candidates(ref)}
        f = dict(self.fields[tag])
        ftype = self.field_type.get(tag, "")
        f["cite"] = f"ORCH:{f['line']}" if f.get("line") else None
        # coded field? attach the codeSet
        cs_name = ftype if ftype in self.codesets else None
        if cs_name:
            cs = self.codesets[cs_name]
            f["is_enum"] = True
            f["codeSet"] = cs_name
            f["base_datatype"] = cs["base"]
            f["codes"] = cs["codes"]
            f["codeSet_cite"] = f"ORCH:{cs['line']}" if cs.get("line") else None
        else:
            f["is_enum"] = False
            f["base_datatype"] = ftype
            dt = self.datatypes.get(ftype)
            if dt:
                f["datatype_synopsis"] = dt["synopsis"]
                f["datatype_cite"] = f"ORCH:{dt['line']}" if dt.get("line") else None
            xsd = self.xsd.get(ftype)
            if xsd:
                f["xsd_pattern"] = xsd["pattern"]
                f["xsd_base"] = xsd["base"]
                f["xsd_cite"] = f"XSD:{xsd['line']}" if xsd.get("line") else None
        return f

    def lookup_codeset(self, ref: str) -> dict:
        name = self._resolve_codeset_name(ref)
        if not name:
            return {"error": f"codeSet '{ref}' not found",
                    "hint": "pass a codeSet name (SideCodeSet), a field name (Side) or tag (54)"}
        cs = self.codesets[name]
        return {
            "codeSet": name,
            "id": cs["id"],
            "base_datatype": cs["base"],
            "cite": f"ORCH:{cs['line']}" if cs.get("line") else None,
            "count": len(cs["codes"]),
            "codes": cs["codes"],
        }

    def lookup_datatype(self, name: str) -> dict:
        # case-insensitive match on the datatype name
        key = None
        for k in self.datatypes:
            if k.lower() == name.lower():
                key = k
                break
        xkey = None
        for k in self.xsd:
            if k.lower() == name.lower():
                xkey = k
                break
        if key is None and xkey is None:
            return {"error": f"datatype '{name}' not found",
                    "candidates": [k for k in self.datatypes if name.lower() in k.lower()][:10]}
        out = {"name": key or xkey}
        if key:
            dt = self.datatypes[key]
            out["baseType"] = dt["baseType"]
            out["synopsis"] = dt["synopsis"]
            out["orchestra_cite"] = f"ORCH:{dt['line']}" if dt.get("line") else None
        if xkey:
            x = self.xsd[xkey]
            out["xsd_pattern"] = x["pattern"]
            out["xsd_base"] = x["base"]
            out["xsd_cite"] = f"XSD:{x['line']}" if x.get("line") else None
        return out

    def lookup_message(self, ref: str, max_depth: int = 6) -> dict:
        mt = ref
        if ref not in self.messages:
            mt = self.msg_name2type.get(ref.lower())
        if not mt or mt not in self.messages:
            return {"error": f"message '{ref}' not found",
                    "candidates": self._message_candidates(ref)}
        m = self.messages[mt]
        rows: list[dict] = []
        if m["_structure"] is not None:
            self._resolve(list(m["_structure"]), rows, depth=0, seen=set(), max_depth=max_depth)
        required_fields = [{"tag": r["tag"], "name": r["name"]}
                           for r in rows if r["presence"] == "required" and r["kind"] == "field"]
        # derive each group's delimiter = its first child member (next row at depth+1)
        groups = []
        for i, r in enumerate(rows):
            if r["kind"] != "group":
                continue
            delim = None
            for s in rows[i + 1:]:
                if s["depth"] <= r["depth"]:
                    break
                if s["depth"] == r["depth"] + 1:
                    delim = {"tag": s.get("tag"), "name": s["name"], "kind": s["kind"]}
                    break
            groups.append({
                "numInGroup_tag": r.get("numInGroup_tag"),
                "name": r["name"],
                "presence": r["presence"],
                "depth": r["depth"],
                "delimiter": delim,
            })
        return {
            "name": m["name"],
            "msgType": mt,
            "id": m["id"],
            "category": m["category"],
            "cite": f"ORCH:{m['line']}" if m.get("line") else None,
            "field_count": len(rows),
            "required_count": len(required_fields),
            "required_fields": required_fields,
            "group_count": len(groups),
            "groups": groups,
            "structure": rows,
        }

    # ---------- message structure resolution ----------
    def _resolve(self, elements, out: list, depth: int, seen: set, max_depth: int):
        for el in elements:
            lt = _local(el.tag)
            presence = el.attrib.get("presence", "optional")
            if lt == "fieldRef":
                try:
                    tag = int(el.attrib["id"])
                except (KeyError, ValueError):
                    continue
                fld = self.fields.get(tag)
                out.append({"kind": "field", "tag": tag,
                            "name": fld["name"] if fld else f"Field{tag}",
                            "presence": presence, "depth": depth})
            elif lt == "componentRef":
                try:
                    cid = int(el.attrib["id"])
                except (KeyError, ValueError):
                    continue
                members = self._components.get(cid)
                out.append({"kind": "component", "id": cid,
                            "name": self._component_name.get(cid, f"Component{cid}"),
                            "presence": presence, "depth": depth})
                if members and depth < max_depth and cid not in seen:
                    self._resolve(members, out, depth + 1, seen | {cid}, max_depth)
            elif lt == "groupRef":
                try:
                    gid = int(el.attrib["id"])
                except (KeyError, ValueError):
                    continue
                g = self._groups.get(gid)
                num_tag = g["num_tag"] if g else None
                fld = self.fields.get(num_tag) if num_tag else None
                out.append({"kind": "group", "id": gid,
                            "numInGroup_tag": num_tag,
                            "name": fld["name"] if fld else (g["name"] if g else f"Group{gid}"),
                            "presence": presence, "depth": depth})
                if g and depth < max_depth and gid not in seen:
                    self._resolve(g["members"], out, depth + 1, seen | {gid}, max_depth)

    # ---------- helpers ----------
    def _as_tag(self, ref: str):
        ref = ref.strip()
        if ref.isdigit():
            return int(ref)
        return self.name2tag.get(ref.lower())

    def _resolve_codeset_name(self, ref: str) -> str | None:
        ref = ref.strip()
        if ref in self.codesets:
            return ref
        low = ref.lower()
        if low in self.codeset_lower:
            return self.codeset_lower[low]
        # by field (name or tag) -> its codeSet
        tag = self._as_tag(ref)
        if tag is not None:
            ftype = self.field_type.get(tag)
            if ftype in self.codesets:
                return ftype
        # tolerate "Side" -> "SideCodeSet"
        if (low + "codeset") in self.codeset_lower:
            return self.codeset_lower[low + "codeset"]
        return None

    def _field_candidates(self, ref: str) -> list[str]:
        low = ref.lower()
        return sorted({self.fields[t]["name"] for n, t in self.name2tag.items()
                       if low in n})[:10]

    def _message_candidates(self, ref: str) -> list[str]:
        low = ref.lower()
        return sorted({self.messages[mt]["name"] for n, mt in self.msg_name2type.items()
                       if low in n})[:10]


def _synopsis(el) -> str:
    parts = []
    for ann in el:
        if _local(ann.tag) != "annotation":
            continue
        for doc in ann:
            if _local(doc.tag) == "documentation" and (doc.text or "").strip():
                parts.append(" ".join((doc.text or "").split()))
    return " ".join(parts)
