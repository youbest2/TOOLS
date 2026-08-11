from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple
import json, math, textwrap

@dataclass(frozen=True)
class NodeBox:
    x: int
    y: int
    width: int
    height: int

def display_size(label: str, node_type: str) -> Tuple[int, int]:
    label = (label or '').strip()
    wrap = 34 if node_type == 'condition' else 44
    lines = textwrap.wrap(label, wrap, break_long_words=False, break_on_hyphens=False) or ['']
    width = min(620, max(250, 80 + min(wrap, max(map(len, lines))) * 8))
    height = max(75, 38 + len(lines) * 22)
    if node_type == 'condition':
        width = max(width, 330)
        height = max(height, 145)
    return int(width), int(height)

def build_plan(nodes, edges, coords: Dict[str, Tuple[float, float]]):
    boxes = {}
    for node in nodes:
        width, height = display_size(node.label, node.node_type)
        x, y = coords[node.id]
        boxes[node.id] = NodeBox(int(round(x)), int(round(y)), width, height)
    routes = {}
    for index, edge in enumerate(edges, 1):
        src, tgt = boxes[edge.source_id], boxes[edge.target_id]
        sx, sy = src.x + src.width // 2, src.y + src.height
        tx, ty = tgt.x + tgt.width // 2, tgt.y
        if ty >= sy:
            mid_y = sy + max(45, (ty - sy) // 2)
            points = [(sx, sy), (sx, mid_y), (tx, mid_y), (tx, ty)]
            source_side, target_side = 'BOTTOM', 'TOP'
        else:
            lane_x = max(src.x + src.width, tgt.x + tgt.width) + 180 + (index % 4) * 45
            points = [(sx, sy), (lane_x, sy), (lane_x, ty), (tx, ty)]
            source_side, target_side = 'BOTTOM', 'TOP'
        routes[f'{edge.source_id}_to_{edge.target_id}_{index}'] = {
            'source': edge.source_id, 'target': edge.target_id, 'label': edge.label or '',
            'source_side': source_side, 'target_side': target_side,
            'points': [{'x': x, 'y': y} for x, y in points],
        }
    return {
        'nodes': {k: vars(v) for k, v in boxes.items()},
        'edges': routes,
        'note': 'Edge routes are a deterministic orthogonal plan. Rhapsody COM still creates the control flows. Apply route points only after matching existing graphical connectors in a saved SBSX.',
    }

def write_plan(plan, path):
    Path(path).write_text(json.dumps(plan, indent=2), encoding='utf-8')
