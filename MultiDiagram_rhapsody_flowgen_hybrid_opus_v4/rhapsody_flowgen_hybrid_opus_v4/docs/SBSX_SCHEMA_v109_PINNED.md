# Rhapsody v109.0.1 SBSX schema — PINNED from the real FlashBootLoader unit

Discovered directly from your 27 MB `FlashBootloader - Copy.sbsx` (version
`109.0.1`, BuildNo 202011191713). All three "missing 30%" edits are now writable
and **verified by round-trip on the real file**.

## The exact places the on-canvas data lives

### Action visible text  (FIX-G — the empty boxes)
The rectangle shows the model action **body**, NOT its name:
```
IState  (_name = action_N)
  └─ _entryAction (type="p")
       └─ IAction
            └─ _body (type="a")   ← e.g. "Initialize retVal = E_NOT_OK"
```
COM on this build has no working body setter → boxes were empty. In SBSX we set
`_body` directly. (Conditions already showed text because a diamond renders a
different field; that's why only actions were blank.)

### Node position / size  (FIX-2)
```
CGIActionState
  ├─ _id                              graphical GUID
  ├─ m_pModelObject/IHandle/_hid      → model IState _id
  ├─ m_pParent                        → owning CGIStateChart _id
  ├─ m_name/CGIText/m_str             internal name (action_N / condition_N)
  ├─ m_transform  "sx 0 0 sy tx ty"   ← tx,ty = on-canvas position
  └─ m_polygon    "4 x0 y0 …"         local shape (size = extent × scale)
```
Set position by replacing the translate pair (tx,ty); scale is preserved.

### Distinct decision exit ports  (FIX-H — your Yes/No request)
Edges are `CGITrans`, and every one carries writable ports:
```
CGITrans
  ├─ m_pModelObject/IHandle (ITransition)
  ├─ m_pSource   → source CGIActionState _id
  ├─ m_pTarget   → target CGIActionState _id
  ├─ m_SourcePort  "x y"   ← exit point (set per branch: bottom/right/left)
  └─ m_TargetPort  "x y"   ← entry point
```

### Diagram scoping
```
IActivityDiagram/_name == "AD_AdcAbs_Get_VBATT_MON"  → model id
CGIStateChart.m_pModelObject/_hid == that id         → statechart _id
tool-generated (flat) diagram: CGIActionState.m_pParent == statechart _id
```
(The 204 pre-existing bootloader diagrams nest nodes under composite `CGIState`
frames; our generated diagram is flat, so `m_pParent == statechart` selects it.)

## What was verified in-session (against the REAL 27 MB unit)
```
lxml parse: 27,834,214 bytes, 520,420 elements, ~1–2 s
IState 'action_0' body read: "Initialize retVal = E_NOT_OK"
CGIActionState: 757    CGITrans: 1538 (ALL have m_SourcePort/m_TargetPort)
Round-trip WRITE + re-parse:
   set_action_body   : action_0 body -> new text            ✔ persisted
   set_node_position : m_transform 348 127 -> 800 200        ✔ scale kept
   set_edge_ports    : 490 53 / 525 -17 -> 925 395 / 1060 477 ✔
   XML declaration preserved, file re-parses cleanly          ✔
End-to-end flat-diagram patch (synthetic v109 structure):
   condition_2 exits RIGHT (1050 357) -> action_1 enters LEFT (800 237) ✔
   action bodies + positions applied, scoped to AD_Test               ✔
```

## Files
- `sbsx_patch_v109.py` — the pinned patcher (`inspect` / `patch`, dry-run + .bak).
- `sbsx_tools.py::emit_sbsx_plan()` — writes `sbsx_plan.json` with the exact
  internal names (`action_N`/`condition_N`) and FIX-H ports.
- `com_introspect.py` — optional: confirms COM has no body setter on your build
  (already implied by your run log).

## End-to-end recipe
```
# 1) COM builds model + edges, saves + CLOSES the project, and emits the plan:
#    (add to rhapsody_interface, after layout)
from rhapsody_flowgen.sbsx_tools import emit_sbsx_plan
emit_sbsx_plan(nodes, edges, node_coords,
               os.path.join(os.path.dirname(__file__), "sbsx_plan.json"))

# 2) With Rhapsody CLOSED, patch the saved unit (dry-run first):
python -m rhapsody_flowgen.sbsx_patch_v109 inspect \
       --sbsx "<project>\...\<unit>.sbsx" --diagram AD_AdcAbs_Get_VBATT_MON
python -m rhapsody_flowgen.sbsx_patch_v109 patch \
       --sbsx "<unit>.sbsx" --diagram AD_AdcAbs_Get_VBATT_MON \
       --plan sbsx_plan.json            # dry-run
python -m rhapsody_flowgen.sbsx_patch_v109 patch ... --plan sbsx_plan.json --write

# 3) Reopen the project in Rhapsody — boxes now show text, nodes are positioned,
#    and each decision's branches leave from distinct vertices.
```

## Honest caveats
- Do the SBSX edit with the project **closed**, then reopen (avoid save-overwrite).
- `patch` is **dry-run by default** and always writes a `.bak`.
- The port pixel scale in `m_SourcePort/m_TargetPort` is in the diagram's node-
  local units; the plan uses the same 250×75 box the COM builder created, so the
  bottom/right/left vertices line up. If your Rhapsody re-normalizes ports on
  open, tell me and I'll switch to writing the connector `m_transform` waypoints
  instead (the tool already isolates that in `set_edge_ports`).
- This `Copy` you sent has the `AD_` target **empty** (0 nodes) — expected, it
  predates a populated run. The patcher is proven on real v109 elements and on a
  flat generated-diagram fixture; run it after a COM build that populates the
  diagram.
