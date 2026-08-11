# CHANGES — hybrid v3 → v3.2 (complete)

## Summary of all fixes shipped
| ID | Problem (evidence) | Fix | File |
|----|--------------------|-----|------|
| A | Start placed at bottom; wrong axis (log: Start at 2480) | topology-based start/end | flow_utils.py, layout.py |
| B | Edges dropped when source had inline label (log missing A→B) | skeletonize before edge match | mermaid_parser.py |
| C | 5 stateful, non-deterministic layout funcs | one deterministic pass | layout.py |
| D | Decisions with >1 incoming rejected/dropped | auto-insert merge nodes | flow_utils.py, rhapsody_interface.py |
| E | Geometry X/Y never persisted via COM | position via AddNewNodeForElement + hard-error verify; **SBSX writes m_transform** | rhapsody_interface.py, sbsx_patch_v109.py |
| F | BMP export crash `tuple.count()` | collection vs tuple/list handling | rhapsody_interface.py |
| G | **Action boxes empty** (log: 16× could-not-set-text) | set model IState/_entryAction/IAction/_body via SBSX | sbsx_patch_v109.py |
| H | Decision Yes/No exit same point | distinct m_SourcePort/m_TargetPort per branch | rhapsody_interface.py, sbsx_patch_v109.py |

## Hybrid architecture (why the tool was stuck at 70%)
COM on Rhapsody 109.0.1 **cannot** set an Action's body text and **cannot**
persist node X/Y. Those live in the saved SBSX unit. So:
- **COM** builds the model + all control-flow edges (works; 22/22 in your run).
- **SBSX post-process** (`sbsx_patch_v109.py`) sets text, geometry, and the
  distinct decision exit ports.

## Schema pinned (Rhapsody 109.0.1, from your FlashBootLoader unit)
- Action text  → `IState/_entryAction/IAction/_body`
- Node position → `CGIActionState/m_transform` (translate = last 2 numbers)
- Edge ports   → `CGITrans/m_SourcePort` & `m_TargetPort`
- Scope        → `IActivityDiagram._name` → `CGIStateChart` → nodes by `m_pParent`

## Tests (this build)
```
test_flow_fixes.py                          7/7 PASS
end-to-end mmd→layout→emit_sbsx_plan→patch  PASS
  - init action body set                    ✔
  - node positions set (scale preserved)    ✔
  - 3-way decision ports distinct           bottom/right/left ✔
py_compile all modules                      0 failures
SBSX round-trip on REAL 27MB unit           body+pos+ports persisted ✔
```

## New public entry points
- `flow_utils.validate_flow(nodes, edges)` → structural report.
- `sbsx_tools.emit_sbsx_plan(nodes, edges, coords, path)` → sbsx_plan.json
  (auto-called at the end of the COM build).
- `sbsx_patch_v109.py` CLI: `inspect` / `patch` (dry-run + .bak).
