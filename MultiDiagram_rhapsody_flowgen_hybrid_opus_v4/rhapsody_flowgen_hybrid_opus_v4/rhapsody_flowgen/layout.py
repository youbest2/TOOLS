# layout.py
# hybrid_v3 - Single deterministic layout path.
#
# WHAT CHANGED vs hybrid_v2
#   * Start detection no longer relies on `label.lower() == "start"`. It uses
#     flow_utils.detect_start (node with no incoming edge, label hints as
#     tie-breaker). This fixes real labels like
#     'Start: ApplFblNvWriteDtcList(DtcTable_p)'.
#   * `compute_activity_layout` is now ONE deterministic pass (longest-path
#     levels + main-axis placement). It no longer depends on the stateful,
#     non-deterministic `layout_block_vertical*` helpers.
#   * The legacy helpers (analyze_blocks, layout_block, layout_block_vertical,
#     layout_block_vertical_strict) are RETAINED for backward-compatible imports
#     but are deprecated and no longer on the active path.
#
# PUBLIC API PRESERVED (imported elsewhere):
#   Node, Edge, Block, analyze_blocks, assign_vertical_levels,
#   find_main_flow_path, compute_activity_layout, check_continuity

from typing import List, Dict, Tuple, Optional
import logging

try:
    # Preferred: package-relative import (matches how the app runs).
    from rhapsody_flowgen.flow_utils import (
        detect_start, detect_ends, longest_path_levels,
        reachable_from, build_adjacency,
    )
except Exception:  # pragma: no cover - allow running as a loose script
    from flow_utils import (
        detect_start, detect_ends, longest_path_levels,
        reachable_from, build_adjacency,
    )


# ---------------------------------------------------------------------------
# Light-weight structural classes (kept for backward-compatibility).  Note the
# active layout path is duck-typed and works directly with mermaid_parser.Node
# / mermaid_parser.Edge as well.
# ---------------------------------------------------------------------------
class Node:
    def __init__(self, id: str, node_type: str, label: str):
        self.id = id
        self.node_type = node_type
        self.label = label


class Edge:
    def __init__(self, source_id: str, target_id: str, label: str = ''):
        self.source_id = source_id
        self.target_id = target_id
        self.label = label


class Block:
    def __init__(self, block_type: str, nodes=None, children=None, entry=None, exit=None):
        self.block_type = block_type
        self.nodes = nodes or []
        self.children = children or []
        self.entry = entry
        self.exit = exit


# ===========================================================================
# ACTIVE, DETERMINISTIC LAYOUT
# ===========================================================================
def compute_activity_layout(nodes: List, edges: List,
                            x_center: int = 800, y_start: int = 200,
                            x_offset: int = 260, y_step: int = 120) -> Dict[str, Tuple[int, int]]:
    """
    Deterministic top-to-bottom activity layout.

      * Main flow (longest start->end path) is pinned to x_center.
      * Non-main nodes at the same level fan out left/right by x_offset.
      * y = y_start + level * y_step, where level = longest path distance.

    Returns {node_id: (x, y)}.  Never mutates the inputs.
    """
    if not nodes:
        return {}

    start_id = detect_start(nodes, edges)
    levels = longest_path_levels(nodes, edges, start_id)
    main_path = set(find_main_flow_path(nodes, edges))

    # Group node ids by level for horizontal spreading.
    by_level: Dict[int, List[str]] = {}
    for n in nodes:
        by_level.setdefault(levels.get(n.id, 0), []).append(n.id)

    coords: Dict[str, Tuple[int, int]] = {}
    for level, ids in sorted(by_level.items()):
        y = y_start + level * y_step
        # Main-path node (if any at this level) keeps x_center.
        main_here = [nid for nid in ids if nid in main_path]
        other_here = [nid for nid in ids if nid not in main_path]

        used_x = set()
        for nid in main_here:
            coords[nid] = (x_center, y)
            used_x.add(x_center)

        # Fan the others symmetrically around the center, skipping used slots.
        # Order is stable (sorted) so output is deterministic.
        for k, nid in enumerate(sorted(other_here)):
            # +1,-1,+2,-2,... pattern
            step = (k // 2) + 1
            sign = 1 if (k % 2 == 0) else -1
            x = x_center + sign * step * x_offset
            while x in used_x:
                x += x_offset
            used_x.add(x)
            coords[nid] = (x, y)

    # Safety net: guarantee every node is placed.
    for n in nodes:
        coords.setdefault(n.id, (x_center, y_start + levels.get(n.id, 0) * y_step))

    logging.debug("compute_activity_layout: start=%s, %d nodes placed", start_id, len(coords))
    return coords


def find_main_flow_path(nodes: List, edges: List,
                        start_label: str = None, end_label: str = None) -> list:
    """
    Longest simple forward path from the detected start to any detected end
    node.  Robust to arbitrary labels (topology-based) and to cycles (simple
    paths only, so loops cannot recurse infinitely).

    `start_label` / `end_label` are accepted for backward compatibility but are
    only used as *hints*; detection is topology-first.
    """
    if not nodes:
        return []

    out_edges, _ = build_adjacency(nodes, edges)
    start_id = detect_start(nodes, edges)
    ends = set(detect_ends(nodes, edges))
    # Optional label hint override for the end.
    if end_label:
        for n in nodes:
            if (n.label or "").strip().lower() == end_label.strip().lower():
                ends = {n.id}
                break
    if not ends:
        ends = {nodes[-1].id}

    longest = []

    def dfs(path, node_id):
        nonlocal longest
        if node_id in ends:
            if len(path) > len(longest):
                longest = path[:]
            # continue exploring in case a longer path reaches another end
        for e in out_edges.get(node_id, []):
            if e.target_id not in path:            # simple path -> loop-safe
                dfs(path + [e.target_id], e.target_id)

    import sys
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 10000))
    try:
        dfs([start_id], start_id)
    finally:
        sys.setrecursionlimit(old)
    return longest


def check_continuity(nodes: List, edges: List,
                     start_label: str = None, end_label: str = None) -> bool:
    """
    True if at least one detected end node is reachable from the detected start.
    Topology-based (was previously label-string based).
    """
    if not nodes:
        return False
    start_id = detect_start(nodes, edges)
    ends = set(detect_ends(nodes, edges))
    if not ends:
        logging.warning("check_continuity: no end node (no node without outgoing edges).")
        return False
    reach = reachable_from(start_id, nodes, edges)
    ok = bool(ends & reach)
    if ok:
        logging.info("Continuity OK: start '%s' reaches an end node.", start_id)
    else:
        logging.warning("Discontinuity: no end node reachable from start '%s'.", start_id)
    return ok


def assign_vertical_levels(nodes: List, edges: List, start_label: str = None) -> Dict[str, int]:
    """
    Backward-compatible wrapper: returns {node_id: level}.  Now cycle-safe and
    start-correct (delegates to flow_utils.longest_path_levels).
    """
    if not nodes:
        return {}
    start_id = detect_start(nodes, edges)
    return longest_path_levels(nodes, edges, start_id)


# ===========================================================================
# DEPRECATED LEGACY HELPERS (retained for import compatibility only)
# Not on the active path.  Kept so external code / older callers do not break.
# ===========================================================================
def analyze_blocks(nodes: List, edges: List) -> Block:
    """DEPRECATED. Structural block detection from hybrid_v2. Unused by the
    active layout path; retained for backward compatibility."""
    node_map = {n.id: n for n in nodes}
    out_edges = {n.id: [e for e in edges if e.source_id == n.id] for n in nodes}
    in_edges = {n.id: [e for e in edges if e.target_id == n.id] for n in nodes}
    visited = set()

    def detect_block(node_id: str) -> Optional[Block]:
        if node_id in visited:
            return None
        visited.add(node_id)
        node = node_map[node_id]
        outgoing = out_edges.get(node_id, [])
        incoming = in_edges.get(node_id, [])
        if node.node_type == 'condition' and len(outgoing) > 1:
            children = [detect_block(e.target_id) for e in outgoing]
            return Block('branch', entry=node_id, children=[c for c in children if c])
        elif len(incoming) > 1:
            return Block('merge', exit=node_id, nodes=[node_id])
        else:
            seq = [node_id]
            cur = node_id
            while True:
                nxt = out_edges.get(cur, [])
                if len(nxt) != 1:
                    break
                nn = nxt[0].target_id
                if nn in visited or node_map[nn].node_type == 'condition':
                    break
                visited.add(nn)
                seq.append(nn)
                cur = nn
            return Block('sequence', nodes=seq, entry=seq[0], exit=seq[-1])

    root = detect_block(nodes[0].id)
    for node in nodes:
        if node.id not in visited:
            extra = detect_block(node.id)
            if extra:
                root = Block('branch', children=[root, extra], entry=None)
    return root


def layout_block(*args, **kwargs):  # pragma: no cover - deprecated
    """DEPRECATED and inert. Superseded by compute_activity_layout."""
    logging.debug("layout_block() is deprecated and no longer used.")
    return (0, 0, 0, 0)


def layout_block_vertical(*args, **kwargs):  # pragma: no cover - deprecated
    """DEPRECATED and inert. Superseded by compute_activity_layout."""
    logging.debug("layout_block_vertical() is deprecated and no longer used.")
    return None


def layout_block_vertical_strict(*args, **kwargs):  # pragma: no cover - deprecated
    """DEPRECATED and inert. Superseded by compute_activity_layout."""
    logging.debug("layout_block_vertical_strict() is deprecated and no longer used.")
    return None


if __name__ == "__main__":
    import sys
    try:
        from rhapsody_flowgen.mermaid_parser import parse_mermaid_file
    except Exception:
        from mermaid_parser import parse_mermaid_file

    if len(sys.argv) < 2:
        print("Usage: python layout.py <path_to_mermaid_file>")
        sys.exit(1)

    nodes, edges = parse_mermaid_file(sys.argv[1])
    coords = compute_activity_layout(nodes, edges)
    print("Start node:", detect_start(nodes, edges))
    print("End node(s):", detect_ends(nodes, edges))
    print("Continuity:", check_continuity(nodes, edges))
    print("Computed Coordinates (top -> bottom):")
    for nid, (x, y) in sorted(coords.items(), key=lambda kv: (kv[1][1], kv[1][0])):
        print(f"  {nid}: ({x}, {y})")
