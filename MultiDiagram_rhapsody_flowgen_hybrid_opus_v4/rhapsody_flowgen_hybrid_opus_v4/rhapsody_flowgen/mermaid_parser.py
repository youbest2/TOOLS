# rhapsody_flowgen/mermaid_parser.py
# Final Version - Implemented a corrected two-pass parsing strategy.

import re
import os
import logging
from typing import List, Tuple, NamedTuple, Optional
from collections import defaultdict

class MermaidParseError(Exception):
    """Custom exception for errors during Mermaid file parsing."""
    pass

class Node(NamedTuple):
    id: str
    label: str
    node_type: str  # 'condition' or 'action'

class Edge(NamedTuple):
    source_id: str
    target_id: str
    label: Optional[str]

def parse_mermaid_file(file_path: str) -> Tuple[List[Node], List[Edge]]:
    """
    Parses a Mermaid flowchart using a robust two-pass strategy.
    First, it identifies all nodes, then it identifies the edges connecting them.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Mermaid file not found at: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    nodes = {}
    edges = []
    
    # --- REGEX DEFINITIONS ---
    # Improved: Matches node definitions like: A[Start] or B{Is...?}, even if label contains ']' or '}'
    node_pattern = re.compile(r'([a-zA-Z0-9_]+)(\[[^\]]*\]|\{[^\}]*\})')
    # Matches edges like: B -- No --> Z or C --> D
    # It correctly handles optional labels between the dashes.
    edge_pattern = re.compile(r'\b([a-zA-Z0-9_]+)\b\s*(?:--\s*(.*?)\s*-->|-->)\s*\b([a-zA-Z0-9_]+)\b')


    # --- PASS 1: IDENTIFY ALL EXPLICITLY DEFINED NODES ---
    # This pass ensures all nodes with detailed labels are known first.
    for line in lines:
        # Find all node definitions on the current line
        matches = node_pattern.findall(line)
        for node_id, full_definition in matches:
            label = full_definition[1:-1] # Strip the outer brackets/braces
            # Determine node type by bracket type
            if full_definition.startswith('{'):
                node_type = 'condition'
            elif full_definition.startswith('['):
                node_type = 'action'
            else:
                node_type = 'action'
            logging.info(f"Node parsed: id={node_id}, label='{label.strip()}', node_type={node_type}")
            nodes[node_id] = Node(node_id, label.strip(), node_type)

    # --- PASS 2: IDENTIFY ALL EDGES AND IMPLICIT NODES ---
    # hybrid_v3 FIX: strip inline node labels ("A[Start]" -> "A", "C{q?}" -> "C")
    # BEFORE edge matching. In v2 the edge regex could not match an edge whose
    # *source* carried an inline bracket/brace on the same line, e.g.
    #   A[Start] --> B[Check Sensor Status]
    # which silently DROPPED the A->B edge (root-cause of missing edges).
    label_strip_pattern = re.compile(r'([a-zA-Z0-9_]+)\s*(?:\[[^\]]*\]|\{[^\}]*\})')
    for i, line in enumerate(lines):
        line = line.strip()
        if '-->' not in line:
            continue

        # Skeletonize: collapse "ID[...]" / "ID{...}" to bare "ID" for matching.
        skeleton = label_strip_pattern.sub(r'\1', line)

        # Find all edge connections on the current (skeletonized) line
        matches = edge_pattern.findall(skeleton)
        if not matches:
            # This handles cases where a line has '-->' but doesn't match the main pattern
            # for example, if it's commented out or part of a node label.
            logging.debug(f"Line {i+1} contains '-->' but did not match edge pattern: '{skeleton}'")
            continue

        for src, label, tgt in matches:
            # The regex structure ensures that if `label` is not found, it is an empty string.
            edge_label = label.strip() if label else None
            edges.append(Edge(src, tgt, edge_label))

            # If a node was used in an edge but not explicitly defined in Pass 1,
            # add it now implicitly using its ID as the label.
            for node_id in [src, tgt]:
                if node_id not in nodes:
                    # Implicit nodes default to action
                    nodes[node_id] = Node(node_id, node_id, 'action')

    if not nodes and not edges:
        raise MermaidParseError(f"Failed to parse any nodes or edges from {file_path}.")
    
    # --- ORDERING ---
    # Return nodes in a logical sequence based on their appearance in the edges.
    ordered_node_ids = []
    if edges:
        # Start with the very first node in the flow
        ordered_node_ids.append(edges[0].source_id)
    
    for edge in edges:
        if edge.source_id not in ordered_node_ids: ordered_node_ids.append(edge.source_id)
        if edge.target_id not in ordered_node_ids: ordered_node_ids.append(edge.target_id)
    
    # Ensure any disconnected nodes are still included at the end
    for node_id in nodes.keys():
        if node_id not in ordered_node_ids: ordered_node_ids.append(node_id)
        
    ordered_nodes = [nodes[nid] for nid in ordered_node_ids]
    return ordered_nodes, edges

def check_rhapsody_condition_compatibility(nodes: list, edges: list):
    """
    Checks if any 'condition' node has more than one incoming edge (not allowed in Rhapsody).
    Raises RuntimeError with a clear message if any are found.
    """
    incoming_edges = defaultdict(list)
    for edge in edges:
        incoming_edges[edge.target_id].append(edge.source_id)
    condition_nodes = {n.id: n for n in nodes if n.node_type == 'condition'}
    incompatible_conditions = [
        (nid, condition_nodes[nid], incoming_edges[nid])
        for nid in condition_nodes
        if len(incoming_edges[nid]) > 1
    ]
    if incompatible_conditions:
        msg = ("❌ MODELING ERROR: The following 'Condition' nodes have multiple incoming edges, "
               "which is not allowed in Rhapsody. Please refactor the Mermaid model to insert explicit merge nodes "
               "or ensure only one incoming edge per condition node.\n" +
               "\n".join([f"  - id={nid}, label='{node.label}', incoming from: {srcs}" for nid, node, srcs in incompatible_conditions]))
        print(msg)
        logging.error(msg)
        raise RuntimeError(msg)
