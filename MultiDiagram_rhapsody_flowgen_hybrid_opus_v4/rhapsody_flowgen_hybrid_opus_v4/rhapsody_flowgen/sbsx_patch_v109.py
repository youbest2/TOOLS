# sbsx_patch_v109.py  (v3.2.2)  -- RAW-TEXT surgical editor (RPY-ASCII safe)
#
# CRITICAL: Rhapsody 109 requires "RPY-ASCII" format. Re-serializing the XML
# (lxml/ElementTree) corrupts it: it turns <x></x> into <x/> and changes the
# declaration quotes, so Rhapsody rejects the file ("not in RPY-ASCII format").
# THEREFORE we NEVER write via an XML serializer. We locate elements (read-only)
# and apply targeted string replacements to the ORIGINAL text, preserving every
# other byte, the LF line endings, tabs, and empty-tag style exactly.

import os, re, sys, json, uuid, shutil, argparse, logging
from typing import Dict, List, Optional, Tuple
from lxml import etree  # read-only: locating GUIDs / positions / scoping only

NODE_W, NODE_H = 250, 75

def ln(e) -> str:
    t = getattr(e, "tag", None)
    return etree.QName(t).localname if isinstance(t, str) else ""

def _child(e, name):
    for ch in e:
        if ln(ch) == name: return ch
    return None

def _ctext(e, name) -> Optional[str]:
    c = _child(e, name)
    return (c.text or "").strip() if c is not None else None

def enc_body(s: str) -> str:
    """Encode a body string the RPY-ASCII way: XML-escape, CR->%0D, keep LF."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "%0D\n")
    return s

class SbsxRaw:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as fh:
            self._bom = b""
            data = fh.read()
            if data[:3] == b"\xef\xbb\xbf":
                self._bom = b"\xef\xbb\xbf"; data = data[3:]
        self.raw = data.decode("utf-8", errors="strict")  # exact text, LF preserved
        # read-only parse for locating (never used for output)
        self.tree = etree.fromstring(self.raw.encode("utf-8"),
                                     etree.XMLParser(huge_tree=True))
        self._index()

    # ---------- locating (read-only tree) ----------
    def _index(self):
        self.diagram_name_to_id = {}
        self.istate_id_to_elem = {}
        self.cgi_nodes = []
        self.statecharts = []
        for e in self.tree.iter():
            t = ln(e)
            if t in ("IActivityDiagram", "IActivityGraph", "IDiagram"):
                i = _ctext(e, "_id"); n = _ctext(e, "_name")
                if i and n: self.diagram_name_to_id.setdefault(n, i)
            elif t == "IState":
                i = _ctext(e, "_id")
                if i: self.istate_id_to_elem[i] = e
            elif t == "CGIStateChart":
                self.statecharts.append(e)
            elif t == "CGIActionState":
                self.cgi_nodes.append(e)

    def statechart_for_diagram(self, name):
        did = self.diagram_name_to_id.get(name)
        if not did: return None
        for sc in self.statecharts:
            mo = _child(sc, "m_pModelObject")
            if mo is None: continue
            for h in mo.iter():
                if ln(h) == "_hid" and (h.text or "").strip() == did:
                    return sc
        return None

    @staticmethod
    def root_frame(sc):
        return _ctext(sc, "m_pRoot") if sc is not None else None

    def graph_nodes_for_frame(self, sc):
        """All graphical NODE elements under the frame. Includes action boxes
        (CGIActionState) AND decision diamonds (CGIConnector w/ model IBranch).
        Excludes real edges: any element carrying m_pSource/m_pTarget, plus
        CGITrans/CGIText/CGIStateChart. A node is identified by having an
        m_transform (its on-canvas position) and NO m_pSource."""
        frame = self.root_frame(sc)
        if not frame: return []
        out = []
        for e in self.tree.iter():
            t = ln(e)
            if not t.startswith("CGI"): continue
            if t in ("CGITrans", "CGIText", "CGIStateChart"): continue
            if _ctext(e, "m_pParent") != frame: continue
            if _child(e, "m_transform") is None: continue
            if _child(e, "m_pSource") is not None: continue  # that's an edge
            out.append(e)
        return out

    @staticmethod
    def node_translate(node):
        tr = _child(node, "m_transform")
        if tr is None: return None
        p = (tr.text or "").split()
        if len(p) >= 6:
            try: return (float(p[4]), float(p[5]))
            except ValueError: return None
        return None

    @staticmethod
    def node_id(node): return _ctext(node, "_id")

    @staticmethod
    def node_model_hid(node):
        mo = _child(node, "m_pModelObject")
        if mo is None: return None
        for h in mo.iter():
            if ln(h) == "_hid": return (h.text or "").strip()
        return None

    # ---------- RAW surgical edits ----------
    def _find_id_pos(self, gid: str) -> int:
        needle = '<_id type="a">%s</_id>' % gid  # gid already like "GUID xxxx"
        return self.raw.find(needle)

    def set_node_position_raw(self, node_gid: str, x, y) -> bool:
        pos = self._find_id_pos(node_gid)
        if pos < 0: return False
        m = re.compile(r'(<m_transform type="a">)([^<]*)(</m_transform>)')\
              .search(self.raw, pos)
        if not m: return False
        parts = m.group(2).split()
        if len(parts) >= 6:
            parts[4] = ("%g" % x); parts[5] = ("%g" % y)
            new = m.group(1) + " ".join(parts) + " " + m.group(3)
        else:
            new = m.group(1) + "1 0 0 1 %g %g " % (x, y) + m.group(3)
        self.raw = self.raw[:m.start()] + new + self.raw[m.end():]
        return True

    def _cgitrans_block_span(self, src_gid: str, tgt_gid: str):
        src_line = '<m_pSource type="s">%s</m_pSource>' % src_gid
        start = 0
        while True:
            i = self.raw.find(src_line, start)
            if i < 0: return None
            b = self.raw.rfind("<CGITrans type=\"e\">", 0, i)
            e = self.raw.find("</CGITrans>", i)
            if b >= 0 and e >= 0:
                block = self.raw[b:e]
                if ('<m_pTarget type="s">%s</m_pTarget>' % tgt_gid) in block:
                    return (b, e)
            start = i + len(src_line)

    def set_edge_ports_raw(self, src_gid, tgt_gid, sp, tp) -> bool:
        span = self._cgitrans_block_span(src_gid, tgt_gid)
        if not span: return False
        b, e = span
        block = self.raw[b:e]
        def repl(block, tag, val):
            m = re.search(r'(<%s type="a">)([^<]*)(</%s>)' % (tag, tag), block)
            if not m: return block, False
            new = m.group(1) + ("%d %d " % (int(val[0]), int(val[1]))) + m.group(3)
            return block[:m.start()] + new + block[m.end():], True
        block, ok1 = repl(block, "m_SourcePort", sp)
        block, ok2 = repl(block, "m_TargetPort", tp)
        if not (ok1 and ok2): return False
        self.raw = self.raw[:b] + block + self.raw[e:]
        return True

    def _istate_block_span(self, gid: str):
        pos = self._find_id_pos(gid)
        if pos < 0: return None
        b = self.raw.rfind('<IState type="e">', 0, pos)
        e = self.raw.find("</IState>", pos)
        if b < 0 or e < 0: return None
        return (b, e + len("</IState>"))

    def set_action_body_raw(self, istate_gid: str, text: str) -> bool:
        # SAFETY: only edit genuine IState elements. Condition nodes link to an
        # IBranch (no body); never touch those (prevents wrong-span edits).
        if istate_gid not in self.istate_id_to_elem:
            return False
        span = self._istate_block_span(istate_gid)
        if not span: return False
        b, e = span
        block = self.raw[b:e]
        body_val = enc_body(text)

        # Case A: existing <_body ...>...</_body> -> replace inner (non-greedy, DOTALL)
        m = re.search(r'(<_body type="a">)(.*?)(</_body>)', block, re.DOTALL)
        if m:
            nb = block[:m.start()] + m.group(1) + body_val + m.group(3) + block[m.end():]
            self.raw = self.raw[:b] + nb + self.raw[e:]
            return True

        # figure out indentation from the IState's _id line
        idln = re.search(r'\n(\t*)<_id type="a">%s</_id>' % re.escape(istate_gid), block)
        ind4 = idln.group(1) if idln else "\t\t\t\t"      # IState children indent
        ind5 = ind4 + "\t"

        # Case B: has <IAction ...> but no _body -> inject _body before </IAction>
        mia = re.search(r'</IAction>', block)
        if "<IAction type=\"e\">" in block and mia:
            inject = "\n%s<_body type=\"a\">%s</_body>" % (ind5, body_val)
            nb = block[:mia.start()] + inject + "\n" + ind4 + block[mia.start():]
            # note: we re-add the same indent before </IAction>
            # simpler: insert right before the existing indent+</IAction>
            # Reconstruct cleanly:
            nb = re.sub(r'(\n\t*)</IAction>',
                        lambda mm: "\n%s<_body type=\"a\">%s</_body>%s</IAction>" % (ind5, body_val, mm.group(1)),
                        block, count=1)
            self.raw = self.raw[:b] + nb + self.raw[e:]
            return True

        # Case C: no _entryAction -> inject full block before </IState>
        new_guid = str(uuid.uuid4())
        entry = (
            "%s<_entryAction type=\"p\"><IAction type=\"e\">\n"
            "%s<_id type=\"a\">GUID %s</_id>\n"
            "%s<_myState type=\"a\">4096</_myState>\n"
            "%s<_rmmServerID type=\"a\">-1</_rmmServerID>\n"
            "%s<_body type=\"a\">%s</_body>\n"
            "%s</IAction>\n"
            "%s</_entryAction>\n"
        ) % (ind4, ind5, new_guid, ind5, ind5, ind5, body_val, ind4, ind4)
        mclose = re.search(r'(\n\t*)</IState>\s*$', block)
        if mclose:
            # Normal multi-line IState (real Rhapsody files): inject on its own
            # line just before the closing tag (proven path, unchanged).
            nb = block[:mclose.start()] + "\n" + entry + block[mclose.start()+1:]
        else:
            # Robustness fallback: single-line / unusual formatting. Inject the
            # entry-action as its own line right before the final </IState>.
            ci = block.rfind("</IState>")
            if ci < 0:
                return False
            ind3 = ind4[:-1] if ind4.endswith("\t") else ""
            nb = block[:ci] + "\n" + entry + ind3 + block[ci:]
        self.raw = self.raw[:b] + nb + self.raw[e:]
        return True

    def save(self, write: bool) -> str:
        if not write:
            return "DRY-RUN (no file written)"
        shutil.copyfile(self.path, self.path + ".bak")
        with open(self.path, "wb") as fh:
            fh.write(self._bom + self.raw.encode("utf-8"))
        return "WROTE %s (backup %s.bak)" % (self.path, self.path)

# ---------- port geometry ----------
def source_port_xy(l, t, port):
    if port == "right": return (l + NODE_W, t + NODE_H/2)
    if port == "left":  return (l, t + NODE_H/2)
    return (l + NODE_W/2, t + NODE_H)
def target_port_xy(l, t, port):
    if port == "left":  return (l, t + NODE_H/2)
    if port == "right": return (l + NODE_W, t + NODE_H/2)
    if port == "bottom":return (l + NODE_W/2, t + NODE_H)
    return (l + NODE_W/2, t)

# ============================================================================
# ANCHOR-SPREADING ROUTER  (v3.2.3)
# ----------------------------------------------------------------------------
# Rhapsody stores connector anchors (m_SourcePort / m_TargetPort) in NODE-LOCAL
# coordinates. Every node's local box is 0..1095 (x) by -17..1043 (y), center
# ~ (548, 513). We DO NOT move blocks and DO NOT write polyline waypoints
# (m_position). We only choose, per edge, WHICH border point each end attaches
# to, and SPREAD multiple lines that hit the same node-side so they stop
# stacking. Side selection follows the layout columns => lines that go right
# stay on the right, left stays left => no criss-cross for column layouts.
#
# Rule (matches the user's convention):
#   * incoming edges enter from the TOP (or the side facing the source),
#   * a decision's outgoing edges leave from LEFT / RIGHT (+ BOTTOM for 3-way),
#   * many lines converging on one node-side are fanned across that side.
# ============================================================================
LX0, LX1 = 0, 1095          # local box x-range
LY0, LY1 = -17, 1043        # local box y-range
LCX, LCY = 548, 513         # local center

def _side_local(side, frac=0.5):
    """Return a local (x,y) on the given border. frac in [0,1] positions the
    point along that border (0=start .. 1=end)."""
    if side == "right":
        y = LY0 + (LY1 - LY0) * frac
        return (LX1, int(round(y)))
    if side == "left":
        y = LY0 + (LY1 - LY0) * frac
        return (LX0, int(round(y)))
    if side == "bottom":
        x = LX0 + (LX1 - LX0) * frac
        return (int(round(x)), LY1)
    # top
    x = LX0 + (LX1 - LX0) * frac
    return (int(round(x)), LY0)

def _spread_fracs(k):
    """k evenly spaced fractions along a border with margins (never at corners)."""
    if k <= 1:
        return [0.5]
    lo, hi = 0.18, 0.82
    step = (hi - lo) / (k - 1)
    return [lo + step * i for i in range(k)]

def _infer_src_side(dx, dy):
    if abs(dx) <= 40 and dy > 0:   # target roughly below
        return "bottom"
    if abs(dx) <= 40 and dy < 0:   # target roughly above (loop-back)
        return "top"
    return "right" if dx > 0 else "left"

def _infer_tgt_side(dx, dy):
    # side of TARGET that faces the SOURCE
    if abs(dx) <= 40 and dy > 0:   # source above -> enter top
        return "top"
    if abs(dx) <= 40 and dy < 0:   # source below -> enter bottom
        return "bottom"
    return "left" if dx > 0 else "right"  # source to the left -> enter left

def route_edges(doc, plan, name_to_node):
    """Compute spread anchor points for every plan edge and apply them via the
    RAW port setter. Returns a list of report strings. RPY-ASCII safe."""
    report = []
    # name -> (gid, tx, ty)
    geo = {}
    for name, n in name_to_node.items():
        geo[name] = (doc.node_id(n), *(doc.node_translate(n) or (0.0, 0.0)))

    # 1) decide sides per edge (respect plan-provided ports, else infer)
    edge_info = []  # (frm, to, src_side, tgt_side)
    for e in plan.get("edges", []):
        frm, to = e.get("from"), e.get("to")
        if frm not in geo or to not in geo:
            continue
        _, sx, sy = geo[frm]; _, tx, ty = geo[to]
        dx, dy = (tx - sx), (ty - sy)
        s_side = e.get("src_port") or _infer_src_side(dx, dy)
        t_side = e.get("dst_port") or _infer_tgt_side(dx, dy)
        edge_info.append([frm, to, s_side, t_side])

    # 2) group by (node, side, S/T) and assign spread fractions.
    #    Order within a group by the OTHER endpoint's coordinate to minimise
    #    crossings (e.g. edges entering a node's right side sorted by source y).
    from collections import defaultdict
    src_groups = defaultdict(list)   # (frm, side) -> list of edge idx
    tgt_groups = defaultdict(list)
    for i, (frm, to, s_side, t_side) in enumerate(edge_info):
        src_groups[(frm, s_side)].append(i)
        tgt_groups[(to, t_side)].append(i)

    src_frac = {}   # edge idx -> frac
    tgt_frac = {}
    def order_key_other(i, at_source):
        frm, to, s_side, t_side = edge_info[i]
        # sort by the opposite node's along-border axis
        other = to if at_source else frm
        _, ox, oy = geo[other]
        side = s_side if at_source else t_side
        return oy if side in ("left", "right") else ox

    for (node, side), idxs in src_groups.items():
        idxs.sort(key=lambda i: order_key_other(i, True))
        for f, i in zip(_spread_fracs(len(idxs)), idxs):
            src_frac[i] = f
    for (node, side), idxs in tgt_groups.items():
        idxs.sort(key=lambda i: order_key_other(i, False))
        for f, i in zip(_spread_fracs(len(idxs)), idxs):
            tgt_frac[i] = f

    # 3) apply
    applied = 0
    for i, (frm, to, s_side, t_side) in enumerate(edge_info):
        sgid = geo[frm][0]; tgid = geo[to][0]
        sp = _side_local(s_side, src_frac.get(i, 0.5))
        tp = _side_local(t_side, tgt_frac.get(i, 0.5))
        ok = doc.set_edge_ports_raw(sgid, tgid, sp, tp)
        report.append("ROUTE %s->%s: %s%s -> %s%s %s" %
                      (frm, to, s_side, sp, t_side, tp, "ok" if ok else "skip"))
        if ok:
            applied += 1
    report.append("-- routed %d/%d edges (anchor-spread, no waypoints) --" %
                  (applied, len(edge_info)))
    return report

# ---------- diagram-unit locate ----------
def find_project_dir(project_path):
    p = os.path.abspath(project_path); base = os.path.dirname(p)
    stem = os.path.splitext(os.path.basename(p))[0]
    for c in (os.path.join(base, stem + "_rpy"), os.path.join(base, stem), base):
        if os.path.isdir(c): return c
    return base

def do_locate(root_dir, diagram):
    import glob
    out = ["LOCATE diagram '%s' under: %s" % (diagram, root_dir)]
    files = glob.glob(os.path.join(root_dir, "**", "*.sbsx"), recursive=True)
    out.append("scanning %d .sbsx unit(s)..." % len(files))
    hits = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                head = fh.read()
            if diagram not in head: continue
            d = SbsxRaw(f); sc = d.statechart_for_diagram(diagram)
            n = len(d.graph_nodes_for_frame(sc)) if sc is not None else 0
            hits.append((n, f))
        except Exception as ex:
            out.append("   (skip %s: %s)" % (os.path.basename(f), ex))
    hits.sort(reverse=True)
    if not hits: out.append("No unit mentions the diagram.")
    else:
        out.append("candidates (nodes  file):")
        for n, f in hits[:10]:
            out.append("   %4d  %s%s" % (n, f, "  <== PATCH THIS" if n > 0 else ""))
    return "\n".join(out)

def do_inspect(doc, diagram):
    out = ["SBSX: %s" % doc.path, "diagram: %s" % diagram]
    sc = doc.statechart_for_diagram(diagram)
    out.append("CGIStateChart id: %s" % (_ctext(sc, "_id") if sc is not None else None))
    out.append("activity frame (m_pRoot): %s" % doc.root_frame(sc))
    nodes = doc.graph_nodes_for_frame(sc) if sc is not None else []
    out.append("scoped graphical nodes (m_pParent==frame): %d" % len(nodes))
    for n in nodes[:25]:
        tp = doc.node_translate(n); hid = doc.node_model_hid(n)
        st = doc.istate_id_to_elem.get(hid)
        body = None
        if st is not None:
            for d in st.iter():
                if ln(d) == "_body": body = (d.text or "")[:40]; break
        out.append("   at=%s  model=%s  body=%r" % (tp, hid, body))
    return "\n".join(out)

def do_patch(doc, diagram, plan, write, pos_tol=8.0, route=True):
    rep = []
    sc = doc.statechart_for_diagram(diagram)
    gnodes = doc.graph_nodes_for_frame(sc) if sc is not None else []
    if not gnodes:
        rep.append("ABORT: 0 nodes scoped. Run `locate`. (No changes.)"); return rep
    node_pos = [(doc.node_translate(n), n) for n in gnodes if doc.node_translate(n)]
    def nearest(x, y):
        best=bd=None
        for (tx,ty),n in node_pos:
            d=abs(tx-x)+abs(ty-y)
            if bd is None or d<bd: bd,best=d,n
        return best if (best is not None and bd<=pos_tol) else None
    name_to_node={}
    matched=0
    for name, spec in plan.get("nodes",{}).items():
        x,y=spec.get("x"),spec.get("y")
        gn=nearest(x,y) if x is not None else None
        if gn is None:
            rep.append("NODE %s: skip (no graphic within %gpx of %s,%s)"%(name,pos_tol,x,y)); continue
        name_to_node[name]=gn; matched+=1
        did_text=False
        if spec.get("text") is not None:
            hid=doc.node_model_hid(gn)
            did_text=doc.set_action_body_raw(hid, spec["text"])
        did_pos=doc.set_node_position_raw(doc.node_id(gn), x, y)
        rep.append("NODE %s: body=%s pos=%s"%(name,"ok" if did_text else "n/a","ok" if did_pos else "skip"))
    rep.append("-- matched %d/%d plan nodes by position --"%(matched,len(plan.get("nodes",{}))))

    if route:
        # Anchor-spreading router (default): distinct, fanned-out connector
        # anchors so converging lines don't overlap. No block moves, no
        # polyline waypoints -> RPY-ASCII safe.
        rep.extend(route_edges(doc, plan, name_to_node))
    else:
        # Legacy single-anchor mode (kept for --no-route).
        pos={n:(s.get("x"),s.get("y")) for n,s in plan.get("nodes",{}).items()}
        for e in plan.get("edges",[]):
            frm,to=e.get("from"),e.get("to")
            sg,tg=name_to_node.get(frm),name_to_node.get(to)
            if sg is None or tg is None:
                rep.append("EDGE %s->%s: skip (endpoint unmatched)"%(frm,to)); continue
            sx,sy=pos.get(frm,(0,0)); tx,ty=pos.get(to,(0,0))
            spx=source_port_xy(sx,sy,e.get("src_port","bottom"))
            dpx=target_port_xy(tx,ty,e.get("dst_port","top"))
            ok=doc.set_edge_ports_raw(doc.node_id(sg),doc.node_id(tg),spx,dpx)
            rep.append("EDGE %s->%s: ports=%s src=%s dst=%s"%(frm,to,"ok" if ok else "skip",e.get("src_port"),e.get("dst_port")))

    # Guards: add [YES]/[NO]/<label> to edges that carry a label (decision
    # branches). Mirrors the file's own working ILabel->IGuard structure.
    gcount = 0
    for e in plan.get("edges", []):
        gt = _guard_text(e.get("label"))
        if gt is None:
            continue
        frm, to = e.get("from"), e.get("to")
        sg, tg = name_to_node.get(frm), name_to_node.get(to)
        if sg is None or tg is None:
            continue
        tid = transition_id_for_edge(doc, doc.node_id(sg), doc.node_id(tg))
        if tid and set_edge_guard_raw(doc, tid, gt):
            gcount += 1
            rep.append("GUARD %s->%s: [%s] ok" % (frm, to, gt))
    rep.append("-- guards set on %d edges --" % gcount)

    rep.append(doc.save(write))
    return rep

# ============================================================================
# GUARD INJECTION (v3.2.4)  -- adds [YES]/[NO]/<label> to condition edges
# Mirrors the file's own working structure (337 examples):
#   ITransition -> AggregatesList -> ILabel
#   ILabel      -> AggregatesList -> IGuard
#   IGuard      -> <_body>TEXT</_body>
# RAW-TEXT / RPY-ASCII safe. Only touches the specific ILabel and adds one
# sibling IGuard element.
# ============================================================================
import uuid as _uuid

def _guard_text(label):
    if label is None: return None
    s = str(label).strip()
    if not s: return None
    low = s.lower()
    if low in ("yes","true","y"): return "YES"
    if low in ("no","false","n"): return "NO"
    return s  # keep richer branch labels (Running, DCM_INITIAL, ...) verbatim

def _find_block(raw, tag, gid):
    i = raw.find('<_id type="a">%s</_id>' % gid)
    if i < 0: return None
    b = raw.rfind('<%s type="e">' % tag, 0, i)
    e = raw.find('</%s>' % tag, i)
    if b < 0 or e < 0: return None
    return (b, e + len('</%s>' % tag))

def transition_id_for_edge(doc, src_gid, tgt_gid):
    """CGITrans(src->tgt).m_pModelObject._hid == ITransition id."""
    span = doc._cgitrans_block_span(src_gid, tgt_gid)
    if not span: return None
    b, e = span
    blk = doc.raw[b:e]
    m = re.search(r'<m_pModelObject type="r">.*?<_hid type="a">([^<]*)</_hid>', blk, re.DOTALL)
    return m.group(1).strip() if m else None

def set_edge_guard_raw(doc, transition_id, text):
    """Attach/overwrite a guard on the ITransition's ILabel. Returns bool."""
    tspan = _find_block(doc.raw, "ITransition", transition_id)
    if not tspan: return False
    tb, te = tspan
    tblk = doc.raw[tb:te]
    # ITransition -> first aggregate = ILabel id
    mlab = re.search(r'<AggregatesList type="e">\s*<value>(GUID [0-9a-f-]+)</value>', tblk)
    if not mlab: return False
    label_id = mlab.group(1)
    lspan = _find_block(doc.raw, "ILabel", label_id)
    if not lspan: return False
    lb, le = lspan
    lblk = doc.raw[lb:le]

    # Case 1: ILabel already links a guard (AggregatesList) -> replace IGuard body
    mg = re.search(r'<AggregatesList type="e">\s*<value>(GUID [0-9a-f-]+)</value>', lblk)
    if mg:
        guard_id = mg.group(1)
        gspan = _find_block(doc.raw, "IGuard", guard_id)
        if gspan:
            gb, ge = gspan
            gblk = doc.raw[gb:ge]
            nb = re.sub(r'(<_body type="a">).*?(</_body>)',
                        lambda mm: mm.group(1) + text + mm.group(2), gblk, count=1, flags=re.DOTALL)
            if '<_body' not in gblk:
                nb = gblk.replace('</IGuard>', '\t\t\t\t<_body type="a">%s</_body>\n\t\t\t</IGuard>' % text)
            doc.raw = doc.raw[:gb] + nb + doc.raw[ge:]
            return True

    # Case 2: no guard yet -> create IGuard sibling + link from ILabel
    gid = "GUID " + str(_uuid.uuid4())
    # detect child indent from the ILabel _id line
    mind = re.search(r'\n(\t*)<_id type="a">%s</_id>' % re.escape(label_id), lblk)
    ind4 = mind.group(1) if mind else "\t\t\t\t"
    ind3 = ind4[:-1] if ind4.endswith("\t") else "\t\t\t"
    # remove a stray "<_itsGuard>NULL</_itsGuard>" line to match the working shape
    lblk2 = re.sub(r'\n\t*<_itsGuard>NULL</_itsGuard>', '', lblk, count=1)
    # inject AggregatesList before </ILabel>
    agg = ('\n%s<AggregatesList type="e">\n%s\t<value>%s</value>\n%s</AggregatesList>'
           % (ind4, ind4, gid, ind4))
    lblk2 = re.sub(r'\n\t*</ILabel>', agg + '\n' + ind3 + '</ILabel>', lblk2, count=1)
    # write ILabel back
    doc.raw = doc.raw[:lb] + lblk2 + doc.raw[le:]
    # recompute end (length changed) and insert sibling IGuard right after </ILabel>
    le2 = doc.raw.find('</ILabel>', lb) + len('</ILabel>')
    guard_el = ('\n%s<IGuard type="e">\n%s<_id type="a">%s</_id>\n'
                '%s<_modifiedTimeWeak type="a">1.2.1990::0:0:0</_modifiedTimeWeak>\n'
                '%s<_modifiedTime type="a">1.2.1990::0:0:0</_modifiedTime>\n'
                '%s<_body type="a">%s</_body>\n%s</IGuard>'
                % (ind3, ind4, gid, ind4, ind4, ind4, text, ind3))
    doc.raw = doc.raw[:le2] + guard_el + doc.raw[le2:]
    return True

def _cli(argv=None):
    ap=argparse.ArgumentParser(description="Rhapsody v109 SBSX patcher (RPY-ASCII safe)")
    sub=ap.add_subparsers(dest="cmd",required=True)
    for nm in ("inspect","patch"):
        p=sub.add_parser(nm); p.add_argument("--sbsx",required=True); p.add_argument("--diagram",required=True)
        if nm=="patch":
            p.add_argument("--plan",required=True); p.add_argument("--write",action="store_true")
            p.add_argument("--no-route", dest="route", action="store_false",
                           help="disable the anchor-spreading router (legacy single-anchor)")
            p.set_defaults(route=True)
    pl=sub.add_parser("locate"); pl.add_argument("--root",required=True); pl.add_argument("--diagram",required=True)
    a=ap.parse_args(argv)
    if a.cmd=="locate": print(do_locate(a.root,a.diagram)); return 0
    doc=SbsxRaw(a.sbsx)
    if a.cmd=="inspect": print(do_inspect(doc,a.diagram)); return 0
    plan=json.load(open(a.plan,encoding="utf-8"))
    for l in do_patch(doc,a.diagram,plan,write=a.write,route=a.route): print(l)
    return 0

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO); sys.exit(_cli())
