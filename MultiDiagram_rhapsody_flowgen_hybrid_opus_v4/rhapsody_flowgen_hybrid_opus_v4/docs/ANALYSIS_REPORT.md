# Rhapsody FlowGen — Analysis & Fixes (v3 → v3.2)

## Why the tool was ~70% correct
1) Start detection was string-based (`label=="start"`) → real labels like
   `Start: ApplFblNvWriteDtcList(...)` fell back to nodes[0]; Start rendered at
   the BOTTOM (log: 2480). Fixed: topology-based detection (no-incoming edge).
2) Edges dropped when the source had an inline label on the same line
   (`A[Start] --> B[..]`). Fixed: skeletonize labels before edge matching.
3) Five overlapping, stateful layout functions → non-deterministic output.
   Fixed: one deterministic longest-path pass.
4) Decisions with >1 incoming edge were rejected/dropped. Fixed: auto-insert
   explicit merge nodes (non-destructive).
5) COM could not persist node X/Y (log: empty read-back). Verified + hard-error;
   real geometry written via SBSX `m_transform`.
6) BMP export crashed on `tuple.count()`. Fixed.
7) **Action boxes empty** — COM has no working body setter on v109; an Action
   renders its model *body*. Fixed via SBSX `IState/_entryAction/IAction/_body`.
8) Decision Yes/No exited the same point. Fixed via distinct SBSX
   `m_SourcePort`/`m_TargetPort` per branch.

## Hybrid COM + SBSX
COM builds model + edges (works). SBSX post-processing sets text, geometry, and
decision ports (the 30% COM cannot do on this build). See
SBSX_SCHEMA_v109_PINNED.md and HYBRID_COM_SBSX_PLAN.md.

## Verification
- 7/7 pure-Python regression tests pass.
- End-to-end mmd→layout→emit_sbsx_plan→sbsx_patch verified (body, positions,
  distinct 3-way ports).
- SBSX primitives round-tripped on the REAL 27 MB v109 unit.
