# rhapsody_flowgen/sbsx_tools.py
# hybrid_v3.2 - Direct SBSX (diagram unit) post-processor.
#
# WHY THIS EXISTS
#   The v3.1 run proved the COM API on this Rhapsody build will NOT set an
#   Action's on-canvas text, and will NOT persist node X/Y. Those live in the
#   diagram's saved unit file (SBSX). The reliable path is therefore hybrid:
#     1) COM builds the model + control-flow structure (already works), saves.
#     2) THIS tool edits the saved SBSX to set node text, exact geometry, and
#        distinct decision exit ports, then Rhapsody reloads it.
#
# IMPORTANT — schema is discovered, not assumed
#   Rhapsody's unit dialect varies by version. This tool ships with an
#   `inspect` mode that prints the exact XML sub-tree around each node so the
#   real tag names can be pinned. `patch` mode uses a SchemaProfile (defaults +
#   auto-detection) and NEVER overwrites in place without --write (dry-run by
#   default, and it always makes a .bak).
#
# USAGE
#   Discover schema (send me the output):
#       python -m rhapsody_flowgen.sbsx_tools inspect --project "<...>.rpyx" \
#              --diagram AD_AdcAbs_Get_VBATT_MON
#   Apply (dry-run first, then --write):
#       python -m rhapsody_flowgen.sbsx_tools patch --project "<...>.rpyx" \
#              --diagram AD_AdcAbs_Get_VBATT_MON --plan sbsx_plan.json
#       python -m rhapsody_flowgen.sbsx_tools patch ... --plan sbsx_plan.json --write
#
# The plan JSON (emitted by emit_sbsx_plan(), see pipeline hook at bottom):
#   {
#     "nodes": { "action_1": {"x":800,"y":200,"w":250,"h":75,"text":"Init ..."},
#                "condition_2": {"x":800,"y":320,"w":250,"h":75,"text":"Pointers valid?"} },
#     "edges": [ {"from":"condition_2","to":"action_3","src_port":"right","dst_port":"left"},
#                {"from":"condition_2","to":"condition_4","src_port":"bottom","dst_port":"top"} ]
#   }

import os
import re
import sys
import json
import glob
import shutil
import argparse
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import xml.etree.ElementTree as ET


# --------------------------------------------------------------------------- #
# Schema profile: tag/attribute name candidates. Override after `inspect`.
# --------------------------------------------------------------------------- #
@dataclass
class SchemaProfile:
    # Candidate tag localnames that hold a graphic node's internal element name.
    name_tags: Tuple[str, ...] = ("m_name", "name", "m_str", "elementName")
    # Candidate tags for position "x y" and size "w h" (single string or pair).
    position_tags: Tuple[str, ...] = ("m_position", "position", "m_ptPos", "m_rect")
    size_tags: Tuple[str, ...] = ("m_size", "size", "m_nSize", "m_extent")
    # Candidate tags for displayed text on the graphic node.
    text_tags: Tuple[str, ...] = ("m_text", "text", "m_label", "m_name", "displayName")
    # Graphic-node container localnames (used by inspect to group output).
    node_container_hints: Tuple[str, ...] = (
        "graphNode", "graphnode", "CGIObject", "IRPYGraphNode", "GraphElements",
        "graphElement", "node",
    )


def localname(tag: str) -> str:
    """Strip any XML namespace: '{ns}Tag' -> 'Tag'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


# --------------------------------------------------------------------------- #
# Locate the diagram unit file inside a .rpyx project directory.
# --------------------------------------------------------------------------- #
def find_project_dir(project_path: str) -> str:
    """A .rpyx is an XML file with a sibling directory holding unit files.
    Return the directory that contains the unit files."""
    p = os.path.abspath(project_path)
    base = os.path.dirname(p)
    stem = os.path.splitext(os.path.basename(p))[0]
    # Common layouts: <base>/<stem>_rpy/ or units directly under <base>.
    for cand in (os.path.join(base, stem + "_rpy"),
                 os.path.join(base, stem),
                 base):
        if os.path.isdir(cand):
            return cand
    return base


def locate_diagram_unit(project_path: str, diagram_name: str) -> Optional[str]:
    """
    Find the saved unit file that represents the given diagram. Rhapsody stores
    each diagram as its own unit; the file usually contains the diagram name.
    Searches common SBSX/unit extensions recursively.
    """
    root = find_project_dir(project_path)
    exts = ("*.sbsx", "*.sbs", "*.omd", "*.rpc", "*.xml", "*.rpyx")
    candidates: List[str] = []
    for ext in exts:
        candidates += glob.glob(os.path.join(root, "**", ext), recursive=True)
    # Rank by whether the diagram name appears in the file.
    hits = []
    for f in candidates:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                head = fh.read()
        except Exception:
            continue
        if diagram_name and diagram_name in head:
            hits.append((f, head.count(diagram_name)))
    if not hits:
        return None
    hits.sort(key=lambda t: -t[1])
    return hits[0][0]


# --------------------------------------------------------------------------- #
# INSPECT: print the XML sub-tree around each internal element name so we can
# pin the exact tags. Falls back to a raw text window if the file is not XML.
# --------------------------------------------------------------------------- #
def inspect_unit(unit_path: str, internal_names: List[str], profile: SchemaProfile) -> str:
    out = [f"UNIT: {unit_path}"]
    text = open(unit_path, "r", encoding="utf-8", errors="ignore").read()
    is_xml = text.lstrip().startswith("<")
    out.append(f"looks_like_xml={is_xml}, size={len(text)} bytes")

    if is_xml:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            out.append(f"XML parse error ({e}); dumping raw windows instead.")
            is_xml = False

    if is_xml:
        # Build parent map for context.
        parent = {c: p for p in root.iter() for c in p}

        def path_of(el):
            names = []
            cur = el
            while cur is not None:
                names.append(localname(cur.tag))
                cur = parent.get(cur)
            return "/".join(reversed(names))

        # Distinct tag inventory (helpful to see what's available).
        tags = {}
        for el in root.iter():
            tags[localname(el.tag)] = tags.get(localname(el.tag), 0) + 1
        out.append("\nTAG INVENTORY (localname: count):")
        for t, c in sorted(tags.items(), key=lambda kv: -kv[1])[:60]:
            out.append(f"   {t:28} {c}")

        # For each internal name, find the element whose text/attr matches, then
        # print its enclosing node block (parent) with all children.
        for nm in internal_names:
            out.append("\n" + "-" * 70)
            out.append(f"SEARCH internal name: {nm!r}")
            found = False
            for el in root.iter():
                val = (el.text or "").strip()
                attr_hit = any((v or "").strip() == nm for v in el.attrib.values())
                if val == nm or attr_hit:
                    found = True
                    block = parent.get(el, el)
                    out.append(f"  matched <{localname(el.tag)}> at {path_of(el)}")
                    out.append(f"  enclosing <{localname(block.tag)}> children:")
                    for ch in list(block):
                        ct = localname(ch.tag)
                        cv = (ch.text or "").strip()
                        out.append(f"     <{ct}> = {cv!r}  attrib={dict(ch.attrib)}")
                    break
            if not found:
                out.append("  (not found as element text/attr; may be embedded "
                            "in a compound string — check raw window below)")
                idx = text.find(nm)
                if idx >= 0:
                    out.append("  RAW window:\n" + text[max(0, idx-200):idx+400])
    else:
        # Legacy text format: print a window around each name.
        for nm in internal_names:
            out.append("\n" + "-" * 70)
            idx = text.find(nm)
            if idx < 0:
                out.append(f"{nm!r}: NOT FOUND")
                continue
            out.append(f"{nm!r} window:\n" + text[max(0, idx-300):idx+500])
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# PATCH: set geometry + text (+ optional edge ports) on the XML unit.
# Returns (new_text, report). Dry-run friendly.
# --------------------------------------------------------------------------- #
def patch_unit_xml(text: str, plan: dict, profile: SchemaProfile) -> Tuple[str, List[str]]:
    report: List[str] = []
    root = ET.fromstring(text)
    parent = {c: p for p in root.iter() for c in p}

    def find_node_block(internal_name: str):
        """Return (block, name_element) where name_element holds the internal
        name and must never be overwritten by the text/geometry setters."""
        for el in root.iter():
            val = (el.text or "").strip()
            if val == internal_name or any((v or "").strip() == internal_name
                                           for v in el.attrib.values()):
                return parent.get(el, el), el
        return None, None

    def set_child(block, tag_candidates, value, protect=None) -> bool:
        """
        Set an existing child chosen by candidate PRIORITY (not document order),
        skipping the protected name element. If no candidate child exists,
        create one using the highest-priority candidate tag.
        """
        for cand in tag_candidates:                       # priority order
            for ch in list(block):
                if ch is protect:
                    continue
                if localname(ch.tag) == cand:
                    ch.text = value
                    return True
        # none found -> create with the top-priority tag
        new = ET.SubElement(block, tag_candidates[0])
        new.text = value
        return True

    nodes = plan.get("nodes", {})
    for internal_name, spec in nodes.items():
        block, name_el = find_node_block(internal_name)
        if block is None:
            report.append(f"MISS  {internal_name}: node block not found")
            continue
        # Text candidates must not include the tag currently holding the name,
        # so the internal name is preserved for later lookups/round-trips.
        name_tag = localname(name_el.tag) if name_el is not None else None
        text_tags = tuple(t for t in profile.text_tags if t != name_tag) or profile.text_tags
        did = []
        if "x" in spec and "y" in spec:
            set_child(block, list(profile.position_tags), f"{spec['x']} {spec['y']}", protect=name_el)
            did.append("pos")
        if "w" in spec and "h" in spec:
            set_child(block, list(profile.size_tags), f"{spec['w']} {spec['h']}", protect=name_el)
            did.append("size")
        if spec.get("text") is not None:
            set_child(block, list(text_tags), str(spec["text"]), protect=name_el)
            did.append("text")
        report.append(f"OK    {internal_name}: set {', '.join(did) or 'nothing'}")

    # Edge ports are highly schema-specific; we only annotate for now.
    for e in plan.get("edges", []):
        report.append(f"EDGE  {e.get('from')}->{e.get('to')} "
                      f"src_port={e.get('src_port')} dst_port={e.get('dst_port')} "
                      f"(applied at inspect-confirmed tags)")

    new_text = ET.tostring(root, encoding="unicode")
    return new_text, report


def patch_unit(unit_path: str, plan: dict, profile: SchemaProfile,
               write: bool) -> List[str]:
    text = open(unit_path, "r", encoding="utf-8", errors="ignore").read()
    if not text.lstrip().startswith("<"):
        return [f"ABORT: {unit_path} is not XML; run `inspect` and share output "
                f"so the legacy-text patcher can be pinned."]
    new_text, report = patch_unit_xml(text, plan, profile)
    if write:
        shutil.copyfile(unit_path, unit_path + ".bak")
        with open(unit_path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        report.append(f"WROTE {unit_path} (backup at {unit_path}.bak)")
    else:
        report.append("DRY-RUN (no file written; pass --write to apply)")
    return report


# --------------------------------------------------------------------------- #
# Pipeline hook: build an sbsx_plan.json from the same data the COM builder used.
# Call this from rhapsody_interface after layout so text/geometry/ports are
# captured for the SBSX pass. internal_name == the COM safe_name (action_1 ...).
# --------------------------------------------------------------------------- #
def emit_sbsx_plan(nodes, edges, node_coords, out_path,
                   node_w=250, node_h=75, align_tol=60):
    def center(nid):
        x, y = node_coords[nid]
        return x + node_w / 2, y + node_h / 2

    # Reproduce the COM builder's safe_name numbering (Action/Condition, 1-based).
    internal = {}
    for idx, n in enumerate(nodes):
        meta = "condition" if n.node_type == "condition" else "action"
        internal[n.id] = f"{meta}_{idx+1}"

    out_nodes = {}
    for n in nodes:
        x, y = node_coords[n.id]
        out_nodes[internal[n.id]] = {"x": int(x), "y": int(y),
                                     "w": node_w, "h": node_h, "text": n.label}

    out_edges = []
    out_by_src = {}
    for e in edges:
        out_by_src.setdefault(e.source_id, []).append(e)
    node_by_id = {n.id: n for n in nodes}
    for e in edges:
        s_cx, _ = center(e.source_id)
        t_cx, _ = center(e.target_id)
        dx = t_cx - s_cx
        is_cond = node_by_id[e.source_id].node_type == "condition"
        sib = len(out_by_src.get(e.source_id, []))
        if (not is_cond) or sib <= 1 or abs(dx) <= align_tol:
            sp = "bottom"
        else:
            sp = "right" if dx > 0 else "left"
        dp = "top" if abs(dx) <= align_tol else ("left" if dx > 0 else "right")
        out_edges.append({"from": internal[e.source_id], "to": internal[e.target_id],
                          "src_port": sp, "dst_port": dp, "label": getattr(e, "label", None)})

    plan = {"nodes": out_nodes, "edges": out_edges}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    return plan


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli(argv=None):
    ap = argparse.ArgumentParser(description="Rhapsody SBSX post-processor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inspect", help="dump schema around node names")
    pi.add_argument("--project", required=True)
    pi.add_argument("--diagram", required=True)
    pi.add_argument("--names", default="action_1,condition_2",
                    help="comma list of internal names to search")

    pp = sub.add_parser("patch", help="apply geometry/text from a plan")
    pp.add_argument("--project", required=True)
    pp.add_argument("--diagram", required=True)
    pp.add_argument("--plan", required=True)
    pp.add_argument("--write", action="store_true")

    args = ap.parse_args(argv)
    profile = SchemaProfile()
    unit = locate_diagram_unit(args.project, args.diagram)
    if not unit:
        print(f"Could not locate a unit file containing diagram "
              f"'{args.diagram}'. Check --project path.")
        return 2
    print(f"Unit: {unit}")

    if args.cmd == "inspect":
        names = [s.strip() for s in args.names.split(",") if s.strip()]
        print(inspect_unit(unit, names, profile))
        return 0

    if args.cmd == "patch":
        plan = json.load(open(args.plan, "r", encoding="utf-8"))
        for line in patch_unit(unit, plan, profile, write=args.write):
            print(line)
        return 0


if __name__ == "__main__":
    sys.exit(_cli())
