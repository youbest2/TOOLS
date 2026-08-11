# rhapsody_flowgen/flow_utils.py
# NEW in hybrid_v3 - Single source of truth for flow-graph structure:
#   * Robust start / end detection (topology-based, not label-string based)
#   * Cycle-safe reachability + longest-path levels
#   * Explicit merge-node insertion so Rhapsody's "one incoming edge per
#     Condition" rule is satisfied WITHOUT dropping edges or raising.
#
# This module is deliberately dependency-free (pure Python, stdlib only) so it
# can be imported by layout.py, rhapsody_interface.py and the test-suite alike.
#
# It is duck-typed: any object exposing `.id`, `.label`, `.node_type`
# (mermaid_parser.Node) and `.source_id`, `.target_id`, `.label`
# (mermaid_parser.Edge) works.

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Dict, List, Sequence, Set, Tuple

__all__ = [
    "build_adjacency",
    "detect_start",
    "detect_ends",
    "reachable_from",
    "find_unreachable",
    "longest_path_levels",
    "insert_merge_nodes",
    "validate_flow",
]

# Labels that *hint* at a start/end when topology alone is ambiguous.
_START_HINTS = ("start", "begin", "entry")
_END_HINTS = ("return", "end", "stop", "exit", "finish")


def build_adjacency(nodes: Sequence, edges: Sequence):
    """Return (out_edges, in_edges) dicts keyed by node id -> list[edge]."""
    out_edges: Dict[str, list] = {n.id: [] for n in nodes}
    in_edges: Dict[str, list] = {n.id: [] for n in nodes}
    for e in edges:
        # Guard against edges that reference an undefined node id.
        out_edges.setdefault(e.source_id, []).append(e)
        in_edges.setdefault(e.target_id, []).append(e)
        out_edges.setdefault(e.target_id, out_edges.get(e.target_id, []))
        in_edges.setdefault(e.source_id, in_edges.get(e.source_id, []))
    return out_edges, in_edges


def detect_start(nodes: Sequence, edges: Sequence) -> str:
    """
    Determine the start node id using topology first, labels second.

    Order of preference:
      1) the unique node with **no incoming edges**;
      2) if several have no incoming edges, the one whose label starts with a
         start-hint ('start'/'begin'/'entry'), else the first of them;
      3) if every node has an incoming edge (fully cyclic), the node whose
         label starts with a start-hint;
      4) fallback: first node in the list.

    This fixes the original bug where start was found only via
    `label.lower() == "start"`, which failed for labels like
    'Start: ApplFblNvWriteDtcList(...)'.
    """
    if not nodes:
        raise ValueError("detect_start called with no nodes")

    _, in_edges = build_adjacency(nodes, edges)
    no_incoming = [n for n in nodes if len(in_edges.get(n.id, [])) == 0]

    if len(no_incoming) == 1:
        return no_incoming[0].id

    if no_incoming:
        for n in no_incoming:
            if (n.label or "").strip().lower().startswith(_START_HINTS):
                return n.id
        return no_incoming[0].id

    # Fully cyclic: no source node. Use a label hint if present.
    for n in nodes:
        if (n.label or "").strip().lower().startswith(_START_HINTS):
            return n.id
    return nodes[0].id


def detect_ends(nodes: Sequence, edges: Sequence) -> List[str]:
    """
    Return the list of end node ids (nodes with **no outgoing edges**).
    If none exist (fully cyclic), fall back to nodes whose label matches an
    end-hint, else an empty list.
    """
    out_edges, _ = build_adjacency(nodes, edges)
    ends = [n.id for n in nodes if len(out_edges.get(n.id, [])) == 0]
    if ends:
        return ends
    return [n.id for n in nodes if (n.label or "").strip().lower().startswith(_END_HINTS)]


def reachable_from(start_id: str, nodes: Sequence, edges: Sequence) -> Set[str]:
    """Forward-reachable set from start_id (cycle-safe BFS)."""
    out_edges, _ = build_adjacency(nodes, edges)
    seen: Set[str] = set()
    q = deque([start_id])
    while q:
        nid = q.popleft()
        if nid in seen:
            continue
        seen.add(nid)
        for e in out_edges.get(nid, []):
            if e.target_id not in seen:
                q.append(e.target_id)
    return seen


def find_unreachable(nodes: Sequence, edges: Sequence, start_id: str = None) -> Set[str]:
    """Node ids not forward-reachable from the (detected) start."""
    start_id = start_id or detect_start(nodes, edges)
    return {n.id for n in nodes} - reachable_from(start_id, nodes, edges)


def longest_path_levels(nodes: Sequence, edges: Sequence, start_id: str = None) -> Dict[str, int]:
    """
    Assign each node a vertical level = longest forward distance from start,
    computed on the DAG obtained by ignoring back-edges (so loops don't cause
    infinite recursion). Unreachable nodes are appended below the deepest level.

    Deterministic and O(V+E).
    """
    start_id = start_id or detect_start(nodes, edges)
    out_edges, _ = build_adjacency(nodes, edges)

    # 1) Classify back-edges via DFS colouring (WHITE/GREY/BLACK).
    WHITE, GREY, BLACK = 0, 1, 2
    color = defaultdict(lambda: WHITE)
    back_edges: Set[Tuple[str, str]] = set()

    def dfs(u: str):
        color[u] = GREY
        for e in out_edges.get(u, []):
            v = e.target_id
            if color[v] == GREY:
                back_edges.add((u, v))          # loop back-edge
            elif color[v] == WHITE:
                dfs(v)
        color[u] = BLACK

    # Start DFS from the start node, then from any unvisited node (disconnected).
    import sys
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 10000))
    try:
        dfs(start_id)
        for n in nodes:
            if color[n.id] == WHITE:
                dfs(n.id)
    finally:
        sys.setrecursionlimit(old_limit)

    # 2) Kahn longest-path on the DAG (edges minus back-edges).
    dag_out = defaultdict(list)
    indeg = {n.id: 0 for n in nodes}
    for e in edges:
        if (e.source_id, e.target_id) in back_edges:
            continue
        dag_out[e.source_id].append(e.target_id)
        indeg[e.target_id] = indeg.get(e.target_id, 0) + 1
        indeg.setdefault(e.source_id, indeg.get(e.source_id, 0))

    level = {n.id: 0 for n in nodes}
    q = deque([nid for nid, d in indeg.items() if d == 0])
    # Guarantee the detected start is processed first for stable output.
    if start_id in q:
        q.remove(start_id)
        q.appendleft(start_id)

    visited_count = 0
    while q:
        u = q.popleft()
        visited_count += 1
        for v in dag_out.get(u, []):
            if level.get(v, 0) < level.get(u, 0) + 1:
                level[v] = level[u] + 1
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    # 3) Unreached / leftover nodes (rare) go below the deepest known level.
    if level:
        deepest = max(level.values())
    else:
        deepest = 0
    for n in nodes:
        if n.id not in level:
            deepest += 1
            level[n.id] = deepest
    return level


def insert_merge_nodes(nodes: Sequence, edges: Sequence, node_cls=None, edge_cls=None):
    """
    Non-destructively insert explicit MERGE (action) nodes in front of any
    *Condition* (decision) node that has more than one incoming edge, because
    Rhapsody forbids multiple incoming control-flows on a decision.

    Returns (new_nodes, new_edges) as fresh lists. Original inputs are untouched.

    node_cls / edge_cls default to the caller's node/edge classes (inferred from
    the first element) so we return the *same* concrete types the pipeline uses.
    """
    if not nodes:
        return list(nodes), list(edges)

    if node_cls is None:
        node_cls = type(nodes[0])
    if edge_cls is None and edges:
        edge_cls = type(edges[0])
    elif edge_cls is None:
        edge_cls = node_cls  # not used when there are no edges

    _, in_edges = build_adjacency(nodes, edges)
    condition_ids = {n.id for n in nodes if getattr(n, "node_type", "action") == "condition"}

    # Which condition nodes need a merge in front of them?
    needing = [cid for cid in condition_ids if len(in_edges.get(cid, [])) > 1]
    if not needing:
        return list(nodes), list(edges)

    new_nodes = list(nodes)
    new_edges = []
    merge_counter = 0
    # Build a quick set of existing ids to avoid collisions.
    existing_ids = {n.id for n in nodes}

    # Map: condition id -> merge node id
    merge_for = {}
    for cid in needing:
        merge_counter += 1
        mid = f"MERGE_{cid}"
        while mid in existing_ids:
            mid = f"MERGE_{cid}_{merge_counter}"
            merge_counter += 1
        existing_ids.add(mid)
        merge_for[cid] = mid
        # Create the merge node (an Action acting as a UML merge/junction).
        new_nodes.append(_make_node(node_cls, mid, "merge", "action"))
        logging.info("Inserted merge node '%s' before condition '%s'", mid, cid)

    # Re-wire edges: anything that targeted a merged condition now targets the
    # merge node; the merge node has exactly one outgoing edge to the condition.
    for e in edges:
        if e.target_id in merge_for:
            new_edges.append(_make_edge(edge_cls, e.source_id, merge_for[e.target_id], getattr(e, "label", None)))
        else:
            new_edges.append(_make_edge(edge_cls, e.source_id, e.target_id, getattr(e, "label", None)))
    for cid, mid in merge_for.items():
        new_edges.append(_make_edge(edge_cls, mid, cid, None))

    return new_nodes, new_edges


def _make_node(node_cls, nid, label, node_type):
    """Construct a node regardless of NamedTuple field order or __init__ order."""
    # mermaid_parser.Node is NamedTuple(id, label, node_type)
    try:
        return node_cls(nid, label, node_type)
    except TypeError:
        # layout.Node.__init__(self, id, node_type, label)
        return node_cls(nid, node_type, label)


def _make_edge(edge_cls, src, tgt, label):
    try:
        return edge_cls(src, tgt, label)
    except TypeError:
        return edge_cls(src, tgt)


def validate_flow(nodes: Sequence, edges: Sequence) -> Dict[str, object]:
    """
    Structural report used by tests and the CLI. Never raises; returns a dict:
        { 'start', 'ends', 'unreachable', 'multi_in_conditions', 'ok' }
    """
    start = detect_start(nodes, edges)
    ends = detect_ends(nodes, edges)
    unreachable = sorted(find_unreachable(nodes, edges, start))
    _, in_edges = build_adjacency(nodes, edges)
    multi_in_conditions = sorted(
        n.id for n in nodes
        if getattr(n, "node_type", "action") == "condition"
        and len(in_edges.get(n.id, [])) > 1
    )
    ok = (not unreachable) and (not multi_in_conditions) and bool(ends)
    return {
        "start": start,
        "ends": ends,
        "unreachable": unreachable,
        "multi_in_conditions": multi_in_conditions,
        "ok": ok,
    }
