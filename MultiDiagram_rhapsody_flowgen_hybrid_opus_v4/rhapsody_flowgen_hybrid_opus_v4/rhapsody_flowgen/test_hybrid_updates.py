from pathlib import Path
import tempfile, json
from rhapsody_flowgen.mermaid_parser import parse_mermaid_file
from rhapsody_flowgen.layout import compute_activity_layout
from rhapsody_flowgen.layout_plan import build_plan, display_size

def test_shape_parsing_and_plan():
    text='''flowchart TD\nA[Start] --> B[Long action statement that needs a wider display box]\nB -- Yes --> C{Is value valid?}\nC -- No --> B\nC -- Yes --> Z[Return result]\n'''
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'x.mmd';p.write_text(text)
        nodes,edges=parse_mermaid_file(str(p))
        by={n.id:n for n in nodes}
        assert by['C'].node_type=='condition'
        assert next(e for e in edges if e.source_id=='B').label=='Yes'
        plan=build_plan(nodes,edges,compute_activity_layout(nodes,edges))
        assert plan['nodes']['C']['height']>=145
        for route in plan['edges'].values():
            pts=route['points']
            assert all(a['x']==b['x'] or a['y']==b['y'] for a,b in zip(pts,pts[1:]))
if __name__=='__main__':
    test_shape_parsing_and_plan();print('PASS')
