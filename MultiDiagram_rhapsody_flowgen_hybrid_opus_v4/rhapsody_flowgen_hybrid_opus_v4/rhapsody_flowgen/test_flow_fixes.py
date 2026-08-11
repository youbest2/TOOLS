# rhapsody_flowgen/test_flow_fixes.py
# hybrid_v3 regression tests (pure Python; no Rhapsody / win32com / Graphviz).
#
# Covers the specific bugs fixed in hybrid_v3:
#   1. Start detection works for non-"start" labels (topology-based).
#   2. End detection finds the true sink.
#   3. Deterministic layout pins the main flow to a single X axis and is stable
#      across repeated runs.
#   4. Merge-node insertion removes >1-incoming edges on Condition nodes without
#      dropping any original connectivity.
#   5. No node is left unplaced; continuity holds on the sample flow.

import tempfile
from pathlib import Path

from rhapsody_flowgen.mermaid_parser import parse_mermaid_file, Node, Edge
from rhapsody_flowgen import flow_utils
from rhapsody_flowgen.layout import compute_activity_layout, find_main_flow_path, check_continuity


SAMPLE = """flowchart TD
    A[Start] --> B[Check Sensor Status]
    B --> C[Check Lens Calibration]
    C --> D1{Is Sensor Active?}
    D1 -- Yes --> D2{Is Lens Calibrated?}
    D1 -- No --> X1[Skip Lens Check]
    D2 -- Yes --> E2[Proceed]
    D2 -- No --> E1[Calibrate Lens]
    E1 --> X2[Sensor Check Complete]
    E2 --> X2
    X1 --> X2
    X2 --> F1{Frame Rate > 60?}
    F1 -- Yes --> F2{Exposure > 40?}
    F1 -- No --> F3{Exposure < 60?}
    F2 -- Yes --> G1[Reduce Exposure]
    F2 -- No --> G3[Exposure Optimal]
    F3 -- Yes --> G2[Increase Exposure]
    F3 -- No --> G3
    G1 --> H[Capture 5 Frames]
    G2 --> H
    G3 --> H
    H --> I[Initialize Camera System]
    I --> J1{Retry Count == 3?}
    J1 -- Yes --> K1[Initialization Success]
    J1 -- No --> J2{Retry Count < 5?}
    J2 -- Yes --> I
    J2 -- No --> K2[Initialization Failed]
    K1 --> Z1[Set Overall result = OK]
    K2 --> Z2[Set Overall result = FAILED]
    Z1 --> Z[Return Overall result]
    Z2 --> Z
"""

# A flow whose start label is NOT "start" (the real-world failure case).
REALISTIC = """flowchart TD
    A[Start: ApplFblNvWriteDtcList] --> B[Declare ret]
    B --> C[Write DTC Index 0]
    C --> D{ENABLE_EYEQ_DTCTYPE42 defined?}
    D -- No --> J[Return ret]
    D -- Yes --> G{Pattern == UPDATE?}
    G -- No --> J
    G -- Yes --> H[Clear pattern]
    H --> I[Write ApplFblNvWriteFD0142]
    I --> J
"""


def _write(text):
    d = tempfile.mkdtemp()
    p = Path(d) / "x.mmd"
    p.write_text(text)
    return str(p)


def test_start_end_detection_topology():
    nodes, edges = parse_mermaid_file(_write(REALISTIC))
    assert flow_utils.detect_start(nodes, edges) == "A", "start must be the no-incoming node A"
    assert flow_utils.detect_ends(nodes, edges) == ["J"], "J is the only sink"
    # Old buggy behaviour would have fallen back to nodes[0]; ensure the label
    # 'Start: ...' is still correctly identified as start.
    assert nodes[0].id == "A"


def test_main_axis_single_x():
    nodes, edges = parse_mermaid_file(_write(SAMPLE))
    coords = compute_activity_layout(nodes, edges, x_center=800)
    main = find_main_flow_path(nodes, edges)
    xs = {coords[nid][0] for nid in main}
    assert xs == {800}, f"main-flow nodes must share one X axis, got {xs}"
    assert "A" in main and coords["A"][0] == 800


def test_layout_is_deterministic():
    nodes, edges = parse_mermaid_file(_write(SAMPLE))
    a = compute_activity_layout(nodes, edges)
    b = compute_activity_layout(nodes, edges)
    assert a == b, "layout must be identical across runs (no leaked state)"


def test_all_nodes_placed_and_unique_positions():
    nodes, edges = parse_mermaid_file(_write(SAMPLE))
    coords = compute_activity_layout(nodes, edges)
    assert set(coords) == {n.id for n in nodes}, "every node must be placed"
    # No two nodes share the same (x, y).
    assert len(set(coords.values())) == len(coords), "positions must not overlap exactly"


def test_merge_insertion_preserves_reachability():
    # Force a condition with two incoming edges.
    nodes = [
        Node("A", "Start", "action"),
        Node("B", "b", "action"),
        Node("C", "c?", "condition"),   # will receive 2 incoming edges
        Node("Z", "Return", "action"),
    ]
    edges = [
        Edge("A", "C", None),
        Edge("B", "C", None),
        Edge("A", "B", None),
        Edge("C", "Z", "yes"),
    ]
    # Before: C has 2 incoming -> flagged.
    v0 = flow_utils.validate_flow(nodes, edges)
    assert "C" in v0["multi_in_conditions"]

    n2, e2 = flow_utils.insert_merge_nodes(nodes, edges)
    v1 = flow_utils.validate_flow(n2, e2)
    assert v1["multi_in_conditions"] == [], "no condition may have >1 incoming after merge insertion"

    # Original reachability preserved: A and B still lead to C then Z.
    reach = flow_utils.reachable_from("A", n2, e2)
    assert {"C", "Z"} <= reach
    # Exactly one merge node was added.
    assert len(n2) == len(nodes) + 1


def test_continuity_true_on_sample():
    nodes, edges = parse_mermaid_file(_write(SAMPLE))
    assert check_continuity(nodes, edges) is True


def run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed")


if __name__ == "__main__":
    run_all()
